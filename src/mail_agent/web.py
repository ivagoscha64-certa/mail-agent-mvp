from __future__ import annotations

import json
from html import escape
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from ipaddress import ip_address
from urllib.parse import parse_qs, urlparse

from mail_agent.config import load_settings
from mail_agent.diagnostics import (
    build_audit_events_payload,
    build_health_payload,
    build_message_stats_payload,
    build_operational_review_payload,
    build_run_log_events_payload,
    build_runs_payload,
)


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765


def is_loopback_bind_host(host: str) -> bool:
    normalized = host.strip().lower()
    if normalized == "localhost":
        return True
    if normalized.startswith("[") and normalized.endswith("]"):
        normalized = normalized[1:-1]
    try:
        return ip_address(normalized).is_loopback
    except ValueError:
        return False


def run_web_server(*, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> None:
    server = ThreadingHTTPServer((host, port), MailAgentWebHandler)
    print(f"Mail agent web panel listening on http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nMail agent web panel stopped.")
    finally:
        server.server_close()


class MailAgentWebHandler(BaseHTTPRequestHandler):
    server_version = "MailAgentWeb/0.1"

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/":
                query = parse_qs(parsed.query)
                settings = load_settings()
                payload = build_health_payload(
                    settings,
                    run_limit=10,
                    include_scheduler=False,
                    scheduler_task_name="MailAgentNotifyNew",
                )
                run_log_payload = build_run_log_events_payload(
                    settings,
                    limit=_limit_from_query(parsed.query, default=10),
                    command=_query_value(query, "command"),
                    status=_query_value(query, "status"),
                    finished_from=_query_value(query, "finished_from"),
                    finished_to=_query_value(query, "finished_to"),
                )
                self._send_html(render_dashboard(payload, run_log_payload))
                return

            if parsed.path == "/audit":
                settings = load_settings()
                query = parse_qs(parsed.query)
                audit_payload = build_audit_events_payload(
                    settings,
                    limit=_limit_from_query(parsed.query, default=25),
                    action=_query_value(query, "action"),
                    status=_query_value(query, "status"),
                    account=_query_value(query, "account"),
                )
                stats_payload = build_message_stats_payload(
                    settings,
                    sender_limit=_sender_limit_from_query(
                        parsed.query,
                        default=10,
                    ),
                    date_from=_query_value(query, "date_from"),
                    date_to=_query_value(query, "date_to"),
                )
                self._send_html(render_audit_page(audit_payload, stats_payload))
                return

            if parsed.path == "/api/health":
                payload = build_health_payload(
                    load_settings(),
                    run_limit=_limit_from_query(parsed.query, default=10),
                    include_scheduler=False,
                    scheduler_task_name="MailAgentNotifyNew",
                )
                self._send_json(payload)
                return

            if parsed.path == "/api/audit-events":
                query = parse_qs(parsed.query)
                payload = build_audit_events_payload(
                    load_settings(),
                    limit=_limit_from_query(parsed.query, default=25),
                    action=_query_value(query, "action"),
                    status=_query_value(query, "status"),
                    account=_query_value(query, "account"),
                )
                self._send_json(payload)
                return

            if parsed.path == "/api/message-stats":
                query = parse_qs(parsed.query)
                payload = build_message_stats_payload(
                    load_settings(),
                    sender_limit=_sender_limit_from_query(parsed.query, default=10),
                    date_from=_query_value(query, "date_from"),
                    date_to=_query_value(query, "date_to"),
                )
                self._send_json(payload)
                return

            if parsed.path == "/api/run-log-events":
                query = parse_qs(parsed.query)
                payload = build_run_log_events_payload(
                    load_settings(),
                    limit=_limit_from_query(parsed.query, default=10),
                    command=_query_value(query, "command"),
                    status=_query_value(query, "status"),
                    finished_from=_query_value(query, "finished_from"),
                    finished_to=_query_value(query, "finished_to"),
                )
                self._send_json(payload)
                return

            if parsed.path == "/api/operational-review":
                payload = build_operational_review_payload(
                    load_settings(),
                    limit=_limit_from_query(parsed.query, default=10),
                    sender_limit=_limit_from_query(
                        parsed.query,
                        default=10,
                        param="sender_limit",
                    ),
                )
                self._send_json(payload)
                return

            if parsed.path == "/api/runs":
                payload = build_runs_payload(
                    load_settings(),
                    limit=_limit_from_query(parsed.query, default=10),
                )
                self._send_json(payload)
                return

            if parsed.path == "/favicon.ico":
                self._send_no_content()
                return
        except ValueError as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return

        self._send_json({"error": "Not found"}, status=HTTPStatus.NOT_FOUND)

    def log_message(self, format: str, *args) -> None:
        return

    def _send_json(
        self,
        payload: dict,
        *,
        status: HTTPStatus = HTTPStatus.OK,
    ) -> None:
        body = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_no_content(self) -> None:
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

    def _send_html(
        self,
        html: str,
        *,
        status: HTTPStatus = HTTPStatus.OK,
    ) -> None:
        body = html.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)


def render_dashboard(payload: dict, run_log_payload: dict) -> str:
    db_info = payload["db"]
    latest = payload["latest_notify_run"]
    last_success = payload["last_successful_notify_run"]
    rows = payload["runs"]
    run_log_filters = run_log_payload["filters"]

    latest_cells = _run_summary_cells(latest)
    run_rows = "\n".join(_render_run_row(row) for row in rows)
    if not run_rows:
        run_rows = '<tr><td colspan="8" class="muted">No notify-new runs recorded.</td></tr>'
    run_log_rows = "\n".join(
        _render_run_log_event_row(row) for row in run_log_payload["run_log_events"]
    )
    if not run_log_rows:
        run_log_rows = '<tr><td colspan="9" class="muted">No run log events recorded.</td></tr>'
    run_log_filter_form = _render_run_log_filter_form(run_log_filters)

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <link rel="icon" href="data:,">
  <title>Mail Agent Panel</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f6f7f9;
      --panel: #ffffff;
      --text: #1f2933;
      --muted: #607080;
      --border: #d9e0e7;
      --accent: #0f766e;
      --warn: #a04b00;
    }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: Arial, Helvetica, sans-serif;
      font-size: 15px;
      line-height: 1.45;
    }}
    main {{
      max-width: 1120px;
      margin: 0 auto;
      padding: 28px 18px 40px;
    }}
    h1 {{
      margin: 0 0 18px;
      font-size: 28px;
      font-weight: 700;
    }}
    h2 {{
      margin: 0 0 12px;
      font-size: 18px;
    }}
    section {{
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 6px;
      padding: 16px;
      margin-bottom: 16px;
    }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
      gap: 12px;
    }}
    .metric {{
      border: 1px solid var(--border);
      border-radius: 6px;
      padding: 12px;
      min-width: 0;
    }}
    .label {{
      color: var(--muted);
      font-size: 12px;
      text-transform: uppercase;
    }}
    .value {{
      margin-top: 4px;
      font-weight: 700;
      overflow-wrap: anywhere;
    }}
    .badge {{
      display: inline-block;
      color: #ffffff;
      background: var(--accent);
      border-radius: 999px;
      padding: 2px 8px;
      font-weight: 700;
    }}
    .muted {{
      color: var(--muted);
    }}
    .error {{
      color: var(--warn);
      overflow-wrap: anywhere;
    }}
    .nav {{
      margin: -8px 0 16px;
    }}
    .filters {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
      gap: 10px;
      margin-bottom: 12px;
    }}
    .filters label {{
      color: var(--muted);
      font-size: 12px;
      font-weight: 700;
      text-transform: uppercase;
    }}
    .filters input {{
      box-sizing: border-box;
      width: 100%;
      margin-top: 4px;
      border: 1px solid var(--border);
      border-radius: 6px;
      padding: 8px 9px;
      color: var(--text);
      font: inherit;
    }}
    .filters button {{
      align-self: end;
      border: 1px solid var(--accent);
      border-radius: 6px;
      background: var(--accent);
      color: #ffffff;
      cursor: pointer;
      font: inherit;
      font-weight: 700;
      padding: 8px 12px;
    }}
    a {{
      color: var(--accent);
      font-weight: 700;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      table-layout: fixed;
    }}
    th, td {{
      border-bottom: 1px solid var(--border);
      padding: 9px 8px;
      text-align: left;
      vertical-align: top;
      overflow-wrap: anywhere;
    }}
    th {{
      color: var(--muted);
      font-size: 12px;
      text-transform: uppercase;
    }}
    @media (max-width: 760px) {{
      main {{
        padding: 18px 10px 28px;
      }}
      table {{
        display: block;
        overflow-x: auto;
        table-layout: auto;
        white-space: nowrap;
      }}
    }}
  </style>
</head>
<body>
  <main>
    <h1>Mail Agent Panel</h1>
    <div class="nav"><a href="/audit">Audit events and message stats</a></div>
    <section>
      <h2>Local State</h2>
      <div class="grid">
        {_metric("Mode", f'<span class="badge">{_text(payload["mode"])}</span>')}
        {_metric("Account", _text(payload["account"]))}
        {_metric("Backend", _text(payload["backend"]))}
        {_metric("Provider", _text(payload["provider"]))}
      </div>
    </section>
    <section>
      <h2>Database</h2>
      <div class="grid">
        {_metric("Exists", _yes_no(db_info["exists"]))}
        {_metric("Readable", _yes_no(db_info["readable"]))}
        {_metric("Path", _text(db_info["path"]))}
        {_metric("Messages", _number_or_none(db_info["messages"]))}
        {_metric("Audit Events", _number_or_none(db_info["audit_events"]))}
      </div>
      {_db_error(db_info)}
    </section>
    <section>
      <h2>Latest notify-new</h2>
      <div class="grid">
        {_metric("Status", latest_cells["status"])}
        {_metric("Finished", latest_cells["finished_at"])}
        {_metric("New", latest_cells["new_count"])}
        {_metric("Existing", latest_cells["existing_count"])}
        {_metric("Notified", latest_cells["notified_count"])}
        {_metric("Error", latest_cells["error"])}
      </div>
    </section>
    <section>
      <h2>Last Successful notify-new</h2>
      <div class="grid">
        {_metric("Finished", _text(last_success["finished_at"]) if last_success else '<span class="muted">none</span>')}
        {_metric("New", _number_or_none(last_success["new_count"] if last_success else None))}
        {_metric("Existing", _number_or_none(last_success["existing_count"] if last_success else None))}
        {_metric("Notified", _number_or_none(last_success["notified_count"] if last_success else None))}
      </div>
    </section>
    <section>
      <h2>Run Log Events</h2>
      {run_log_filter_form}
      {_payload_error(run_log_payload)}
      <table>
        <thead>
          <tr>
            <th>Finished</th>
            <th>Command</th>
            <th>Status</th>
            <th>Account</th>
            <th>Provider</th>
            <th>Limit</th>
            <th>New</th>
            <th>Notified</th>
            <th>Error</th>
          </tr>
        </thead>
        <tbody>
          {run_log_rows}
        </tbody>
      </table>
    </section>
    <section>
      <h2>Recent Runs</h2>
      <table>
        <thead>
          <tr>
            <th>Finished</th>
            <th>Status</th>
            <th>Limit</th>
            <th>New</th>
            <th>Existing</th>
            <th>Notified</th>
            <th>Phase</th>
            <th>Error</th>
          </tr>
        </thead>
        <tbody>
          {run_rows}
        </tbody>
      </table>
    </section>
  </main>
</body>
</html>"""


def render_audit_page(audit_payload: dict, stats_payload: dict) -> str:
    audit_filters = audit_payload["filters"]
    stats_filters = stats_payload["filters"]
    audit_rows = "\n".join(
        _render_audit_event_row(row) for row in audit_payload["audit_events"]
    )
    if not audit_rows:
        audit_rows = '<tr><td colspan="7" class="muted">No audit events recorded.</td></tr>'

    day_rows = "\n".join(
        f"<tr><td>{_text(row['day'])}</td><td>{_number_or_none(row['count'])}</td></tr>"
        for row in stats_payload["messages_by_day"]
    )
    if not day_rows:
        day_rows = '<tr><td colspan="2" class="muted">No messages recorded.</td></tr>'

    sender_rows = "\n".join(
        f"<tr><td>{_text(row['sender'])}</td>"
        f"<td>{_number_or_none(row['count'])}</td>"
        f"<td>{_text(row['latest_created_at'])}</td></tr>"
        for row in stats_payload["top_senders"]
    )
    if not sender_rows:
        sender_rows = '<tr><td colspan="3" class="muted">No senders recorded.</td></tr>'

    audit_filter_form = _render_audit_filter_form(audit_filters, stats_filters)
    stats_filter_form = _render_stats_filter_form(stats_filters, audit_filters)

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <link rel="icon" href="data:,">
  <title>Mail Agent Audit</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f6f7f9;
      --panel: #ffffff;
      --text: #1f2933;
      --muted: #607080;
      --border: #d9e0e7;
      --accent: #0f766e;
      --warn: #a04b00;
    }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: Arial, Helvetica, sans-serif;
      font-size: 15px;
      line-height: 1.45;
    }}
    main {{
      max-width: 1120px;
      margin: 0 auto;
      padding: 28px 18px 40px;
    }}
    h1 {{
      margin: 0 0 18px;
      font-size: 28px;
      font-weight: 700;
    }}
    h2 {{
      margin: 0 0 12px;
      font-size: 18px;
    }}
    section {{
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 6px;
      padding: 16px;
      margin-bottom: 16px;
    }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 16px;
    }}
    .metric {{
      border: 1px solid var(--border);
      border-radius: 6px;
      padding: 12px;
      min-width: 0;
    }}
    .label {{
      color: var(--muted);
      font-size: 12px;
      text-transform: uppercase;
    }}
    .value {{
      margin-top: 4px;
      font-weight: 700;
      overflow-wrap: anywhere;
    }}
    .muted {{
      color: var(--muted);
    }}
    .error {{
      color: var(--warn);
      overflow-wrap: anywhere;
    }}
    .nav {{
      margin: -8px 0 16px;
    }}
    .filters {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
      gap: 10px;
      margin-bottom: 12px;
    }}
    .filters label {{
      color: var(--muted);
      font-size: 12px;
      font-weight: 700;
      text-transform: uppercase;
    }}
    .filters input {{
      box-sizing: border-box;
      width: 100%;
      margin-top: 4px;
      border: 1px solid var(--border);
      border-radius: 6px;
      padding: 8px 9px;
      color: var(--text);
      font: inherit;
    }}
    .filters button {{
      align-self: end;
      border: 1px solid var(--accent);
      border-radius: 6px;
      background: var(--accent);
      color: #ffffff;
      cursor: pointer;
      font: inherit;
      font-weight: 700;
      padding: 8px 12px;
    }}
    a {{
      color: var(--accent);
      font-weight: 700;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      table-layout: fixed;
    }}
    th, td {{
      border-bottom: 1px solid var(--border);
      padding: 9px 8px;
      text-align: left;
      vertical-align: top;
      overflow-wrap: anywhere;
    }}
    th {{
      color: var(--muted);
      font-size: 12px;
      text-transform: uppercase;
    }}
    @media (max-width: 760px) {{
      main {{
        padding: 18px 10px 28px;
      }}
      table {{
        display: block;
        overflow-x: auto;
        table-layout: auto;
        white-space: nowrap;
      }}
    }}
  </style>
</head>
<body>
  <main>
    <h1>Mail Agent Audit</h1>
    <div class="nav"><a href="/">Dashboard</a></div>
    <section>
      <h2>Database</h2>
      <div class="grid">
        {_metric("Audit DB Exists", _yes_no(audit_payload["exists"]))}
        {_metric("Audit DB Readable", _yes_no(audit_payload["readable"]))}
        {_metric("Stats DB Exists", _yes_no(stats_payload["exists"]))}
        {_metric("Stats DB Readable", _yes_no(stats_payload["readable"]))}
        {_metric("Path", _text(audit_payload["db"]))}
        {_metric("Total Messages", _number_or_none(stats_payload["total_messages"]))}
      </div>
      {_payload_error(audit_payload)}
      {_payload_error(stats_payload)}
    </section>
    <section>
      <h2>Messages By Day</h2>
      {stats_filter_form}
      <table>
        <thead><tr><th>Day</th><th>Messages</th></tr></thead>
        <tbody>{day_rows}</tbody>
      </table>
    </section>
    <section>
      <h2>Top Senders</h2>
      <table>
        <thead><tr><th>Sender</th><th>Messages</th><th>Latest Stored</th></tr></thead>
        <tbody>{sender_rows}</tbody>
      </table>
    </section>
    <section>
      <h2>Recent Audit Events</h2>
      {audit_filter_form}
      <table>
        <thead>
          <tr>
            <th>Created</th>
            <th>Action</th>
            <th>Status</th>
            <th>Account</th>
            <th>Message UID</th>
            <th>Reason</th>
            <th>Metadata</th>
          </tr>
        </thead>
        <tbody>{audit_rows}</tbody>
      </table>
    </section>
  </main>
  <script>
    document.querySelectorAll('form.filters').forEach((form) => {{
      form.addEventListener('submit', () => {{
        form.querySelectorAll('input[type="hidden"][data-preserve-name]').forEach((hidden) => {{
          const preserveName = hidden.dataset.preserveName;
          const current = Array.from(document.querySelectorAll('input[name]')).find(
            (input) => input.name === preserveName && input.type !== 'hidden'
          );
          if (current && current.value) {{
            hidden.name = preserveName;
            hidden.value = current.value;
          }} else {{
            hidden.removeAttribute('name');
            hidden.value = '';
          }}
        }});
      }});
    }});
  </script>
</body>
</html>"""


def _limit_from_query(query: str, *, default: int, param: str = "limit") -> int:
    values = parse_qs(query).get(param, [])
    if not values:
        return default
    try:
        limit = int(values[0])
    except ValueError as exc:
        raise ValueError(f"{param} must be an integer") from exc
    if limit < 1:
        raise ValueError(f"{param} must be at least 1")
    return limit


def _sender_limit_from_query(query: str, *, default: int) -> int:
    parsed = parse_qs(query)
    if "sender_limit" in parsed:
        return _limit_from_query(query, default=default, param="sender_limit")
    return _limit_from_query(query, default=default, param="limit")


def _query_value(query: dict[str, list[str]], name: str) -> str | None:
    values = query.get(name, [])
    if not values:
        return None
    return values[0]


def _render_run_row(row: dict) -> str:
    error = row["error"] or ""
    return (
        "<tr>"
        f"<td>{_text(row['finished_at'])}</td>"
        f"<td>{_text(row['status'])}</td>"
        f"<td>{_number_or_none(row['limit'])}</td>"
        f"<td>{_number_or_none(row['new_count'])}</td>"
        f"<td>{_number_or_none(row['existing_count'])}</td>"
        f"<td>{_number_or_none(row['notified_count'])}</td>"
        f"<td>{_text(row['error_phase'] or '')}</td>"
        f"<td>{_text(error)}</td>"
        "</tr>"
    )


def _render_run_log_event_row(row: dict) -> str:
    error = row["error"] or ""
    if row["error_phase"] or row["error_type"]:
        error = ": ".join(
            part
            for part in (row["error_phase"], row["error_type"], row["error"])
            if part
        )
    return (
        "<tr>"
        f"<td>{_text(row['finished_at'])}</td>"
        f"<td>{_text(row['command'])}</td>"
        f"<td>{_text(row['status'])}</td>"
        f"<td>{_text(row['account'])}</td>"
        f"<td>{_text(row['provider'])}</td>"
        f"<td>{_number_or_none(row['limit'])}</td>"
        f"<td>{_number_or_none(row['new_count'])}</td>"
        f"<td>{_number_or_none(row['notified_count'])}</td>"
        f"<td>{_text(error)}</td>"
        "</tr>"
    )


def _render_audit_event_row(row: dict) -> str:
    metadata = json.dumps(row["metadata"], ensure_ascii=False, sort_keys=True)
    return (
        "<tr>"
        f"<td>{_text(row['created_at'])}</td>"
        f"<td>{_text(row['action'])}</td>"
        f"<td>{_text(row['status'])}</td>"
        f"<td>{_text(row['account'] or '')}</td>"
        f"<td>{_text(row['message_uid'] or '')}</td>"
        f"<td>{_text(row['reason'])}</td>"
        f"<td>{_text(metadata)}</td>"
        "</tr>"
    )


def _render_run_log_filter_form(filters: dict) -> str:
    return (
        '<form class="filters" method="get" action="/">'
        '<label>Command'
        f'<input name="command" value="{_attr(filters["command"] or "")}">'
        "</label>"
        '<label>Status'
        f'<input name="status" value="{_attr(filters["status"] or "")}">'
        "</label>"
        '<label>Finished From'
        f'<input type="date" name="finished_from" value="{_attr(filters["finished_from"] or "")}">'
        "</label>"
        '<label>Finished To'
        f'<input type="date" name="finished_to" value="{_attr(filters["finished_to"] or "")}">'
        "</label>"
        '<button type="submit">Filter Runs</button>'
        "</form>"
    )


def _render_audit_filter_form(filters: dict, stats_filters: dict) -> str:
    return (
        '<form class="filters" method="get" action="/audit">'
        f'{_hidden_input("date_from", stats_filters["date_from"])}'
        f'{_hidden_input("date_to", stats_filters["date_to"])}'
        f'{_hidden_input("sender_limit", stats_filters["sender_limit"])}'
        '<label>Action'
        f'<input name="action" value="{_attr(filters["action"] or "")}">'
        "</label>"
        '<label>Status'
        f'<input name="status" value="{_attr(filters["status"] or "")}">'
        "</label>"
        '<label>Account'
        f'<input name="account" value="{_attr(filters["account"] or "")}">'
        "</label>"
        '<button type="submit">Filter Audit</button>'
        "</form>"
    )


def _render_stats_filter_form(filters: dict, audit_filters: dict) -> str:
    return (
        '<form class="filters" method="get" action="/audit">'
        f'{_hidden_input("action", audit_filters["action"])}'
        f'{_hidden_input("status", audit_filters["status"])}'
        f'{_hidden_input("account", audit_filters["account"])}'
        '<label>Date From'
        f'<input type="date" name="date_from" value="{_attr(filters["date_from"] or "")}">'
        "</label>"
        '<label>Date To'
        f'<input type="date" name="date_to" value="{_attr(filters["date_to"] or "")}">'
        "</label>"
        '<label>Sender Limit'
        f'<input type="number" min="1" name="sender_limit" value="{_attr(filters["sender_limit"])}">'
        "</label>"
        '<button type="submit">Filter Stats</button>'
        "</form>"
    )


def _hidden_input(name: str, value) -> str:
    if value is None:
        return f'<input type="hidden" data-preserve-name="{_attr(name)}" value="">'
    return (
        f'<input type="hidden" name="{_attr(name)}" value="{_attr(value)}"'
        f' data-preserve-name="{_attr(name)}">'
    )


def _run_summary_cells(row: dict | None) -> dict:
    if row is None:
        none = '<span class="muted">none</span>'
        return {
            "error": none,
            "existing_count": none,
            "finished_at": none,
            "new_count": none,
            "notified_count": none,
            "status": none,
        }
    return {
        "error": _text(row["error"] or ""),
        "existing_count": _number_or_none(row["existing_count"]),
        "finished_at": _text(row["finished_at"]),
        "new_count": _number_or_none(row["new_count"]),
        "notified_count": _number_or_none(row["notified_count"]),
        "status": _text(row["status"]),
    }


def _metric(label: str, value: str) -> str:
    return (
        '<div class="metric">'
        f'<div class="label">{escape(label)}</div>'
        f'<div class="value">{value}</div>'
        "</div>"
    )


def _db_error(db_info: dict) -> str:
    if not db_info["error"]:
        return ""
    return (
        '<p class="error">'
        f'{_text(db_info["error_type"])}: {_text(db_info["error"])}'
        "</p>"
    )


def _payload_error(payload: dict) -> str:
    if not payload["error"]:
        return ""
    return (
        '<p class="error">'
        f'{_text(payload["error_type"])}: {_text(payload["error"])}'
        "</p>"
    )


def _yes_no(value: bool) -> str:
    return "yes" if value else "no"


def _number_or_none(value) -> str:
    if value is None:
        return '<span class="muted">none</span>'
    return escape(str(value))


def _text(value) -> str:
    return escape(str(value))


def _attr(value) -> str:
    return escape(str(value), quote=True)
