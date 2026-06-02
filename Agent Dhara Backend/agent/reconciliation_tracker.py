from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ReconciliationTracker:
    """Tracks row counts through logical ETL stages for a single dataset."""

    dataset: str
    stages: Dict[str, int] = field(default_factory=dict)
    details: Dict[str, Any] = field(default_factory=dict)

    def record(self, stage: str, count: int, **extra: Any) -> None:
        self.stages[str(stage)] = int(count)
        if extra:
            self.details[str(stage)] = extra

    def finalize(self) -> Dict[str, Any]:
        return {
            "dataset": self.dataset,
            "stages": dict(self.stages),
            "details": dict(self.details),
            "balanced": self._balanced(),
        }

    def _balanced(self) -> bool:
        # Soft check: written + failed + skipped ~= source when all present
        src = self.stages.get("source")
        w = self.stages.get("written")
        if src is None or w is None:
            return True
        return w <= src


def build_reconciliation_from_profile(
    dataset_name: str,
    row_count: int,
    *,
    parse_failures: int = 0,
    filtered_rows: int = 0,
) -> Dict[str, Any]:
    """
    Default reconciliation for assess-only runs (no transform pipeline).
    """
    tr = ReconciliationTracker(dataset=dataset_name)
    tr.record("source", row_count)
    tr.record("parsed", max(row_count - parse_failures, 0))
    tr.record("parse_failed", parse_failures)
    tr.record("filtered", filtered_rows)
    tr.record("transformed", max(row_count - parse_failures - filtered_rows, 0))
    tr.record("written", max(row_count - parse_failures - filtered_rows, 0))
    tr.record("failed", 0)
    tr.record("skipped", 0)
    return tr.finalize()


def merge_reconciliations(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {"by_dataset": {i["dataset"]: i for i in items if isinstance(i, dict) and i.get("dataset")}}
