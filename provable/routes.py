from __future__ import annotations

from collections import defaultdict
from datetime import timedelta

from flask import Flask, current_app, jsonify, make_response, request, send_file

from .config import Settings
from .db import connect_database
from .demo_seed import DEMO_USER_EMAIL
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

    @app.get("/receipts")
    def list_receipts():
        settings = _settings()
        session, response = _require_session()
        if response is not None:
            return response

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
                WHERE user_id = ?
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
            return jsonify({"error": "real_export_not_implemented"}), 501

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


def _set_session_cookie(response, session_id: str, settings: Settings) -> None:
    response.set_cookie(
        settings.session_cookie_name,
        session_id,
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
