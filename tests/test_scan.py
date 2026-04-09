from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from threading import Event
from time import sleep
from urllib.parse import parse_qs, urlparse

from provable.oauth import GoogleIdentity, OAuthTokens
from provable.scan import ScanExecutionResult, ScanManager


@dataclass
class FakeOAuthClient:
    def build_authorization_url(self, state: str) -> str:
        return f"https://accounts.google.com/o/oauth2/v2/auth?state={state}"

    def exchange_code(self, code: str) -> OAuthTokens:
        return OAuthTokens(
            access_token=f"access-{code}",
            refresh_token=f"refresh-{code}",
            token_type="Bearer",
            scope="openid email https://www.googleapis.com/auth/gmail.readonly",
        )

    def fetch_identity(self, access_token: str) -> GoogleIdentity:
        return GoogleIdentity(
            google_user_id="scan-google-user",
            email="scanner@example.com",
        )


@dataclass
class BlockingExecutor:
    started: Event = field(default_factory=Event)
    release: Event = field(default_factory=Event)
    call_count: int = 0

    def run(self, *, settings, user_id: int, gmail_account_id: int) -> ScanExecutionResult:
        self.call_count += 1
        self.started.set()
        self.release.wait(timeout=5)
        return ScanExecutionResult(scanned_at=datetime.now(UTC), status="ok")


@dataclass
class ImmediateExecutor:
    call_count: int = 0

    def run(self, *, settings, user_id: int, gmail_account_id: int) -> ScanExecutionResult:
        self.call_count += 1
        return ScanExecutionResult(scanned_at=datetime.now(UTC), status="ok")


def _connect_real_user(client):
    login_response = client.get("/auth/login")
    state = parse_qs(urlparse(login_response.headers["Location"]).query)["state"][0]
    callback_response = client.get(f"/auth/callback?state={state}&code=scan-code")
    assert callback_response.status_code == 302


def test_manual_scan_is_session_protected(client):
    response = client.post("/scan")

    assert response.status_code == 401
    assert response.get_json()["error"] == "unauthenticated"


def test_manual_scan_rejects_overlap_and_reports_status(app, client, settings):
    executor = BlockingExecutor()
    app.config["PROVABLE_OAUTH_CLIENT"] = FakeOAuthClient()
    app.config["PROVABLE_SCAN_MANAGER"] = ScanManager(settings=settings, executor=executor)

    _connect_real_user(client)
    assert executor.started.wait(timeout=3)

    second_scan = client.post("/scan")
    assert second_scan.status_code == 409
    assert second_scan.get_json()["error"] == "scan_in_progress"

    status_while_running = client.get("/scan/status")
    assert status_while_running.status_code == 200
    assert status_while_running.get_json()["scan_in_progress"] is True
    assert status_while_running.get_json()["last_scan_status"] == "running"

    executor.release.set()

    for _ in range(20):
        status_after = client.get("/scan/status")
        if status_after.get_json()["scan_in_progress"] is False:
            break
        sleep(0.05)

    assert status_after.get_json()["scan_in_progress"] is False
    assert status_after.get_json()["last_scan_status"] == "ok"
    assert executor.call_count == 1


def test_auto_scan_runs_on_open_when_stale(app, client, settings):
    executor = ImmediateExecutor()
    app.config["PROVABLE_OAUTH_CLIENT"] = FakeOAuthClient()
    app.config["PROVABLE_SCAN_MANAGER"] = ScanManager(settings=settings, executor=executor)

    _connect_real_user(client)
    for _ in range(20):
        status = client.get("/scan/status")
        if status.status_code == 200 and status.get_json()["scan_in_progress"] is False:
            break
        sleep(0.05)

    with sqlite3.connect(settings.database_path) as connection:
        connection.execute(
            """
            UPDATE gmail_accounts
            SET last_scan_at = ?, scan_in_progress = 0, last_scan_status = 'ok'
            WHERE email = ?
            """,
            (
                (datetime.now(UTC) - timedelta(hours=settings.stale_threshold_hours + 1)).isoformat(),
                "scanner@example.com",
            ),
        )
        connection.commit()

    before_calls = executor.call_count
    receipts_response = client.get("/receipts")
    for _ in range(20):
        if executor.call_count >= before_calls + 1:
            break
        sleep(0.05)

    assert receipts_response.status_code == 200
    assert executor.call_count >= before_calls + 1


def test_manual_scan_requires_real_connected_account(app, client):
    response = client.post("/demo")
    assert response.status_code == 200

    scan_response = client.post("/scan")
    assert scan_response.status_code == 400
    assert scan_response.get_json()["error"] == "gmail_account_required"
