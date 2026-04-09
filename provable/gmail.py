from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import requests

GMAIL_API_ROOT = "https://gmail.googleapis.com/gmail/v1/users/me"


@dataclass(frozen=True, slots=True)
class GmailAttachmentPayload:
    attachment_id: str
    filename: str
    mime_type: str
    data: bytes


class GmailApiClient:
    def __init__(self, session: requests.Session | None = None):
        self._session = session or requests.Session()

    def list_messages(self, *, access_token: str, after_date: date) -> list[str]:
        message_ids: list[str] = []
        page_token: str | None = None
        query = f"after:{after_date.strftime('%Y/%m/%d')} has:attachment"

        while True:
            params = {
                "q": query,
                "maxResults": 100,
            }
            if page_token:
                params["pageToken"] = page_token
            response = self._session.get(
                f"{GMAIL_API_ROOT}/messages",
                headers={"Authorization": f"Bearer {access_token}"},
                params=params,
                timeout=20,
            )
            response.raise_for_status()
            payload = response.json()
            message_ids.extend(message["id"] for message in payload.get("messages", []))
            page_token = payload.get("nextPageToken")
            if not page_token:
                return message_ids

    def get_message(self, *, access_token: str, message_id: str) -> dict:
        response = self._session.get(
            f"{GMAIL_API_ROOT}/messages/{message_id}",
            headers={"Authorization": f"Bearer {access_token}"},
            params={"format": "full"},
            timeout=20,
        )
        response.raise_for_status()
        return response.json()

    def get_attachment(
        self,
        *,
        access_token: str,
        message_id: str,
        attachment_id: str,
        filename: str,
        mime_type: str,
    ) -> GmailAttachmentPayload:
        response = self._session.get(
            f"{GMAIL_API_ROOT}/messages/{message_id}/attachments/{attachment_id}",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=20,
        )
        response.raise_for_status()
        payload = response.json()
        return GmailAttachmentPayload(
            attachment_id=attachment_id,
            filename=filename,
            mime_type=mime_type,
            data=_decode_base64url(str(payload["data"])),
        )


def _decode_base64url(value: str) -> bytes:
    import base64

    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(f"{value}{padding}")
