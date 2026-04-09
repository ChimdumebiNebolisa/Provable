from __future__ import annotations

from flask import Flask

from .bootstrap import bootstrap_environment
from .config import Settings
from .demo_seed import seed_demo_data
from .gmail import GmailApiClient
from .gmail_scan import GmailScanExecutor
from .oauth import GoogleOAuthClient
from .routes import register_routes
from .scan import ScanManager


def create_app(settings: Settings | None = None) -> Flask:
    resolved_settings = settings or Settings.from_env()
    bootstrap_environment(resolved_settings)
    seed_demo_data(resolved_settings)
    oauth_client = GoogleOAuthClient(resolved_settings)

    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=resolved_settings.secret_key,
        PROVABLE_SETTINGS=resolved_settings,
        PROVABLE_OAUTH_CLIENT=oauth_client,
        PROVABLE_SCAN_MANAGER=ScanManager(
            settings=resolved_settings,
            executor=GmailScanExecutor(
                settings=resolved_settings,
                oauth_client=oauth_client,
                gmail_client=GmailApiClient(),
            ),
        ),
    )
    register_routes(app)

    return app
