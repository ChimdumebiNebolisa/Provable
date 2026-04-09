from __future__ import annotations

import hashlib
import json
import zipfile
from dataclasses import dataclass
from pathlib import Path

from .config import Settings
from .db import connect_database, initialize_schema
from .storage import ensure_storage_paths

DEMO_USER_EMAIL = "demo@provable.local"

DEMO_RECEIPTS = (
    {
        "month": "2024-01",
        "vendor": "Acme Office",
        "filename": "receipt-acme-office-2024-01-15.pdf",
        "receipt_date": "2024-01-15",
        "amount_cents": 1299,
        "confidence_score": 5,
        "high_confidence": True,
    },
    {
        "month": "2024-01",
        "vendor": "Metro Fuel",
        "filename": "receipt-metro-fuel-2024-01-28.pdf",
        "receipt_date": "2024-01-28",
        "amount_cents": 4521,
        "confidence_score": 4,
        "high_confidence": True,
    },
    {
        "month": "2024-02",
        "vendor": "Bright Cable",
        "filename": "invoice-bright-cable-2024-02-05.pdf",
        "receipt_date": "2024-02-05",
        "amount_cents": 8999,
        "confidence_score": 5,
        "high_confidence": True,
    },
)


@dataclass(frozen=True, slots=True)
class DemoSeedResult:
    user_id: int
    receipt_count: int
    export_count: int

    def to_dict(self) -> dict[str, int]:
        return {
            "user_id": self.user_id,
            "receipt_count": self.receipt_count,
            "export_count": self.export_count,
        }


def seed_demo_data(settings: Settings) -> DemoSeedResult:
    ensure_storage_paths(settings)

    with connect_database(settings.database_path) as connection:
        initialize_schema(connection)
        connection.execute(
            """
            INSERT INTO users(email, is_demo)
            VALUES(?, 1)
            ON CONFLICT(email) DO UPDATE SET is_demo = excluded.is_demo
            """,
            (DEMO_USER_EMAIL,),
        )
        demo_user_id = int(
            connection.execute(
                "SELECT id FROM users WHERE email = ?",
                (DEMO_USER_EMAIL,),
            ).fetchone()[0]
        )

        for receipt in DEMO_RECEIPTS:
            vendor_dir = settings.demo_storage_root / receipt["month"] / _slugify(receipt["vendor"])
            vendor_dir.mkdir(parents=True, exist_ok=True)
            pdf_path = vendor_dir / receipt["filename"]
            pdf_bytes = _build_demo_pdf_bytes(
                vendor=receipt["vendor"],
                receipt_date=receipt["receipt_date"],
                amount_cents=int(receipt["amount_cents"]),
                filename=receipt["filename"],
            )
            pdf_path.write_bytes(pdf_bytes)
            file_sha256 = hashlib.sha256(pdf_bytes).hexdigest()

            connection.execute(
                """
                INSERT INTO receipts(
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
                VALUES(?, NULL, NULL, NULL, ?, ?, ?, ?, ?, ?, ?, 'demo_seed')
                ON CONFLICT(user_id, file_sha256) DO UPDATE SET
                  vendor = excluded.vendor,
                  receipt_date = excluded.receipt_date,
                  amount_cents = excluded.amount_cents,
                  storage_path = excluded.storage_path,
                  confidence_score = excluded.confidence_score,
                  high_confidence = excluded.high_confidence,
                  source = excluded.source
                """,
                (
                    demo_user_id,
                    file_sha256,
                    receipt["vendor"],
                    receipt["receipt_date"],
                    receipt["amount_cents"],
                    str(pdf_path),
                    receipt["confidence_score"],
                    int(receipt["high_confidence"]),
                ),
            )

        connection.commit()

    created_exports = _build_demo_exports(settings)
    return DemoSeedResult(
        user_id=demo_user_id,
        receipt_count=len(DEMO_RECEIPTS),
        export_count=created_exports,
    )


def _build_demo_exports(settings: Settings) -> int:
    exports_created = 0
    receipts_by_month: dict[str, list[Path]] = {}
    for receipt in DEMO_RECEIPTS:
        pdf_path = (
            settings.demo_storage_root
            / receipt["month"]
            / _slugify(receipt["vendor"])
            / receipt["filename"]
        )
        receipts_by_month.setdefault(receipt["month"], []).append(pdf_path)

    for month, files in receipts_by_month.items():
        export_path = settings.demo_exports_root / f"{month}.zip"
        with zipfile.ZipFile(export_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for pdf_path in files:
                archive.write(pdf_path, arcname=pdf_path.relative_to(settings.demo_storage_root))
        exports_created += 1

    return exports_created


def _build_demo_pdf_bytes(
    *,
    vendor: str,
    receipt_date: str,
    amount_cents: int,
    filename: str,
) -> bytes:
    amount = f"{amount_cents / 100:.2f}"
    content = (
        "%PDF-1.4\n"
        "1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n"
        "2 0 obj << /Type /Pages /Count 1 /Kids [3 0 R] >> endobj\n"
        "3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 300 144] "
        "/Contents 4 0 R /Resources << >> >> endobj\n"
        f"4 0 obj << /Length 91 >> stream\nBT /F1 12 Tf 24 108 Td ({vendor}) Tj 0 -18 Td "
        f"({receipt_date}) Tj 0 -18 Td (${amount}) Tj 0 -18 Td ({filename}) Tj ET\n"
        "endstream endobj\n"
        "xref\n0 5\n0000000000 65535 f \n0000000010 00000 n \n0000000063 00000 n \n"
        "0000000122 00000 n \n0000000218 00000 n \n"
        "trailer << /Root 1 0 R /Size 5 >>\nstartxref\n379\n%%EOF\n"
    )
    return content.encode("utf-8")


def _slugify(value: str) -> str:
    cleaned = "".join(ch.lower() if ch.isalnum() else "-" for ch in value)
    return "-".join(part for part in cleaned.split("-") if part)


if __name__ == "__main__":
    print(json.dumps(seed_demo_data(Settings.from_env()).to_dict(), indent=2))
