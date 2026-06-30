PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    mode TEXT NOT NULL DEFAULT 'read_only',
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider TEXT NOT NULL,
    account TEXT NOT NULL,
    message_uid TEXT NOT NULL,
    message_id TEXT,
    thread_id TEXT,
    sender TEXT NOT NULL,
    recipients_json TEXT NOT NULL,
    subject TEXT NOT NULL,
    message_date TEXT,
    text TEXT NOT NULL,
    html TEXT NOT NULL,
    headers_json TEXT NOT NULL,
    attachments_json TEXT NOT NULL,
    links_json TEXT NOT NULL,
    folder TEXT NOT NULL DEFAULT 'INBOX',
    created_at TEXT NOT NULL,
    UNIQUE(provider, account, message_uid)
);

CREATE TABLE IF NOT EXISTS message_classifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_row_id INTEGER NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    importance TEXT NOT NULL,
    action TEXT NOT NULL,
    risk TEXT NOT NULL,
    message_type TEXT NOT NULL,
    reason TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS telegram_notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_row_id INTEGER NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    account TEXT NOT NULL,
    chat_id TEXT NOT NULL,
    status TEXT NOT NULL,
    sent_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(message_row_id, chat_id)
);

CREATE TABLE IF NOT EXISTS run_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    command TEXT NOT NULL,
    status TEXT NOT NULL,
    account TEXT NOT NULL,
    provider TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT NOT NULL,
    limit_value INTEGER,
    new_count INTEGER NOT NULL DEFAULT 0,
    existing_count INTEGER NOT NULL DEFAULT 0,
    notified_count INTEGER NOT NULL DEFAULT 0,
    error_phase TEXT,
    error_type TEXT,
    error TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS drafts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_row_id INTEGER NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    account TEXT NOT NULL,
    subject TEXT NOT NULL,
    body TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'local_draft_only',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS recommendations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account TEXT NOT NULL,
    provider TEXT NOT NULL,
    action TEXT NOT NULL,
    target TEXT NOT NULL,
    reason TEXT NOT NULL,
    requires_confirmation INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL DEFAULT 'recommended',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS approval_actions (
    id TEXT PRIMARY KEY,
    account TEXT NOT NULL,
    provider TEXT NOT NULL,
    action_type TEXT NOT NULL,
    target TEXT NOT NULL,
    reason TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    approved_at TEXT,
    executed_at TEXT
);

CREATE TABLE IF NOT EXISTS unsubscribe_candidates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_row_id INTEGER REFERENCES messages(id) ON DELETE SET NULL,
    account TEXT NOT NULL,
    sender TEXT NOT NULL,
    list_unsubscribe TEXT,
    reason TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'detected',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS spam_signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_row_id INTEGER REFERENCES messages(id) ON DELETE CASCADE,
    signal TEXT NOT NULL,
    severity TEXT NOT NULL,
    reason TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account TEXT,
    message_uid TEXT,
    action TEXT NOT NULL,
    status TEXT NOT NULL,
    reason TEXT NOT NULL,
    metadata_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
