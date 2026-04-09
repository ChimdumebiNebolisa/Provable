from __future__ import annotations

import sqlite3

from provable.bootstrap import bootstrap_environment
from provable.config import Settings


def build_settings(tmp_path):
    storage_root = tmp_path / "storage"
    return Settings(
        app_env="development",
        secret_key="test-secret",
        storage_root=storage_root,
        database_path=storage_root / "provable.sqlite3",
        demo_storage_root=storage_root / "demo",
        demo_exports_root=storage_root / "demo_exports",
        user_storage_root=storage_root / "users",
    )


def test_bootstrap_creates_required_schema_and_wal_mode(tmp_path):
    settings = build_settings(tmp_path)
    result = bootstrap_environment(settings)

    assert result.journal_mode.lower() == "wal"
    assert settings.database_path.exists()

    with sqlite3.connect(settings.database_path) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        assert {"users", "gmail_accounts", "receipts", "sessions", "settings"} <= tables

        journal_mode = connection.execute("PRAGMA journal_mode").fetchone()[0]
        assert str(journal_mode).lower() == "wal"

        gmail_account_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(gmail_accounts)")
        }
        assert {
            "scan_in_progress",
            "last_scan_at",
            "last_scan_error",
            "last_scan_status",
        } <= gmail_account_columns


def test_bootstrap_is_idempotent_and_creates_writable_storage_paths(tmp_path):
    settings = build_settings(tmp_path)

    bootstrap_environment(settings)
    bootstrap_environment(settings)

    for path in (
        settings.storage_root,
        settings.demo_storage_root,
        settings.demo_exports_root,
        settings.user_storage_root,
    ):
        assert path.is_dir()
        probe = path / "probe.txt"
        probe.write_text("ok", encoding="utf-8")
        assert probe.read_text(encoding="utf-8") == "ok"
        probe.unlink()
