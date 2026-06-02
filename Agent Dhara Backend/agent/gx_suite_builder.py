"""
Describe GX-style expectations from profiling (documentation / future suite split).
Runtime execution remains in specialists.gx_validation_specialist.
"""
from __future__ import annotations

from typing import Any, Dict, List


def list_expectation_descriptors_from_assessment(assessment: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Return a structured list of expectation kinds that *would* apply per column.
    """
    out: List[Dict[str, Any]] = []
    for ds_name, ds in (assessment.get("datasets") or {}).items():
        if not isinstance(ds, dict):
            continue
        for col, meta in (ds.get("columns") or {}).items():
            if not isinstance(meta, dict):
                continue
            null_pct = float(meta.get("null_percentage") or 0)
            kinds: List[str] = ["expect_column_values_to_not_be_null"]
            if null_pct > 0:
                kinds = ["expect_column_values_to_not_be_null(mostly=...)"]
            if meta.get("candidate_primary_key"):
                kinds.append("expect_column_values_to_be_unique")
            st = str(meta.get("semantic_type") or "").lower()
            if st == "email":
                kinds.append("expect_column_values_to_match_regex(email)")
            elif st in ("uuid", "guid"):
                kinds.append("expect_column_values_to_match_regex(uuid)")
            elif st == "date":
                kinds.append("expect_column_values_to_be_dateutil_parseable")
            uq = int(meta.get("unique_count") or 0)
            if 0 < uq <= 25:
                kinds.append("expect_column_values_to_be_in_set(low_cardinality)")
            out.append({"dataset": str(ds_name), "column": str(col), "expectations": kinds})
    return out
