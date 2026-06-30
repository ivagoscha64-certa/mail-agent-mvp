param(
    [string]$TaskName = "MailAgentNotifyNew",
    [int]$EveryMinutes = 10,
    [int]$Limit = 25,
    [switch]$Register,
    [switch]$Unregister,
    [switch]$Status,
    [switch]$Json
)

$ErrorActionPreference = "Stop"

function Get-DotEnvValue {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Name
    )

    if (-not (Test-Path -LiteralPath $Path)) {
        return $null
    }

    foreach ($line in Get-Content -LiteralPath $Path) {
        $trimmed = $line.Trim()
        if ($trimmed.Length -eq 0 -or $trimmed.StartsWith("#")) {
            continue
        }

        $parts = $trimmed -split "=", 2
        if ($parts.Count -eq 2 -and $parts[0].Trim() -eq $Name) {
            return $parts[1].Trim().Trim('"').Trim("'")
        }
    }

    return $null
}

function Assert-ReadOnlyMode {
    param([Parameter(Mandatory = $true)][string]$EnvPath)

    $mode = Get-DotEnvValue -Path $EnvPath -Name "MAIL_AGENT_MODE"
    if ($mode -and $mode -ne "read_only") {
        throw "Refusing to create a scheduled task because MAIL_AGENT_MODE is '$mode', not 'read_only'."
    }
}

function Show-TaskPlan {
    param(
        [Parameter(Mandatory = $true)][string]$ProjectRoot,
        [Parameter(Mandatory = $true)][string]$PythonExe,
        [Parameter(Mandatory = $true)][string]$TaskName,
        [Parameter(Mandatory = $true)][int]$EveryMinutes,
        [Parameter(Mandatory = $true)][int]$Limit
    )

    Write-Host "Task Scheduler dry-run plan:"
    Write-Host "  Task name:        $TaskName"
    Write-Host "  Working folder:   $ProjectRoot"
    Write-Host "  Program:          $PythonExe"
    Write-Host "  Arguments:        -m mail_agent notify-new --limit $Limit"
    Write-Host "  Schedule:         every $EveryMinutes minute(s)"
    Write-Host "  Read-only mode:   enforced by project .env/config"
    Write-Host ""
    Write-Host "No task was created. Re-run with -Register to create it."
}

$selectedActions = @($Register, $Unregister, $Status) | Where-Object { $_ }
if ($selectedActions.Count -gt 1) {
    throw "Choose only one of -Register, -Unregister, or -Status."
}

if ($EveryMinutes -lt 5) {
    throw "EveryMinutes must be at least 5 to avoid overly frequent Gmail/Telegram polling."
}

if ($Limit -lt 1 -or $Limit -gt 100) {
    throw "Limit must be between 1 and 100."
}

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Split-Path -Parent $scriptDir
$envPath = Join-Path $projectRoot ".env"
$pythonExe = Join-Path $projectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $projectRoot)) {
    throw "Project folder not found: $projectRoot"
}

if (-not (Test-Path -LiteralPath $pythonExe)) {
    throw "Python virtualenv executable not found: $pythonExe"
}

Assert-ReadOnlyMode -EnvPath $envPath

if ($Status) {
    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if (-not $task) {
        if ($Json) {
            [ordered]@{
                task_name = $TaskName
                registered = $false
                state = $null
                last_run = $null
                last_result = $null
                next_run = $null
            } | ConvertTo-Json -Compress
            exit 0
        }

        Write-Host "Scheduled task '$TaskName' is not registered."
        exit 0
    }

    $info = Get-ScheduledTaskInfo -TaskName $TaskName
    if ($Json) {
        [ordered]@{
            task_name = $TaskName
            registered = $true
            state = [string]$task.State
            last_run = $info.LastRunTime
            last_result = $info.LastTaskResult
            next_run = $info.NextRunTime
        } | ConvertTo-Json -Compress
        exit 0
    }

    Write-Host "Scheduled task '$TaskName' is registered."
    Write-Host "  State:        $($task.State)"
    Write-Host "  Last run:     $($info.LastRunTime)"
    Write-Host "  Last result:  $($info.LastTaskResult)"
    Write-Host "  Next run:     $($info.NextRunTime)"
    exit 0
}

if ($Unregister) {
    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if (-not $task) {
        Write-Host "Scheduled task '$TaskName' is already absent."
        exit 0
    }

    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "Removed scheduled task '$TaskName'."
    exit 0
}

if (-not $Register) {
    Show-TaskPlan `
        -ProjectRoot $projectRoot `
        -PythonExe $pythonExe `
        -TaskName $TaskName `
        -EveryMinutes $EveryMinutes `
        -Limit $Limit
    exit 0
}

$action = New-ScheduledTaskAction `
    -Execute $pythonExe `
    -Argument "-m mail_agent notify-new --limit $Limit" `
    -WorkingDirectory $projectRoot

$trigger = New-ScheduledTaskTrigger `
    -Once `
    -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Minutes $EveryMinutes) `
    -RepetitionDuration (New-TimeSpan -Days 3650)

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10) `
    -MultipleInstances IgnoreNew `
    -StartWhenAvailable

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Description "Runs mail-agent notify-new in read-only mode for iva196464@gmail.com." `
    -Force | Out-Null

Write-Host "Created or updated scheduled task '$TaskName'."
Write-Host "It runs from '$projectRoot' every $EveryMinutes minute(s):"
Write-Host "  .\.venv\Scripts\python.exe -m mail_agent notify-new --limit $Limit"
