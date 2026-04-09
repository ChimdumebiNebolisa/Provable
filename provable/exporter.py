from __future__ import annotations

from io import BytesIO
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from .config import Settings
from .db import connect_database


class ExportLimitError(RuntimeError):
    pass


def build_real_user_export(*, settings: Settings, user_id: int, month: str) -> BytesIO | None:
    with connect_database(settings.database_path) as connection:
        rows = connection.execute(
            """
            SELECT vendor, storage_path
            FROM receipts
            WHERE user_id = ? AND substr(receipt_date, 1, 7) = ?
            ORDER BY vendor ASC, receipt_date ASC, id ASC
            """,
            (user_id, month),
        ).fetchall()

    if not rows:
        return None
    if len(rows) > settings.real_export_max_files:
        raise ExportLimitError("export_limit_exceeded_files")

    max_size_bytes = settings.real_export_max_size_mb * 1024 * 1024
    total_size = 0
    archive_buffer = BytesIO()
    with ZipFile(archive_buffer, "w", compression=ZIP_DEFLATED) as archive:
        for row in rows:
            storage_path = Path(str(row["storage_path"]))
            if not storage_path.exists():
                raise FileNotFoundError(str(storage_path))

            file_size = storage_path.stat().st_size
            total_size += file_size
            if total_size > max_size_bytes:
                raise ExportLimitError("export_limit_exceeded_size")

            archive.write(
                storage_path,
                arcname=f"{month}/{_slugify(str(row['vendor']))}/{storage_path.name}",
            )

    archive_buffer.seek(0)
    return archive_buffer


def _slugify(value: str) -> str:
    cleaned = "".join(ch.lower() if ch.isalnum() else "-" for ch in value)
    return "-".join(part for part in cleaned.split("-") if part)
