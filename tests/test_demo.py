from __future__ import annotations

import sqlite3
import zipfile

from provable.demo_seed import seed_demo_data


def test_demo_seed_is_idempotent_and_exports_exist(settings, app):
    seed_demo_data(settings)
    seed_demo_data(settings)

    first_export = settings.demo_exports_root / "2024-01.zip"
    second_export = settings.demo_exports_root / "2024-02.zip"

    assert first_export.exists()
    assert second_export.exists()

    with zipfile.ZipFile(first_export) as archive:
        names = sorted(archive.namelist())
        assert names == [
            "2024-01/acme-office/receipt-acme-office-2024-01-15.pdf",
            "2024-01/metro-fuel/receipt-metro-fuel-2024-01-28.pdf",
        ]

    with sqlite3.connect(settings.database_path) as connection:
        user_count = connection.execute(
            "SELECT COUNT(*) FROM users WHERE is_demo = 1"
        ).fetchone()[0]
        receipt_count = connection.execute("SELECT COUNT(*) FROM receipts").fetchone()[0]

    assert user_count == 1
    assert receipt_count == 3


def test_demo_session_and_receipt_listing(client):
    response = client.post("/demo")

    assert response.status_code == 200
    set_cookie = response.headers["Set-Cookie"]
    assert "HttpOnly" in set_cookie
    assert "SameSite=Lax" in set_cookie

    receipts_response = client.get("/receipts")
    payload = receipts_response.get_json()

    assert receipts_response.status_code == 200
    assert payload["months"] == ["2024-02", "2024-01"]
    assert len(payload["byMonth"]["2024-01"]) == 2
    assert payload["byMonth"]["2024-02"][0]["vendor"] == "Bright Cable"
    assert payload["byMonth"]["2024-02"][0]["source"] == "demo_seed"


def test_demo_export_validates_month_and_serves_prebuilt_zip(client):
    client.post("/demo")

    ok_response = client.get("/export/2024-01")
    assert ok_response.status_code == 200
    assert ok_response.mimetype == "application/zip"

    invalid_response = client.get("/export/2024-13")
    assert invalid_response.status_code == 400
    assert invalid_response.get_json()["error"] == "invalid_month"

    traversal_response = client.get("/export/..2024-01")
    assert traversal_response.status_code == 400
    assert traversal_response.get_json()["error"] == "invalid_month"


def test_demo_reset_clears_only_session_data(client, settings):
    client.post("/demo")

    with sqlite3.connect(settings.database_path) as connection:
        session_count_before = connection.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
        receipt_count_before = connection.execute("SELECT COUNT(*) FROM receipts").fetchone()[0]

    export_path = settings.demo_exports_root / "2024-01.zip"
    assert export_path.exists()

    reset_response = client.post("/demo/reset")
    assert reset_response.status_code == 200

    with sqlite3.connect(settings.database_path) as connection:
        session_count_after = connection.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
        receipt_count_after = connection.execute("SELECT COUNT(*) FROM receipts").fetchone()[0]

    assert session_count_before == 1
    assert session_count_after == 0
    assert receipt_count_after == receipt_count_before
    assert export_path.exists()

    unauthorized_response = client.get("/receipts")
    assert unauthorized_response.status_code == 401
