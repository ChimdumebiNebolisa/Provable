from __future__ import annotations

import sqlite3
import zipfile

from provable.deploy import run_deploy_seed


def test_deploy_seed_is_idempotent_and_prebuilds_demo_exports(settings):
    first_result = run_deploy_seed(settings)
    second_result = run_deploy_seed(settings)

    assert first_result.journal_mode.lower() == "wal"
    assert second_result.demo_receipt_count == 3
    assert second_result.demo_export_count == 2

    first_export = settings.demo_exports_root / "2024-01.zip"
    second_export = settings.demo_exports_root / "2024-02.zip"
    assert first_export.exists()
    assert second_export.exists()

    with zipfile.ZipFile(first_export) as archive:
        assert sorted(archive.namelist()) == [
            "2024-01/acme-office/receipt-acme-office-2024-01-15.pdf",
            "2024-01/metro-fuel/receipt-metro-fuel-2024-01-28.pdf",
        ]

    with sqlite3.connect(settings.database_path) as connection:
        demo_user_count = connection.execute(
            "SELECT COUNT(*) FROM users WHERE is_demo = 1"
        ).fetchone()[0]
        demo_receipt_count = connection.execute(
            "SELECT COUNT(*) FROM receipts WHERE source = 'demo_seed'"
        ).fetchone()[0]

    assert demo_user_count == 1
    assert demo_receipt_count == 3
