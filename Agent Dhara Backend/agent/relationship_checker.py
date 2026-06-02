from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import pandas as pd


def check_orphans(
    child_df: pd.DataFrame,
    parent_df: pd.DataFrame,
    child_key: str,
    parent_key: str,
    *,
    child_dataset: str = "",
    parent_dataset: str = "",
) -> Dict[str, Any]:
    if child_key not in child_df.columns or parent_key not in parent_df.columns:
        return {"ok": True, "orphan_count": 0, "message": ""}
    parents = set(parent_df[parent_key].dropna().astype(str).unique())
    c = child_df[child_key].dropna().astype(str)
    orphan_mask = ~c.isin(parents)
    cnt = int(orphan_mask.sum())
    return {
        "ok": cnt == 0,
        "orphan_count": cnt,
        "message": (
            f"{cnt} orphan(s) in [{child_dataset}].{child_key} not found in "
            f"[{parent_dataset}].{parent_key}"
            if cnt
            else ""
        ),
    }


def run_relationship_checks(
    datasets: Dict[str, pd.DataFrame],
    relationships: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Returns (row_issues, warnings) compatible with global_issues lists.
    """
    row_issues: List[Dict[str, Any]] = []
    warnings: List[Dict[str, Any]] = []
    for rel in relationships or []:
        if not isinstance(rel, dict):
            continue
        da, ca = rel.get("dataset_a"), rel.get("column_a")
        db, cb = rel.get("dataset_b"), rel.get("column_b")
        if not all([da, ca, db, cb]):
            continue
        dfa = datasets.get(str(da))
        dfb = datasets.get(str(db))
        if dfa is None or dfb is None:
            continue
        # Try both directions: smaller as parent heuristic by overlap_count if present
        r1 = check_orphans(dfa, dfb, str(ca), str(cb), child_dataset=str(da), parent_dataset=str(db))
        if r1["orphan_count"]:
            row_issues.append(
                {
                    "dataset": da,
                    "column": ca,
                    "related_dataset": db,
                    "related_column": cb,
                    "count": r1["orphan_count"],
                    "severity": "high",
                    "message": r1["message"],
                }
            )
        r2 = check_orphans(dfb, dfa, str(cb), str(ca), child_dataset=str(db), parent_dataset=str(da))
        if r2["orphan_count"]:
            row_issues.append(
                {
                    "dataset": db,
                    "column": cb,
                    "related_dataset": da,
                    "related_column": ca,
                    "count": r2["orphan_count"],
                    "severity": "high",
                    "message": r2["message"],
                }
            )
    return row_issues, warnings


def relationship_issue_key(item: Dict[str, Any]) -> tuple:
    return (
        str(item.get("dataset") or ""),
        str(item.get("column") or ""),
        str(item.get("related_dataset") or ""),
        str(item.get("related_column") or ""),
    )


def merge_supplemental_relationship_issues(
    existing: List[Any],
    new: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    merged: List[Dict[str, Any]] = [x for x in existing if isinstance(x, dict)]
    keys = {relationship_issue_key(x) for x in merged}
    for item in new:
        if not isinstance(item, dict):
            continue
        k = relationship_issue_key(item)
        if k not in keys:
            merged.append(item)
            keys.add(k)
    return merged
