"""
Before/after summaries for ETL or DuckDB preview (pandas-based).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import pandas as pd


def summarize_frame_diff(
    before: pd.DataFrame,
    after: pd.DataFrame,
    *,
    key_columns: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Structural diff: rows/cols, dtype changes, optional key overlap.
    """
    out: Dict[str, Any] = {
        "before_rows": int(len(before)),
        "after_rows": int(len(after)),
        "before_cols": list(before.columns.astype(str)),
        "after_cols": list(after.columns.astype(str)),
        "row_delta": int(len(after) - len(before)),
        "added_columns": sorted(set(after.columns) - set(before.columns), key=str),
        "removed_columns": sorted(set(before.columns) - set(after.columns), key=str),
    }
    common = [c for c in before.columns if c in after.columns]
    dtype_changes = []
    for c in common:
        if str(before[c].dtype) != str(after[c].dtype):
            dtype_changes.append({"column": str(c), "before": str(before[c].dtype), "after": str(after[c].dtype)})
    out["dtype_changes"] = dtype_changes
    if key_columns and all(k in before.columns and k in after.columns for k in key_columns):
        bk = before.set_index(list(key_columns)).index.unique()
        ak = after.set_index(list(key_columns)).index.unique()
        try:
            lost = int(bk.difference(ak).size)
            new = int(ak.difference(bk).size)
            out["key_overlap"] = {"keys_lost": lost, "keys_new": new}
        except Exception:
            out["key_overlap"] = {"error": "could_not_compute"}
    return out
