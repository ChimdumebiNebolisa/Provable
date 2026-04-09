from __future__ import annotations

from dataclasses import replace

import pytest
from cryptography.fernet import Fernet

from provable.app import create_app
from provable.config import Settings


def build_settings(tmp_path):
    storage_root = tmp_path / "storage"
    return Settings(
        app_env="development",
        secret_key="test-secret",
        storage_root=storage_root,
        database_path=storage_root / "provable.sqlite3",
        demo_storage_root=storage_root / "demo",
        demo_exports_root=storage_root / "demo_exports",
        user_storage_root=storage_root / "users",
        session_cookie_name="provable_session",
        oauth_state_cookie_name="provable_oauth_state",
        demo_session_ttl_minutes=30,
        real_session_ttl_hours=24,
        stale_threshold_hours=6,
        scan_window_days=60,
        real_export_max_files=500,
        real_export_max_size_mb=100,
        google_client_id="test-google-client-id",
        google_client_secret="test-google-client-secret",
        google_redirect_uri="http://localhost/auth/callback",
        fernet_key=Fernet.generate_key().decode("utf-8"),
    )


@pytest.fixture
def settings(tmp_path):
    return build_settings(tmp_path)


@pytest.fixture
def app(settings):
    app = create_app(settings)
    app.config.update(TESTING=True)
    return app


@pytest.fixture
def client(app):
    return app.test_client()
