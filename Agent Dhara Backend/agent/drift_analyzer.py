"""
Aggregate drift outputs into scores and rollups (pure, no I/O).
"""
from __future__ import annotations

from typing import Any, Dict, List

_SEV_ORDER = {"none": 0, "low": 1, "medium": 2, "high": 3}


def aggregate_drift(by_dataset: Dict[str, Any]) -> Dict[str, Any]:
    """
    Input: assessment['drift']['by_dataset'] values from drift_detector.compare_snapshots.
    Output: global rollup for readiness/report.
    """
    worst = "none"
    total_signals = 0
    per_ds: List[Dict[str, Any]] = []
    for ds_name, block in (by_dataset or {}).items():
        if not isinstance(block, dict):
            continue
        sev = str(block.get("severity") or "none").lower()
        sigs = block.get("signals") or []
        n = len(sigs) if isinstance(sigs, list) else 0
        total_signals += n
        if _SEV_ORDER.get(sev, 0) > _SEV_ORDER.get(worst, 0):
            worst = sev
        per_ds.append(
            {
                "dataset": str(ds_name),
                "severity": sev,
                "signal_count": n,
                "has_baseline": bool(block.get("has_baseline")),
            }
        )
    # Simple score 0–100 (100 = no drift concern)
    score = 100
    if worst == "high":
        score -= 35
    elif worst == "medium":
        score -= 18
    elif worst == "low":
        score -= 8
    score -= min(20, total_signals * 2)
    return {
        "drift_score": max(0, score),
        "worst_severity": worst,
        "total_signal_count": total_signals,
        "per_dataset": per_ds,
    }
