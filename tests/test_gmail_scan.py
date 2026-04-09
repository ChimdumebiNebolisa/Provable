from __future__ import annotations

import base64
import sqlite3
from dataclasses import dataclass, field
from time import sleep
from urllib.parse import parse_qs, urlparse

from provable.gmail import GmailAttachmentPayload
from provable.gmail_scan import GmailScanExecutor
from provable.oauth import GoogleIdentity, OAuthTokens
from provable.scan import ScanManager


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("utf-8").rstrip("=")


@dataclass
class FakeOAuthClient:
    refreshed_tokens: list[str] = field(default_factory=list)

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
            google_user_id="gmail-user-123",
            email="receipts@example.com",
        )

    def refresh_access_token(self, refresh_token: str) -> str:
        self.refreshed_tokens.append(refresh_token)
        return "refreshed-access-token"


@dataclass
class FakeGmailClient:
    queried_after_dates: list[str] = field(default_factory=list)

    def list_messages(self, *, access_token: str, after_date) -> list[str]:
        self.queried_after_dates.append(after_date.isoformat())
        return ["message-1", "message-2", "message-3"]

    def get_message(self, *, access_token: str, message_id: str) -> dict:
        messages = {
            "message-1": {
                "id": "message-1",
                "internalDate": "1706745600000",
                "payload": {
                    "headers": [
                        {"name": "Subject", "value": "Your receipt is ready"},
                        {"name": "From", "value": "Example Store <billing@example-store.com>"},
                    ],
                    "parts": [
                        {
                            "filename": "receipt-february.pdf",
                            "mimeType": "application/pdf",
                            "body": {"attachmentId": "attachment-1"},
                        }
                    ],
                },
            },
            "message-2": {
                "id": "message-2",
                "internalDate": "1706745600000",
                "payload": {
                    "headers": [
                        {"name": "Subject", "value": "Your receipt image"},
                        {"name": "From", "value": "Camera Mart <sales@camera-mart.com>"},
                    ],
                    "parts": [
                        {
                            "filename": "receipt-image.jpg",
                            "mimeType": "image/jpeg",
                            "body": {"attachmentId": "attachment-2"},
                        }
                    ],
                },
            },
            "message-3": {
                "id": "message-3",
                "internalDate": "1706745600000",
                "payload": {
                    "headers": [
                        {"name": "Subject", "value": "Monthly statement"},
                        {"name": "From", "value": "News Corp <updates@news-corp.com>"},
                    ],
                    "parts": [
                        {
                            "filename": "statement.pdf",
                            "mimeType": "application/pdf",
                            "body": {"attachmentId": "attachment-3"},
                        }
                    ],
                },
            },
        }
        return messages[message_id]

    def get_attachment(
        self,
        *,
        access_token: str,
        message_id: str,
        attachment_id: str,
        filename: str,
        mime_type: str,
    ) -> GmailAttachmentPayload:
        payloads = {
            "attachment-1": b"%PDF-high-confidence%",
            "attachment-2": b"\xff\xd8review-queue-image\xff\xd9",
            "attachment-3": b"%PDF-low-score%",
        }
        return GmailAttachmentPayload(
            attachment_id=attachment_id,
            filename=filename,
            mime_type=mime_type,
            data=payloads[attachment_id],
        )


def _connect_real_user(client):
    login_response = client.get("/auth/login")
    state = parse_qs(urlparse(login_response.headers["Location"]).query)["state"][0]
    callback_response = client.get(f"/auth/callback?state={state}&code=gmail-code")
    assert callback_response.status_code == 302


def _wait_for_scan_completion(client):
    for _ in range(40):
        status = client.get("/scan/status")
        if status.status_code == 200 and status.get_json()["scan_in_progress"] is False:
            return status.get_json()
        sleep(0.05)
    raise AssertionError("scan did not complete")


def test_scan_fetches_fixed_window_and_uses_internal_date_for_receipts(app, client, settings):
    fake_oauth = FakeOAuthClient()
    fake_gmail = FakeGmailClient()
    app.config["PROVABLE_OAUTH_CLIENT"] = fake_oauth
    app.config["PROVABLE_SCAN_MANAGER"] = ScanManager(
        settings=settings,
        executor=GmailScanExecutor(
            settings=settings,
            oauth_client=fake_oauth,
            gmail_client=fake_gmail,
        ),
    )

    _connect_real_user(client)
    _wait_for_scan_completion(client)

    with sqlite3.connect(settings.database_path) as connection:
        receipts = connection.execute(
            """
            SELECT
              gmail_message_id,
              gmail_attachment_id,
              receipt_date,
              confidence_score,
              high_confidence,
              source
            FROM receipts
            WHERE source = 'gmail_scan'
            ORDER BY gmail_message_id
            """
        ).fetchall()

    assert fake_oauth.refreshed_tokens == ["refresh-gmail-code"]
    assert len(fake_gmail.queried_after_dates) == 1
    assert receipts[0][0] == "message-1"
    assert receipts[0][2] == "2024-02-01"
    assert receipts[0][3] == 4
    assert receipts[0][4] == 1
    assert receipts[1][0] == "message-2"
    assert receipts[1][3] == 4
    assert receipts[1][4] == 1


def test_scan_deduplicates_by_sha_and_skips_low_score(app, client, settings):
    fake_oauth = FakeOAuthClient()
    fake_gmail = FakeGmailClient()
    app.config["PROVABLE_OAUTH_CLIENT"] = fake_oauth
    app.config["PROVABLE_SCAN_MANAGER"] = ScanManager(
        settings=settings,
        executor=GmailScanExecutor(
            settings=settings,
            oauth_client=fake_oauth,
            gmail_client=fake_gmail,
        ),
    )

    _connect_real_user(client)
    _wait_for_scan_completion(client)

    second_scan = client.post("/scan")
    assert second_scan.status_code == 202
    _wait_for_scan_completion(client)

    with sqlite3.connect(settings.database_path) as connection:
        gmail_receipt_count = connection.execute(
            "SELECT COUNT(*) FROM receipts WHERE source = 'gmail_scan'"
        ).fetchone()[0]
        listed_receipts = client.get("/receipts").get_json()["byMonth"]

    assert gmail_receipt_count == 2
    assert list(listed_receipts.keys()) == ["2024-02"]
    assert len(listed_receipts["2024-02"]) == 2


@dataclass
class DuplicateShaGmailClient(FakeGmailClient):
    def list_messages(self, *, access_token: str, after_date) -> list[str]:
        self.queried_after_dates.append(after_date.isoformat())
        return ["message-1", "message-4"]

    def get_message(self, *, access_token: str, message_id: str) -> dict:
        if message_id == "message-4":
            return {
                "id": "message-4",
                "internalDate": "1706745600000",
                "payload": {
                    "headers": [
                        {"name": "Subject", "value": "Receipt copy"},
                        {"name": "From", "value": "Example Store <billing@example-store.com>"},
                    ],
                    "parts": [
                        {
                            "filename": "receipt-copy.pdf",
                            "mimeType": "application/pdf",
                            "body": {"attachmentId": "attachment-4"},
                        }
                    ],
                },
            }
        return super().get_message(access_token=access_token, message_id=message_id)

    def get_attachment(
        self,
        *,
        access_token: str,
        message_id: str,
        attachment_id: str,
        filename: str,
        mime_type: str,
    ) -> GmailAttachmentPayload:
        if attachment_id == "attachment-4":
            return GmailAttachmentPayload(
                attachment_id=attachment_id,
                filename=filename,
                mime_type=mime_type,
                data=b"%PDF-high-confidence%",
            )
        return super().get_attachment(
            access_token=access_token,
            message_id=message_id,
            attachment_id=attachment_id,
            filename=filename,
            mime_type=mime_type,
        )


def test_scan_skips_distinct_gmail_ids_when_file_sha_matches(app, client, settings):
    fake_oauth = FakeOAuthClient()
    fake_gmail = DuplicateShaGmailClient()
    app.config["PROVABLE_OAUTH_CLIENT"] = fake_oauth
    app.config["PROVABLE_SCAN_MANAGER"] = ScanManager(
        settings=settings,
        executor=GmailScanExecutor(
            settings=settings,
            oauth_client=fake_oauth,
            gmail_client=fake_gmail,
        ),
    )

    _connect_real_user(client)
    _wait_for_scan_completion(client)

    with sqlite3.connect(settings.database_path) as connection:
        gmail_receipts = connection.execute(
            """
            SELECT gmail_message_id, file_sha256
            FROM receipts
            WHERE source = 'gmail_scan'
            ORDER BY gmail_message_id
            """
        ).fetchall()

    assert len(gmail_receipts) == 1
    assert gmail_receipts[0][0] == "message-1"
