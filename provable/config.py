from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _default_storage_root(app_env: str) -> Path:
    if app_env == "production":
        return Path("/app/storage")
    return PROJECT_ROOT / "storage"


def _resolve_path(raw_path: str, *, project_root: Path) -> Path:
    candidate = Path(raw_path).expanduser()
    if candidate.is_absolute():
        return candidate.resolve()
    return (project_root / candidate).resolve()


@dataclass(frozen=True, slots=True)
class Settings:
    app_env: str
    secret_key: str
    storage_root: Path
    database_path: Path
    demo_storage_root: Path
    demo_exports_root: Path
    user_storage_root: Path

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @classmethod
    def from_env(cls) -> "Settings":
        app_env = os.getenv("PROVABLE_ENV", "development").strip().lower() or "development"
        storage_root = _resolve_path(
            os.getenv("PROVABLE_STORAGE_ROOT", str(_default_storage_root(app_env))),
            project_root=PROJECT_ROOT,
        )
        database_path = _resolve_path(
            os.getenv("PROVABLE_DB_PATH", str(storage_root / "provable.sqlite3")),
            project_root=PROJECT_ROOT,
        )
        return cls(
            app_env=app_env,
            secret_key=os.getenv("PROVABLE_SECRET_KEY", "development-only"),
            storage_root=storage_root,
            database_path=database_path,
            demo_storage_root=storage_root / "demo",
            demo_exports_root=storage_root / "demo_exports",
            user_storage_root=storage_root / "users",
        )
