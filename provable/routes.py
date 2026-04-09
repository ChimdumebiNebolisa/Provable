from __future__ import annotations

from collections import defaultdict
import secrets
from datetime import timedelta

from flask import Flask, current_app, jsonify, redirect, request, send_file

from .config import Settings
from .crypto import CryptoConfigError, decrypt_refresh_token, encrypt_refresh_token
from .db import connect_database
from .demo_seed import DEMO_USER_EMAIL
from .exporter import ExportLimitError, build_real_user_export
from .oauth import OAuthConfigError
from .session_store import create_session, delete_session, get_current_session
from .validators import validate_month


def register_routes(app: Flask) -> None:
    @app.get("/")
    def landing():
        return jsonify({"name": "Provable", "status": "ok"})

    @app.get("/health")
    def health():
        return jsonify({"status": "ok"})

    @app.post("/demo")
    def create_demo_session():
        settings = _settings()
        with connect_database(settings.database_path) as connection:
            user_row = connection.execute(
                "SELECT id FROM users WHERE email = ? AND is_demo = 1",
                (DEMO_USER_EMAIL,),
            ).fetchone()
            if user_row is None:
                return jsonify({"error": "demo_seed_missing"}), 500

            session = create_session(
                connection,
                user_id=int(user_row["id"]),
                ttl=timedelta(minutes=settings.demo_session_ttl_minutes),
            )

        response = jsonify({"status": "demo_session_created"})
        _set_session_cookie(response, session.session_id, settings)
        return response

    @app.get("/auth/login")
    def auth_login():
        settings = _settings()
        oauth_client = _oauth_client()
        state = secrets.token_urlsafe(32)

        try:
            authorization_url = oauth_client.build_authorization_url(state)
        except OAuthConfigError as exc:
            return jsonify({"error": str(exc)}), 503

        response = redirect(authorization_url, code=302)
        _set_oauth_state_cookie(response, state, settings)
        return response

    @app.get("/auth/callback")
    def auth_callback():
        settings = _settings()
        oauth_client = _oauth_client()
        callback_state = request.args.get("state", "")
        cookie_state = request.cookies.get(settings.oauth_state_cookie_name, "")

        if not callback_state or not cookie_state or callback_state != cookie_state:
            response = jsonify({"error": "invalid_oauth_state"})
            _clear_oauth_state_cookie(response, settings)
            return response, 400

        if request.args.get("error"):
            response = jsonify(
                {
                    "error": "oauth_error",
                    "detail": request.args.get("error"),
                }
            )
            _clear_oauth_state_cookie(response, settings)
            return response, 400

        code = request.args.get("code")
        if not code:
            response = jsonify({"error": "missing_oauth_code"})
            _clear_oauth_state_cookie(response, settings)
            return response, 400

        try:
            tokens = oauth_client.exchange_code(code)
            identity = oauth_client.fetch_identity(tokens.access_token)
            refresh_token_encrypted = encrypt_refresh_token(tokens.refresh_token, settings.fernet_key)
        except OAuthConfigError as exc:
            response = jsonify({"error": str(exc)})
            _clear_oauth_state_cookie(response, settings)
            return response, 503
        except CryptoConfigError as exc:
            response = jsonify({"error": str(exc)})
            _clear_oauth_state_cookie(response, settings)
            return response, 503
        except Exception as exc:
            response = jsonify({"error": "oauth_exchange_failed", "detail": str(exc)})
            _clear_oauth_state_cookie(response, settings)
            return response, 502

        with connect_database(settings.database_path) as connection:
            connection.execute(
                """
                INSERT INTO users(email, is_demo)
                VALUES(?, 0)
                ON CONFLICT(email) DO UPDATE SET is_demo = 0
                """,
                (identity.email,),
            )
            user_id = int(
                connection.execute(
                    "SELECT id FROM users WHERE email = ?",
                    (identity.email,),
                ).fetchone()["id"]
            )

            connection.execute(
                """
                INSERT INTO gmail_accounts(
                  user_id,
                  google_user_id,
                  email,
                  refresh_token_encrypted,
                  status
                )
                VALUES(?, ?, ?, ?, 'connected_active')
                ON CONFLICT(user_id) DO UPDATE SET
                  google_user_id = excluded.google_user_id,
                  email = excluded.email,
                  refresh_token_encrypted = excluded.refresh_token_encrypted,
                  status = excluded.status
                """,
                (
                    user_id,
                    identity.google_user_id,
                    identity.email,
                    refresh_token_encrypted,
                ),
            )
            connection.commit()
            session = create_session(
                connection,
                user_id=user_id,
                ttl=timedelta(hours=settings.real_session_ttl_hours),
            )

        response = redirect("/", code=302)
        _set_session_cookie(response, session.session_id, settings)
        _clear_oauth_state_cookie(response, settings)
        _scan_manager().start_scan(user_id=user_id, trigger="connect", only_if_stale=False)
        return response

    @app.post("/demo/reset")
    def reset_demo_session():
        settings = _settings()
        session, response = _require_session()
        if response is not None:
            return response
        if not session.is_demo:
            return jsonify({"error": "demo_session_required"}), 403

        with connect_database(settings.database_path) as connection:
            delete_session(connection, session.session_id)

        response = jsonify({"status": "demo_session_cleared"})
        _clear_session_cookie(response, settings)
        return response

    @app.post("/auth/disconnect")
    def disconnect_account():
        settings = _settings()
        session, response = _require_session()
        if response is not None:
            return response
        if session.is_demo:
            return jsonify({"error": "real_user_required"}), 403

        refresh_token = None
        user_storage_root = settings.user_storage_root / str(session.user_id)
        with connect_database(settings.database_path) as connection:
            gmail_row = connection.execute(
                """
                SELECT refresh_token_encrypted
                FROM gmail_accounts
                WHERE user_id = ?
                """,
                (session.user_id,),
            ).fetchone()
            if gmail_row is not None and gmail_row["refresh_token_encrypted"]:
                refresh_token = decrypt_refresh_token(
                    str(gmail_row["refresh_token_encrypted"]),
                    settings.fernet_key,
                )

            connection.execute("DELETE FROM sessions WHERE user_id = ?", (session.user_id,))
            connection.execute("DELETE FROM receipts WHERE user_id = ?", (session.user_id,))
            connection.execute("DELETE FROM gmail_accounts WHERE user_id = ?", (session.user_id,))
            connection.execute("DELETE FROM users WHERE id = ?", (session.user_id,))
            connection.commit()

        if user_storage_root.exists():
            import shutil

            shutil.rmtree(user_storage_root)

        if refresh_token:
            try:
                _oauth_client().revoke_token(refresh_token)
            except Exception:
                pass

        response = jsonify({"status": "disconnected"})
        _clear_session_cookie(response, settings)
        return response

    @app.get("/receipts")
    def list_receipts():
        settings = _settings()
        session, response = _require_session()
        if response is not None:
            return response
        if not session.is_demo:
            _scan_manager().start_scan(
                user_id=session.user_id,
                trigger="open",
                only_if_stale=True,
            )

        with connect_database(settings.database_path) as connection:
            rows = connection.execute(
                """
                SELECT
                  id,
                  vendor,
                  receipt_date,
                  amount_cents,
                  storage_path,
                  confidence_score,
                  high_confidence,
                  source
                FROM receipts
                WHERE user_id = ? AND high_confidence = 1
                ORDER BY receipt_date DESC, vendor ASC, id ASC
                """,
                (session.user_id,),
            ).fetchall()

        by_month: dict[str, list[dict[str, object]]] = defaultdict(list)
        for row in rows:
            month = str(row["receipt_date"])[:7]
            by_month[month].append(
                {
                    "id": int(row["id"]),
                    "vendor": row["vendor"],
                    "receipt_date": row["receipt_date"],
                    "amount_cents": row["amount_cents"],
                    "storage_path": row["storage_path"],
                    "confidence_score": int(row["confidence_score"]),
                    "high_confidence": bool(row["high_confidence"]),
                    "source": row["source"],
                }
            )

        months = sorted(by_month.keys(), reverse=True)
        return jsonify({"months": months, "byMonth": {month: by_month[month] for month in months}})

    @app.post("/scan")
    def trigger_scan():
        session, response = _require_session()
        if response is not None:
            return response
        if session.is_demo:
            return jsonify({"error": "gmail_account_required"}), 400

        status = _scan_manager().start_scan(
            user_id=session.user_id,
            trigger="manual",
            only_if_stale=False,
        )
        if status == "started":
            return jsonify({"status": "started"}), 202
        if status == "already_running":
            return jsonify({"error": "scan_in_progress"}), 409
        if status == "missing_account":
            return jsonify({"error": "gmail_account_required"}), 400

        return jsonify({"error": status}), 400

    @app.get("/scan/status")
    def scan_status():
        session, response = _require_session()
        if response is not None:
            return response
        if session.is_demo:
            return jsonify({"error": "gmail_account_required"}), 400

        status = _scan_manager().get_status(user_id=session.user_id)
        if status is None:
            return jsonify({"error": "gmail_account_required"}), 400

        return jsonify(
            {
                "scan_in_progress": status.scan_in_progress,
                "last_scan_at": status.last_scan_at,
                "last_scan_status": status.last_scan_status,
                "last_scan_error": status.last_scan_error,
            }
        )

    @app.get("/export/<month>")
    def export_month(month: str):
        settings = _settings()
        session, response = _require_session()
        if response is not None:
            return response

        try:
            validated_month = validate_month(month)
        except ValueError:
            return jsonify({"error": "invalid_month"}), 400
        if not session.is_demo:
            try:
                export_buffer = build_real_user_export(
                    settings=settings,
                    user_id=session.user_id,
                    month=validated_month,
                )
            except ExportLimitError as exc:
                return jsonify({"error": str(exc)}), 400
            except FileNotFoundError:
                return jsonify({"error": "missing_receipt_file"}), 500
            if export_buffer is None:
                return jsonify({"error": "export_not_found"}), 404
            return send_file(
                export_buffer,
                mimetype="application/zip",
                as_attachment=True,
                download_name=f"{validated_month}.zip",
            )

        export_path = settings.demo_exports_root / f"{validated_month}.zip"
        if not export_path.exists():
            return jsonify({"error": "export_not_found"}), 404

        return send_file(
            export_path,
            mimetype="application/zip",
            as_attachment=True,
            download_name=f"{validated_month}.zip",
        )


def _require_session():
    settings = _settings()
    with connect_database(settings.database_path) as connection:
        session = get_current_session(
            connection,
            request.cookies.get(settings.session_cookie_name),
        )

    if session is None:
        response = jsonify({"error": "unauthenticated"})
        _clear_session_cookie(response, settings)
        return None, (response, 401)

    return session, None


def _settings() -> Settings:
    return current_app.config["PROVABLE_SETTINGS"]


def _oauth_client():
    return current_app.config["PROVABLE_OAUTH_CLIENT"]


def _scan_manager():
    return current_app.config["PROVABLE_SCAN_MANAGER"]


def _set_session_cookie(response, session_id: str, settings: Settings) -> None:
    response.set_cookie(
        settings.session_cookie_name,
        session_id,
        httponly=True,
        samesite="Lax",
        secure=settings.is_production,
        path="/",
    )


def _set_oauth_state_cookie(response, state: str, settings: Settings) -> None:
    response.set_cookie(
        settings.oauth_state_cookie_name,
        state,
        max_age=600,
        httponly=True,
        samesite="Lax",
        secure=settings.is_production,
        path="/",
    )


def _clear_oauth_state_cookie(response, settings: Settings) -> None:
    response.set_cookie(
        settings.oauth_state_cookie_name,
        "",
        expires=0,
        httponly=True,
        samesite="Lax",
        secure=settings.is_production,
        path="/",
    )


def _clear_session_cookie(response, settings: Settings) -> None:
    response.set_cookie(
        settings.session_cookie_name,
        "",
        expires=0,
        httponly=True,
        samesite="Lax",
        secure=settings.is_production,
        path="/",
    )
