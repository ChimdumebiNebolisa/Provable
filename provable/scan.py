from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from threading import Thread

from .config import Settings
from .db import connect_database


@dataclass(frozen=True, slots=True)
class ScanExecutionResult:
    scanned_at: datetime
    status: str = "ok"
    error: str | None = None


@dataclass(frozen=True, slots=True)
class ScanStatusRecord:
    gmail_account_id: int
    scan_in_progress: bool
    last_scan_at: str | None
    last_scan_status: str | None
    last_scan_error: str | None


class NoOpScanExecutor:
    def run(
        self,
        *,
        settings: Settings,
        user_id: int,
        gmail_account_id: int,
    ) -> ScanExecutionResult:
        return ScanExecutionResult(scanned_at=datetime.now(UTC), status="ok")


class ScanManager:
    def __init__(self, *, settings: Settings, executor):
        self._settings = settings
        self._executor = executor

    def start_scan(self, *, user_id: int, trigger: str, only_if_stale: bool) -> str:
        with connect_database(self._settings.database_path) as connection:
            account = self._get_scan_status(connection, user_id)
            if account is None:
                return "missing_account"
            if account.scan_in_progress:
                return "already_running"
            if only_if_stale and not self._is_stale(account.last_scan_at):
                return "not_stale"

            updated = connection.execute(
                """
                UPDATE gmail_accounts
                SET
                  scan_in_progress = 1,
                  last_scan_status = 'running',
                  last_scan_error = NULL
                WHERE user_id = ? AND scan_in_progress = 0
                """,
                (user_id,),
            )
            connection.commit()
            if updated.rowcount != 1:
                return "already_running"
            gmail_account_id = account.gmail_account_id

        thread = Thread(
            target=self._run_scan,
            kwargs={
                "user_id": user_id,
                "gmail_account_id": gmail_account_id,
                "trigger": trigger,
            },
            daemon=True,
        )
        thread.start()
        return "started"

    def get_status(self, *, user_id: int) -> ScanStatusRecord | None:
        with connect_database(self._settings.database_path) as connection:
            return self._get_scan_status(connection, user_id)

    def _run_scan(self, *, user_id: int, gmail_account_id: int, trigger: str) -> None:
        try:
            result = self._executor.run(
                settings=self._settings,
                user_id=user_id,
                gmail_account_id=gmail_account_id,
            )
        except Exception as exc:
            with connect_database(self._settings.database_path) as connection:
                connection.execute(
                    """
                    UPDATE gmail_accounts
                    SET
                      scan_in_progress = 0,
                      last_scan_status = 'error',
                      last_scan_error = ?
                    WHERE user_id = ?
                    """,
                    (str(exc), user_id),
                )
                connection.commit()
            return

        with connect_database(self._settings.database_path) as connection:
            connection.execute(
                """
                UPDATE gmail_accounts
                SET
                  scan_in_progress = 0,
                  last_scan_at = ?,
                  last_scan_status = ?,
                  last_scan_error = ?
                WHERE user_id = ?
                """,
                (
                    result.scanned_at.isoformat(),
                    result.status,
                    result.error,
                    user_id,
                ),
            )
            connection.commit()

    def _get_scan_status(
        self,
        connection: sqlite3.Connection,
        user_id: int,
    ) -> ScanStatusRecord | None:
        row = connection.execute(
            """
            SELECT
              id,
              scan_in_progress,
              last_scan_at,
              last_scan_status,
              last_scan_error
            FROM gmail_accounts
            WHERE user_id = ?
            """,
            (user_id,),
        ).fetchone()
        if row is None:
            return None
        return ScanStatusRecord(
            gmail_account_id=int(row["id"]),
            scan_in_progress=bool(row["scan_in_progress"]),
            last_scan_at=row["last_scan_at"],
            last_scan_status=row["last_scan_status"],
            last_scan_error=row["last_scan_error"],
        )

    def _is_stale(self, last_scan_at: str | None) -> bool:
        if not last_scan_at:
            return True
        last_scan_at_dt = datetime.fromisoformat(last_scan_at)
        if last_scan_at_dt.tzinfo is None:
            last_scan_at_dt = last_scan_at_dt.replace(tzinfo=UTC)
        return last_scan_at_dt <= datetime.now(UTC) - timedelta(hours=self._settings.stale_threshold_hours)
