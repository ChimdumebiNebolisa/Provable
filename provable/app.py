from __future__ import annotations

from flask import Flask

from .bootstrap import bootstrap_environment
from .config import Settings


def create_app(settings: Settings | None = None) -> Flask:
    resolved_settings = settings or Settings.from_env()
    bootstrap_environment(resolved_settings)

    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=resolved_settings.secret_key,
    )

    return app
