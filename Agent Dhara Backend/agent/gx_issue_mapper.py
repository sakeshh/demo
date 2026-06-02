from __future__ import annotations

from typing import Any, Dict, List, Optional


def map_gx_to_unified_issues(
    gx_results: Dict[str, Any],
    *,
    semantic_by_dataset: Optional[Dict[str, Any]] = None,
    drift_by_dataset: Optional[Dict[str, Any]] = None,
    reconciliation: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """
    Map GX per-dataset results into a unified issue list with business labels.
    """
    semantic_by_dataset = semantic_by_dataset or {}
    drift_by_dataset = drift_by_dataset or {}
    issues: List[Dict[str, Any]] = []

    for ds_name, block in (gx_results or {}).items():
        if str(ds_name).startswith("_"):
            continue
        if not isinstance(block, dict):
            continue
        if block.get("error"):
            issues.append(
                {
                    "source": "gx",
                    "dataset": ds_name,
                    "severity": "high",
                    "business_criticality": "medium",
                    "semantic_confidence": None,
                    "fix_priority": "P1",
                    "etl_impact": "blocking",
                    "message": str(block.get("error")),
                    "column": "",
                }
            )
            continue
        sem_ctx = (semantic_by_dataset or {}).get(ds_name) or {}
        crit = set(str(x) for x in (sem_ctx.get("critical_columns") or []))
        sconf = sem_ctx.get("semantic_confidence")

        for row in block.get("results") or []:
            if not isinstance(row, dict):
                continue
            if row.get("success"):
                continue
            col = str(row.get("column") or "")
            crit_b = "high" if col in crit else "medium"
            issues.append(
                {
                    "source": "gx",
                    "dataset": ds_name,
                    "column": col,
                    "severity": "medium",
                    "business_criticality": crit_b,
                    "semantic_confidence": sconf,
                    "fix_priority": "P2" if crit_b == "high" else "P3",
                    "etl_impact": "cleaning_or_validation",
                    "message": f"{row.get('expectation')}: {row.get('details')}",
                    "gx_expectation": row.get("expectation"),
                }
            )

    for ds, drift in (drift_by_dataset or {}).items():
        if not isinstance(drift, dict):
            continue
        for sig in drift.get("signals") or []:
            if not isinstance(sig, dict):
                continue
            issues.append(
                {
                    "source": "drift",
                    "dataset": ds,
                    "column": sig.get("column") or "",
                    "severity": sig.get("severity") or "medium",
                    "business_criticality": "medium",
                    "semantic_confidence": None,
                    "fix_priority": "P2",
                    "etl_impact": "monitoring",
                    "message": f"{sig.get('kind')}: {sig}",
                }
            )

    if isinstance(reconciliation, dict):
        for ds, rec in (reconciliation.get("by_dataset") or {}).items():
            if not isinstance(rec, dict):
                continue
            if rec.get("balanced") is False:
                issues.append(
                    {
                        "source": "reconciliation",
                        "dataset": ds,
                        "severity": "medium",
                        "business_criticality": "high",
                        "semantic_confidence": None,
                        "fix_priority": "P1",
                        "etl_impact": "row_loss_risk",
                        "message": "Reconciliation stages do not align; review counts.",
                        "column": "",
                    }
                )

    return issues
