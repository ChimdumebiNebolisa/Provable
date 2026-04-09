from __future__ import annotations

import json
from dataclasses import dataclass

from .config import Settings
from .db import connect_database, get_journal_mode, initialize_schema
from .storage import StoragePaths, ensure_storage_paths


@dataclass(frozen=True, slots=True)
class BootstrapResult:
    database_path: str
    journal_mode: str
    storage_root: str
    demo_storage_root: str
    demo_exports_root: str
    user_storage_root: str

    @classmethod
    def from_paths(
        cls,
        *,
        database_path: str,
        journal_mode: str,
        paths: StoragePaths,
    ) -> "BootstrapResult":
        return cls(
            database_path=database_path,
            journal_mode=journal_mode,
            storage_root=str(paths.root),
            demo_storage_root=str(paths.demo),
            demo_exports_root=str(paths.demo_exports),
            user_storage_root=str(paths.users),
        )

    def to_dict(self) -> dict[str, str]:
        return {
            "database_path": self.database_path,
            "journal_mode": self.journal_mode,
            "storage_root": self.storage_root,
            "demo_storage_root": self.demo_storage_root,
            "demo_exports_root": self.demo_exports_root,
            "user_storage_root": self.user_storage_root,
        }


def bootstrap_environment(settings: Settings | None = None) -> BootstrapResult:
    resolved_settings = settings or Settings.from_env()
    paths = ensure_storage_paths(resolved_settings)

    connection = connect_database(resolved_settings.database_path)
    try:
        initialize_schema(connection)
        journal_mode = get_journal_mode(connection)
    finally:
        connection.close()

    return BootstrapResult.from_paths(
        database_path=str(resolved_settings.database_path),
        journal_mode=journal_mode,
        paths=paths,
    )


if __name__ == "__main__":
    print(json.dumps(bootstrap_environment().to_dict(), indent=2))
