from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from time import sleep
from urllib.parse import parse_qs, urlparse

from provable.gmail import GmailAttachmentPayload
from provable.gmail_scan import GmailScanExecutor
from provable.oauth import GoogleIdentity, OAuthTokens
from provable.scan import ScanManager


@dataclass
class FakeOAuthClient:
    revoked_tokens: list[str] = field(default_factory=list)

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
            google_user_id="disconnect-user-123",
            email="disconnect@example.com",
        )

    def refresh_access_token(self, refresh_token: str) -> str:
        return "disconnect-access-token"

    def revoke_token(self, refresh_token: str) -> None:
        self.revoked_tokens.append(refresh_token)


@dataclass
class FakeGmailClient:
    def list_messages(self, *, access_token: str, after_date) -> list[str]:
        return ["disconnect-message"]

    def get_message(self, *, access_token: str, message_id: str) -> dict:
        return {
            "id": "disconnect-message",
            "internalDate": "1706745600000",
            "payload": {
                "headers": [
                    {"name": "Subject", "value": "Your receipt is ready"},
                    {"name": "From", "value": "Cleanup Store <cleanup@example.com>"},
                ],
                "parts": [
                    {
                        "filename": "receipt-cleanup.pdf",
                        "mimeType": "application/pdf",
                        "body": {"attachmentId": "disconnect-attachment"},
                    }
                ],
            },
        }

    def get_attachment(
        self,
        *,
        access_token: str,
        message_id: str,
        attachment_id: str,
        filename: str,
        mime_type: str,
    ) -> GmailAttachmentPayload:
        return GmailAttachmentPayload(
            attachment_id=attachment_id,
            filename=filename,
            mime_type=mime_type,
            data=b"%PDF-disconnect%",
        )


def _connect_real_user(client):
    login_response = client.get("/auth/login")
    state = parse_qs(urlparse(login_response.headers["Location"]).query)["state"][0]
    callback_response = client.get(f"/auth/callback?state={state}&code=disconnect-code")
    assert callback_response.status_code == 302


def _wait_for_scan_completion(client):
    for _ in range(40):
        status = client.get("/scan/status")
        if status.status_code == 200 and status.get_json()["scan_in_progress"] is False:
            return
        sleep(0.05)
    raise AssertionError("scan did not complete")


def test_disconnect_deletes_real_user_rows_and_files_and_clears_session(app, client, settings):
    fake_oauth = FakeOAuthClient()
    app.config["PROVABLE_OAUTH_CLIENT"] = fake_oauth
    app.config["PROVABLE_SCAN_MANAGER"] = ScanManager(
        settings=settings,
        executor=GmailScanExecutor(
            settings=settings,
            oauth_client=fake_oauth,
            gmail_client=FakeGmailClient(),
        ),
    )

    _connect_real_user(client)
    _wait_for_scan_completion(client)

    with sqlite3.connect(settings.database_path) as connection:
        user_id = connection.execute(
            "SELECT id FROM users WHERE email = ?",
            ("disconnect@example.com",),
        ).fetchone()[0]
        receipt_path = connection.execute(
            "SELECT storage_path FROM receipts WHERE user_id = ?",
            (user_id,),
        ).fetchone()[0]

    assert settings.user_storage_root.joinpath(str(user_id)).exists()

    response = client.post("/auth/disconnect")
    assert response.status_code == 200
    assert response.get_json()["status"] == "disconnected"

    with sqlite3.connect(settings.database_path) as connection:
        user_count = connection.execute(
            "SELECT COUNT(*) FROM users WHERE email = ?",
            ("disconnect@example.com",),
        ).fetchone()[0]
        gmail_count = connection.execute(
            "SELECT COUNT(*) FROM gmail_accounts WHERE email = ?",
            ("disconnect@example.com",),
        ).fetchone()[0]
        receipt_count = connection.execute(
            "SELECT COUNT(*) FROM receipts WHERE user_id = ?",
            (user_id,),
        ).fetchone()[0]
        session_count = connection.execute(
            "SELECT COUNT(*) FROM sessions WHERE user_id = ?",
            (user_id,),
        ).fetchone()[0]

    assert user_count == 0
    assert gmail_count == 0
    assert receipt_count == 0
    assert session_count == 0
    assert not settings.user_storage_root.joinpath(str(user_id)).exists()
    assert fake_oauth.revoked_tokens == ["refresh-disconnect-code"]

    post_disconnect = client.get("/receipts")
    assert post_disconnect.status_code == 401


def test_disconnect_revoke_failure_is_best_effort(app, client, settings):
    class FailingRevokeOAuthClient(FakeOAuthClient):
        def revoke_token(self, refresh_token: str) -> None:
            raise RuntimeError("revoke failed")

    fake_oauth = FailingRevokeOAuthClient()
    app.config["PROVABLE_OAUTH_CLIENT"] = fake_oauth
    app.config["PROVABLE_SCAN_MANAGER"] = ScanManager(
        settings=settings,
        executor=GmailScanExecutor(
            settings=settings,
            oauth_client=fake_oauth,
            gmail_client=FakeGmailClient(),
        ),
    )

    _connect_real_user(client)
    _wait_for_scan_completion(client)

    response = client.post("/auth/disconnect")
    assert response.status_code == 200
    assert response.get_json()["status"] == "disconnected"
