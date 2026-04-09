from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS users(
  id INTEGER PRIMARY KEY,
  email TEXT UNIQUE NOT NULL,
  is_demo BOOLEAN DEFAULT 0,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS gmail_accounts(
  id INTEGER PRIMARY KEY,
  user_id INTEGER NOT NULL UNIQUE REFERENCES users(id),
  google_user_id TEXT UNIQUE,
  email TEXT NOT NULL,
  refresh_token_encrypted TEXT,
  last_scan_at TIMESTAMP,
  scan_in_progress BOOLEAN DEFAULT 0,
  last_scan_error TEXT NULL,
  last_scan_status TEXT NULL,
  status TEXT DEFAULT 'connected_active',
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS receipts(
  id INTEGER PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id),
  gmail_account_id INTEGER REFERENCES gmail_accounts(id),
  gmail_message_id TEXT,
  gmail_attachment_id TEXT,
  file_sha256 TEXT NOT NULL,
  vendor TEXT,
  receipt_date DATE,
  amount_cents INTEGER,
  storage_path TEXT NOT NULL,
  confidence_score INTEGER NOT NULL,
  high_confidence BOOLEAN DEFAULT 1,
  source TEXT NOT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(user_id, file_sha256),
  UNIQUE(gmail_account_id, gmail_message_id, gmail_attachment_id)
);

CREATE TABLE IF NOT EXISTS sessions(
  id INTEGER PRIMARY KEY,
  session_id TEXT UNIQUE NOT NULL,
  user_id INTEGER NOT NULL REFERENCES users(id),
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  expires_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS settings(
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_receipts_user_date
ON receipts(user_id, receipt_date);

CREATE INDEX IF NOT EXISTS idx_receipts_user_vendor
ON receipts(user_id, vendor);
"""


def connect_database(database_path: Path) -> sqlite3.Connection:
    database_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(database_path))
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")

    journal_mode = get_journal_mode(connection, desired_mode="WAL")
    if journal_mode.lower() != "wal":
        raise RuntimeError(f"SQLite journal mode is {journal_mode}, expected WAL")

    connection.execute("PRAGMA busy_timeout = 5000")
    return connection


def get_journal_mode(connection: sqlite3.Connection, desired_mode: str | None = None) -> str:
    pragma = "PRAGMA journal_mode"
    if desired_mode:
        pragma = f"{pragma}={desired_mode}"
    result = connection.execute(pragma).fetchone()
    if result is None:
        raise RuntimeError("SQLite did not return a journal mode")
    return str(result[0])


def initialize_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(SCHEMA_SQL)
    connection.commit()
