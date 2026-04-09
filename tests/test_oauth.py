from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse

from provable.crypto import decrypt_refresh_token
from provable.oauth import GoogleIdentity, OAuthTokens


@dataclass
class FakeOAuthClient:
    last_state: str | None = None

    def build_authorization_url(self, state: str) -> str:
        self.last_state = state
        return (
            "https://accounts.google.com/o/oauth2/v2/auth"
            f"?state={state}&scope=openid+email+https://www.googleapis.com/auth/gmail.readonly"
        )

    def exchange_code(self, code: str) -> OAuthTokens:
        return OAuthTokens(
            access_token=f"access-{code}",
            refresh_token=f"refresh-{code}",
            token_type="Bearer",
            scope="openid email https://www.googleapis.com/auth/gmail.readonly",
        )

    def fetch_identity(self, access_token: str) -> GoogleIdentity:
        return GoogleIdentity(
            google_user_id="google-user-123",
            email="real-user@example.com",
        )


def test_auth_login_redirects_with_state_cookie(app, client):
    app.config["PROVABLE_OAUTH_CLIENT"] = FakeOAuthClient()

    response = client.get("/auth/login")

    assert response.status_code == 302
    assert response.headers["Location"].startswith("https://accounts.google.com/o/oauth2/v2/auth")
    set_cookie = response.headers["Set-Cookie"]
    assert "provable_oauth_state=" in set_cookie
    assert "HttpOnly" in set_cookie
    assert "SameSite=Lax" in set_cookie


def test_auth_callback_rejects_invalid_state(app, client):
    app.config["PROVABLE_OAUTH_CLIENT"] = FakeOAuthClient()
    client.get("/auth/login")

    response = client.get("/auth/callback?state=wrong-state&code=test-code")

    assert response.status_code == 400
    assert response.get_json()["error"] == "invalid_oauth_state"


def test_auth_callback_creates_real_user_session_and_encrypted_token(app, client, settings):
    fake_oauth = FakeOAuthClient()
    app.config["PROVABLE_OAUTH_CLIENT"] = fake_oauth

    login_response = client.get("/auth/login")
    state = parse_qs(urlparse(login_response.headers["Location"]).query)["state"][0]

    callback_response = client.get(f"/auth/callback?state={state}&code=test-code")

    assert callback_response.status_code == 302
    assert callback_response.headers["Location"] == "/"

    with sqlite3.connect(settings.database_path) as connection:
        user_row = connection.execute(
            "SELECT id, email, is_demo FROM users WHERE email = ?",
            ("real-user@example.com",),
        ).fetchone()
        gmail_row = connection.execute(
            """
            SELECT user_id, google_user_id, email, refresh_token_encrypted
            FROM gmail_accounts
            WHERE email = ?
            """,
            ("real-user@example.com",),
        ).fetchone()
        session_count = connection.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]

    assert user_row is not None
    assert user_row[2] == 0
    assert gmail_row is not None
    assert gmail_row[1] == "google-user-123"
    assert gmail_row[3] != "refresh-test-code"
    assert decrypt_refresh_token(gmail_row[3], settings.fernet_key) == "refresh-test-code"
    assert session_count == 1


def test_auth_callback_keeps_single_gmail_account_per_user(app, client, settings):
    app.config["PROVABLE_OAUTH_CLIENT"] = FakeOAuthClient()

    first_login = client.get("/auth/login")
    first_state = parse_qs(urlparse(first_login.headers["Location"]).query)["state"][0]
    first_callback = client.get(f"/auth/callback?state={first_state}&code=first")
    assert first_callback.status_code == 302

    second_login = client.get("/auth/login")
    second_state = parse_qs(urlparse(second_login.headers["Location"]).query)["state"][0]
    second_callback = client.get(f"/auth/callback?state={second_state}&code=second")
    assert second_callback.status_code == 302

    with sqlite3.connect(settings.database_path) as connection:
        gmail_account_count = connection.execute(
            "SELECT COUNT(*) FROM gmail_accounts WHERE email = ?",
            ("real-user@example.com",),
        ).fetchone()[0]
        encrypted_token = connection.execute(
            "SELECT refresh_token_encrypted FROM gmail_accounts WHERE email = ?",
            ("real-user@example.com",),
        ).fetchone()[0]

    assert gmail_account_count == 1
    assert decrypt_refresh_token(encrypted_token, settings.fernet_key) == "refresh-second"
