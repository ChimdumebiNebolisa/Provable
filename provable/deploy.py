from __future__ import annotations

import json
from dataclasses import dataclass

from .bootstrap import BootstrapResult, bootstrap_environment
from .config import Settings
from .demo_seed import DemoSeedResult, seed_demo_data


@dataclass(frozen=True, slots=True)
class DeployResult:
    database_path: str
    journal_mode: str
    storage_root: str
    demo_storage_root: str
    demo_exports_root: str
    user_storage_root: str
    demo_user_id: int
    demo_receipt_count: int
    demo_export_count: int

    @classmethod
    def from_results(
        cls,
        *,
        bootstrap_result: BootstrapResult,
        demo_seed_result: DemoSeedResult,
    ) -> "DeployResult":
        return cls(
            database_path=bootstrap_result.database_path,
            journal_mode=bootstrap_result.journal_mode,
            storage_root=bootstrap_result.storage_root,
            demo_storage_root=bootstrap_result.demo_storage_root,
            demo_exports_root=bootstrap_result.demo_exports_root,
            user_storage_root=bootstrap_result.user_storage_root,
            demo_user_id=demo_seed_result.user_id,
            demo_receipt_count=demo_seed_result.receipt_count,
            demo_export_count=demo_seed_result.export_count,
        )

    def to_dict(self) -> dict[str, str | int]:
        return {
            "database_path": self.database_path,
            "journal_mode": self.journal_mode,
            "storage_root": self.storage_root,
            "demo_storage_root": self.demo_storage_root,
            "demo_exports_root": self.demo_exports_root,
            "user_storage_root": self.user_storage_root,
            "demo_user_id": self.demo_user_id,
            "demo_receipt_count": self.demo_receipt_count,
            "demo_export_count": self.demo_export_count,
        }


def run_deploy_seed(settings: Settings | None = None) -> DeployResult:
    resolved_settings = settings or Settings.from_env()
    bootstrap_result = bootstrap_environment(resolved_settings)
    demo_seed_result = seed_demo_data(resolved_settings)
    return DeployResult.from_results(
        bootstrap_result=bootstrap_result,
        demo_seed_result=demo_seed_result,
    )


if __name__ == "__main__":
    print(json.dumps(run_deploy_seed().to_dict(), indent=2))
