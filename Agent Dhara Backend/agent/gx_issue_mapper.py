from __future__ import annotations

from typing import Any, Dict, List, Optional


def _enrich_issue(row: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(row)
    src = str(out.get("source") or "")
    sev = str(out.get("severity") or "medium").lower()
    etl_imp = str(out.get("etl_impact") or "")
    out.setdefault("confidence", out.get("semantic_confidence"))
    out.setdefault(
        "business_impact",
        "high" if sev == "high" or etl_imp in ("blocking", "row_loss_risk") else "medium",
    )
    root = "Unknown upstream or mapping issue."
    fix = "Review source data and validation rules."
    fix_etl = False
    if src == "gx":
        root = "Data violates a Great Expectations rule relative to the profiled baseline."
        fix = "Correct source values or relax/adjust expectations after business sign-off."
        fix_etl = False
    elif src == "drift":
        root = "Profile metrics shifted versus the last stored snapshot."
        fix = "Confirm intentional upstream change; rebaseline snapshot if approved."
        fix_etl = True
    elif src == "reconciliation":
        root = "Row counts across logical ETL stages do not reconcile."
        fix = "Trace filters, parses, and writes; ensure no silent row drops."
        fix_etl = True
    out.setdefault("likely_root_cause", root)
    out.setdefault("suggested_fix", fix)
    out.setdefault("fix_changes_etl_logic", fix_etl)
    return out


def map_gx_to_unified_issues(
    gx_results: Dict[str, Any],
    *,
    semantic_by_dataset: Optional[Dict[str, Any]] = None,
    drift_by_dataset: Optional[Dict[str, Any]] = None,
    reconciliation: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """
    Map GX per-dataset results into a unified issue list with business labels
    and operator-oriented fields (root cause, fix scope).
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
                    "rule_origin": "gx_expectation",
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
                    "rule_origin": "drift_snapshot",
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
                        "rule_origin": "reconciliation_tracker",
                    }
                )

    return [_enrich_issue(x) for x in issues]
