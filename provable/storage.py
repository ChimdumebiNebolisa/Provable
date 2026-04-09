from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .config import Settings


@dataclass(frozen=True, slots=True)
class StoragePaths:
    root: Path
    demo: Path
    demo_exports: Path
    users: Path

    def all_paths(self) -> tuple[Path, ...]:
        return (self.root, self.demo, self.demo_exports, self.users)


def ensure_storage_paths(settings: Settings) -> StoragePaths:
    paths = StoragePaths(
        root=settings.storage_root,
        demo=settings.demo_storage_root,
        demo_exports=settings.demo_exports_root,
        users=settings.user_storage_root,
    )

    for path in paths.all_paths():
        path.mkdir(parents=True, exist_ok=True)
        _assert_writable(path)

    return paths


def _assert_writable(path: Path) -> None:
    probe_path = path / ".provable-write-check"
    probe_path.write_text("ok", encoding="utf-8")
    probe_path.unlink()
