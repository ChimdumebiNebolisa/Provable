from __future__ import annotations

import hashlib
import re
import sqlite3
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from email.utils import parseaddr
from pathlib import Path

from .config import Settings
from .crypto import decrypt_refresh_token
from .db import connect_database
from .gmail import GmailApiClient
from .scan import ScanExecutionResult

KNOWN_VENDORS: tuple[str, ...] = ()
NEGATIVE_SUBJECT_TERMS = ("statement", "report", "newsletter", "terms", "policy")


@dataclass(frozen=True, slots=True)
class CandidateReceipt:
    gmail_message_id: str
    gmail_attachment_id: str
    vendor: str
    receipt_date: str
    amount_cents: int | None
    storage_path: Path
    file_sha256: str
    confidence_score: int
    high_confidence: bool
    file_bytes: bytes


class GmailScanExecutor:
    def __init__(self, *, settings: Settings, oauth_client, gmail_client: GmailApiClient):
        self._settings = settings
        self._oauth_client = oauth_client
        self._gmail_client = gmail_client

    def run(
        self,
        *,
        settings: Settings,
        user_id: int,
        gmail_account_id: int,
    ) -> ScanExecutionResult:
        refresh_token = self._load_refresh_token(gmail_account_id)
        access_token = self._oauth_client.refresh_access_token(refresh_token)
        after_date = date.today() - timedelta(days=self._settings.scan_window_days)
        message_ids = self._gmail_client.list_messages(
            access_token=access_token,
            after_date=after_date,
        )

        candidates: list[CandidateReceipt] = []
        for message_id in message_ids:
            message = self._gmail_client.get_message(access_token=access_token, message_id=message_id)
            candidates.extend(
                self._extract_candidates(
                    user_id=user_id,
                    gmail_account_id=gmail_account_id,
                    access_token=access_token,
                    message=message,
                )
            )

        self._persist_candidates(
            user_id=user_id,
            gmail_account_id=gmail_account_id,
            candidates=candidates,
        )
        return ScanExecutionResult(scanned_at=datetime.now(UTC), status="ok")

    def _load_refresh_token(self, gmail_account_id: int) -> str:
        with connect_database(self._settings.database_path) as connection:
            row = connection.execute(
                """
                SELECT refresh_token_encrypted
                FROM gmail_accounts
                WHERE id = ?
                """,
                (gmail_account_id,),
            ).fetchone()
            if row is None or not row["refresh_token_encrypted"]:
                raise RuntimeError("refresh_token_missing")
            return decrypt_refresh_token(str(row["refresh_token_encrypted"]), self._settings.fernet_key)

    def _extract_candidates(
        self,
        *,
        user_id: int,
        gmail_account_id: int,
        access_token: str,
        message: dict,
    ) -> list[CandidateReceipt]:
        payload = message.get("payload", {})
        headers = {header["name"].lower(): header["value"] for header in payload.get("headers", [])}
        subject = str(headers.get("subject", ""))
        sender = str(headers.get("from", ""))
        vendor = _derive_vendor(sender)
        sender_domain = _extract_sender_domain(sender)
        receipt_date = _receipt_date_from_internal_date(str(message["internalDate"]))

        candidates: list[CandidateReceipt] = []
        for part in _walk_parts(payload):
            filename = str(part.get("filename") or "")
            mime_type = str(part.get("mimeType") or "")
            body = part.get("body", {})
            attachment_id = body.get("attachmentId")
            if not attachment_id:
                continue

            score = _score_attachment(
                sender_domain=sender_domain,
                subject=subject,
                filename=filename,
                mime_type=mime_type,
            )
            if score <= 2:
                continue

            attachment = self._gmail_client.get_attachment(
                access_token=access_token,
                message_id=str(message["id"]),
                attachment_id=str(attachment_id),
                filename=filename,
                mime_type=mime_type,
            )
            extension = _resolve_extension(filename=filename, mime_type=mime_type)
            storage_path = (
                self._settings.user_storage_root
                / str(user_id)
                / receipt_date[:7]
                / _slugify(vendor)
                / _build_storage_filename(message_id=str(message["id"]), attachment_id=str(attachment_id), extension=extension)
            )
            candidates.append(
                CandidateReceipt(
                    gmail_message_id=str(message["id"]),
                    gmail_attachment_id=str(attachment_id),
                    vendor=vendor,
                    receipt_date=receipt_date,
                    amount_cents=None,
                    storage_path=storage_path,
                    file_sha256=hashlib.sha256(attachment.data).hexdigest(),
                    confidence_score=score,
                    high_confidence=score >= 4,
                    file_bytes=attachment.data,
                )
            )
        return candidates

    def _persist_candidates(
        self,
        *,
        user_id: int,
        gmail_account_id: int,
        candidates: list[CandidateReceipt],
    ) -> None:
        written_files: list[Path] = []
        seen_file_hashes: set[str] = set()
        connection = connect_database(self._settings.database_path)
        try:
            connection.execute("BEGIN")
            for candidate in candidates:
                if candidate.file_sha256 in seen_file_hashes:
                    continue
                inserted = connection.execute(
                    """
                    INSERT OR IGNORE INTO receipts(
                      user_id,
                      gmail_account_id,
                      gmail_message_id,
                      gmail_attachment_id,
                      file_sha256,
                      vendor,
                      receipt_date,
                      amount_cents,
                      storage_path,
                      confidence_score,
                      high_confidence,
                      source
                    )
                    VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'gmail_scan')
                    """,
                    (
                        user_id,
                        gmail_account_id,
                        candidate.gmail_message_id,
                        candidate.gmail_attachment_id,
                        candidate.file_sha256,
                        candidate.vendor,
                        candidate.receipt_date,
                        candidate.amount_cents,
                        str(candidate.storage_path),
                        candidate.confidence_score,
                        int(candidate.high_confidence),
                    ),
                )
                if inserted.rowcount != 1:
                    continue

                candidate.storage_path.parent.mkdir(parents=True, exist_ok=True)
                candidate.storage_path.write_bytes(candidate.file_bytes)
                written_files.append(candidate.storage_path)
                seen_file_hashes.add(candidate.file_sha256)

            connection.commit()
        except Exception:
            connection.rollback()
            for file_path in written_files:
                if file_path.exists():
                    file_path.unlink()
            raise
        finally:
            connection.close()


def _walk_parts(payload: dict) -> list[dict]:
    parts = payload.get("parts")
    if not parts:
        return [payload]

    collected: list[dict] = []
    for part in parts:
        collected.extend(_walk_parts(part))
    return collected


def _score_attachment(
    *,
    sender_domain: str,
    subject: str,
    filename: str,
    mime_type: str,
) -> int:
    score = 0
    filename_lower = filename.lower()
    subject_lower = subject.lower()

    if sender_domain in KNOWN_VENDORS:
        score += 3
    if "invoice" in filename_lower or "receipt" in filename_lower:
        score += 2
    if "invoice" in subject_lower or "receipt" in subject_lower:
        score += 2
    if any(term in subject_lower for term in NEGATIVE_SUBJECT_TERMS):
        score -= 2
    if not (mime_type == "application/pdf" or mime_type.startswith("image/")):
        score -= 2

    return score


def _extract_sender_domain(sender: str) -> str:
    _, address = parseaddr(sender)
    if "@" not in address:
        return ""
    return address.split("@", 1)[1].lower()


def _derive_vendor(sender: str) -> str:
    display_name, address = parseaddr(sender)
    if display_name:
        return display_name
    domain = address.split("@", 1)[1] if "@" in address else "unknown-vendor"
    return domain.split(".", 1)[0].replace("-", " ").title()


def _receipt_date_from_internal_date(internal_date_ms: str) -> str:
    timestamp = int(internal_date_ms) / 1000
    return datetime.fromtimestamp(timestamp, tz=UTC).date().isoformat()


def _slugify(value: str) -> str:
    cleaned = "".join(ch.lower() if ch.isalnum() else "-" for ch in value)
    return "-".join(part for part in cleaned.split("-") if part)


def _resolve_extension(*, filename: str, mime_type: str) -> str:
    if "." in filename:
        return filename.rsplit(".", 1)[1].lower()
    if mime_type == "application/pdf":
        return "pdf"
    if mime_type.startswith("image/"):
        return mime_type.split("/", 1)[1].lower()
    return "bin"


def _build_storage_filename(*, message_id: str, attachment_id: str, extension: str) -> str:
    safe_extension = re.sub(r"[^a-z0-9]", "", extension.lower()) or "bin"
    return f"{message_id}-{attachment_id}.{safe_extension}"
