import json
import re
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest


def test_scheduler_status_json_reports_absent_task_without_registering():
    powershell = shutil.which("powershell.exe")
    if not powershell:
        pytest.skip("Windows PowerShell is not available")

    project_root = Path(__file__).resolve().parents[1]
    script_path = project_root / "scripts" / "Register-NotifyNewTask.ps1"
    task_name = f"MailAgentNotifyNewTest-{uuid.uuid4()}"

    result = subprocess.run(
        [
            powershell,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script_path),
            "-TaskName",
            task_name,
            "-Status",
            "-Json",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    payload = json.loads(result.stdout)
    assert payload == {
        "task_name": task_name,
        "registered": False,
        "state": None,
        "last_run": None,
        "last_result": None,
        "next_run": None,
    }


def test_scheduler_status_json_helper_serializes_dates_as_iso_strings():
    powershell = shutil.which("powershell.exe")
    if not powershell:
        pytest.skip("Windows PowerShell is not available")

    project_root = Path(__file__).resolve().parents[1]
    script_path = project_root / "scripts" / "Register-NotifyNewTask.ps1"

    command = (
        f". '{script_path}'; "
        "[ordered]@{"
        "date = Convert-SchedulerDateTimeToJsonValue ([datetime]'2026-07-01T10:32:32'); "
        "missing = Convert-SchedulerDateTimeToJsonValue $null; "
        "min = Convert-SchedulerDateTimeToJsonValue ([datetime]::MinValue); "
        "never = Convert-SchedulerDateTimeToJsonValue 'Never'"
        "} | ConvertTo-Json -Compress"
    )

    result = subprocess.run(
        [
            powershell,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            command,
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    payload = json.loads(result.stdout)
    assert re.fullmatch(r"2026-07-01T10:32:32[+-]\d{2}:\d{2}", payload["date"])
    assert "/Date(" not in result.stdout
    assert payload["missing"] is None
    assert payload["min"] is None
    assert payload["never"] is None
