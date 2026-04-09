from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlencode

import requests

from .config import Settings

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"
GOOGLE_SCOPES = (
    "openid",
    "email",
    "https://www.googleapis.com/auth/gmail.readonly",
)


class OAuthConfigError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class OAuthTokens:
    access_token: str
    refresh_token: str
    token_type: str
    scope: str


@dataclass(frozen=True, slots=True)
class GoogleIdentity:
    google_user_id: str
    email: str


class GoogleOAuthClient:
    def __init__(self, settings: Settings, session: requests.Session | None = None):
        self._settings = settings
        self._session = session or requests.Session()

    def build_authorization_url(self, state: str) -> str:
        self._ensure_configured()
        query = urlencode(
            {
                "client_id": self._settings.google_client_id,
                "redirect_uri": self._settings.google_redirect_uri,
                "response_type": "code",
                "scope": " ".join(GOOGLE_SCOPES),
                "access_type": "offline",
                "prompt": "consent",
                "include_granted_scopes": "true",
                "state": state,
            }
        )
        return f"{GOOGLE_AUTH_URL}?{query}"

    def exchange_code(self, code: str) -> OAuthTokens:
        self._ensure_configured()
        response = self._session.post(
            GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": self._settings.google_client_id,
                "client_secret": self._settings.google_client_secret,
                "redirect_uri": self._settings.google_redirect_uri,
                "grant_type": "authorization_code",
            },
            timeout=20,
        )
        response.raise_for_status()
        payload = response.json()
        refresh_token = payload.get("refresh_token")
        if not refresh_token:
            raise RuntimeError("refresh_token_missing")
        return OAuthTokens(
            access_token=payload["access_token"],
            refresh_token=refresh_token,
            token_type=payload.get("token_type", "Bearer"),
            scope=payload.get("scope", ""),
        )

    def fetch_identity(self, access_token: str) -> GoogleIdentity:
        response = self._session.get(
            GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=20,
        )
        response.raise_for_status()
        payload = response.json()
        return GoogleIdentity(
            google_user_id=str(payload["sub"]),
            email=str(payload["email"]).lower(),
        )

    def refresh_access_token(self, refresh_token: str) -> str:
        self._ensure_configured()
        response = self._session.post(
            GOOGLE_TOKEN_URL,
            data={
                "client_id": self._settings.google_client_id,
                "client_secret": self._settings.google_client_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
            timeout=20,
        )
        response.raise_for_status()
        payload = response.json()
        return str(payload["access_token"])

    def revoke_token(self, refresh_token: str) -> None:
        self._ensure_configured()
        response = self._session.post(
            "https://oauth2.googleapis.com/revoke",
            data={"token": refresh_token},
            timeout=20,
        )
        if response.status_code not in (200, 400):
            response.raise_for_status()

    def _ensure_configured(self) -> None:
        if not (
            self._settings.google_client_id
            and self._settings.google_client_secret
            and self._settings.google_redirect_uri
        ):
            raise OAuthConfigError("google_oauth_not_configured")
