"""
Explain reconciliation stages as deltas (pure).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional


def _stage(rec: Dict[str, Any], name: str) -> int:
    st = rec.get("stages") or {}
    try:
        return int(st.get(name) or 0)
    except (TypeError, ValueError):
        return 0


def analyze_reconciliation_record(rec: Dict[str, Any]) -> Dict[str, Any]:
    """Single dataset reconciliation breakdown."""
    if not isinstance(rec, dict):
        return {}
    ds = str(rec.get("dataset") or "")
    src = _stage(rec, "source")
    parsed = _stage(rec, "parsed")
    written = _stage(rec, "written")
    failed = _stage(rec, "failed")
    skipped = _stage(rec, "skipped")
    filtered = _stage(rec, "filtered")
    parse_failed = _stage(rec, "parse_failed")
    deltas = {
        "source_to_parsed_loss": max(0, src - parsed),
        "parsed_to_written_loss": max(0, parsed - written),
        "explicit_failures": failed,
        "skipped": skipped,
        "filtered": filtered,
        "parse_failed": parse_failed,
    }
    explain: List[str] = []
    if deltas["parse_failed"]:
        explain.append(f"{deltas['parse_failed']} row(s) estimated lost to parse failures.")
    if deltas["filtered"]:
        explain.append(f"{deltas['filtered']} row(s) marked filtered before transform.")
    if deltas["parsed_to_written_loss"] and not deltas["parse_failed"] and not deltas["filtered"]:
        explain.append(f"{deltas['parsed_to_written_loss']} row(s) delta between parsed and written — review transforms.")
    return {
        "dataset": ds,
        "deltas": deltas,
        "explainable_losses": explain,
        "balanced": rec.get("balanced"),
    }


def analyze_reconciliation_bundle(reconciliation: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Input: assessment['reconciliation'] from merge_reconciliations."""
    if not isinstance(reconciliation, dict):
        return {"by_dataset": {}}
    out: Dict[str, Any] = {}
    for ds, rec in (reconciliation.get("by_dataset") or {}).items():
        if isinstance(rec, dict):
            out[str(ds)] = analyze_reconciliation_record(rec)
    return {"by_dataset": out}
