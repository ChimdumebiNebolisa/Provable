from __future__ import annotations

import secrets
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta


@dataclass(frozen=True, slots=True)
class SessionRecord:
    session_id: str
    user_id: int
    is_demo: bool
    email: str
    expires_at: datetime


def create_session(
    connection: sqlite3.Connection,
    *,
    user_id: int,
    ttl: timedelta,
) -> SessionRecord:
    session_id = secrets.token_urlsafe(32)
    expires_at = datetime.now(UTC) + ttl
    connection.execute(
        """
        INSERT INTO sessions(session_id, user_id, expires_at)
        VALUES(?, ?, ?)
        """,
        (session_id, user_id, expires_at.isoformat()),
    )
    connection.commit()

    row = connection.execute(
        """
        SELECT
          sessions.session_id,
          sessions.user_id,
          sessions.expires_at,
          users.is_demo,
          users.email
        FROM sessions
        INNER JOIN users ON users.id = sessions.user_id
        WHERE sessions.session_id = ?
        """,
        (session_id,),
    ).fetchone()
    return _session_record_from_row(row)


def get_current_session(
    connection: sqlite3.Connection,
    session_id: str | None,
) -> SessionRecord | None:
    if not session_id:
        return None

    row = connection.execute(
        """
        SELECT
          sessions.session_id,
          sessions.user_id,
          sessions.expires_at,
          users.is_demo,
          users.email
        FROM sessions
        INNER JOIN users ON users.id = sessions.user_id
        WHERE sessions.session_id = ?
        """,
        (session_id,),
    ).fetchone()
    if row is None:
        return None

    session = _session_record_from_row(row)
    if session.expires_at <= datetime.now(UTC):
        delete_session(connection, session_id)
        return None

    return session


def delete_session(connection: sqlite3.Connection, session_id: str) -> None:
    connection.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
    connection.commit()


def _session_record_from_row(row: sqlite3.Row) -> SessionRecord:
    return SessionRecord(
        session_id=str(row["session_id"]),
        user_id=int(row["user_id"]),
        is_demo=bool(row["is_demo"]),
        email=str(row["email"]),
        expires_at=datetime.fromisoformat(str(row["expires_at"])),
    )
