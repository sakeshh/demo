from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

logger = logging.getLogger(__name__)

DEFAULT_POLICY = Path(__file__).resolve().parent.parent / "config" / "drift_policy.yaml"


def _load_policy(path: Optional[str] = None) -> Dict[str, Any]:
    p = Path(path or os.getenv("DHARA_DRIFT_POLICY", str(DEFAULT_POLICY)))
    if not p.is_file():
        return {
            "row_count_relative": 0.15,
            "null_rate_absolute": 0.08,
            "distinct_count_relative": 0.25,
        }
    try:
        with open(p, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


def compare_snapshots(
    previous: Optional[Dict[str, Any]],
    current_fp: Dict[str, Any],
    *,
    policy_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Compare previous snapshot payload (from profile_snapshot_store) to current fingerprint.
    """
    policy = _load_policy(policy_path)
    rel_tol = float(policy.get("row_count_relative") or 0.15)
    null_abs = float(policy.get("null_rate_absolute") or 0.08)
    dist_tol = float(policy.get("distinct_count_relative") or 0.25)

    signals: List[Dict[str, Any]] = []
    if not previous or not isinstance(previous, dict):
        return {"has_baseline": False, "signals": [], "severity": "none"}

    prev_fp = previous.get("fingerprint") or previous
    if not isinstance(prev_fp, dict):
        return {"has_baseline": False, "signals": [], "severity": "none"}

    pr = int(prev_fp.get("row_count") or 0)
    cr = int(current_fp.get("row_count") or 0)
    if pr > 0:
        delta = abs(cr - pr) / pr
        if delta > rel_tol:
            signals.append(
                {
                    "kind": "row_count_drift",
                    "previous": pr,
                    "current": cr,
                    "relative_delta": round(delta, 4),
                    "severity": "high" if delta > rel_tol * 2 else "medium",
                }
            )

    prev_cols = prev_fp.get("columns") or {}
    cur_cols = current_fp.get("columns") or {}
    if isinstance(prev_cols, dict) and isinstance(cur_cols, dict):
        prev_names = set(prev_cols.keys())
        cur_names = set(cur_cols.keys())
        added = cur_names - prev_names
        removed = prev_names - cur_names
        if added or removed:
            signals.append(
                {
                    "kind": "schema_drift",
                    "columns_added": sorted(added),
                    "columns_removed": sorted(removed),
                    "severity": "high",
                }
            )
        for c in sorted(prev_names & cur_names):
            a = prev_cols.get(c) or {}
            b = cur_cols.get(c) or {}
            if not isinstance(a, dict) or not isinstance(b, dict):
                continue
            if str(a.get("dtype")) != str(b.get("dtype")):
                signals.append(
                    {
                        "kind": "dtype_drift",
                        "column": c,
                        "previous": a.get("dtype"),
                        "current": b.get("dtype"),
                        "severity": "medium",
                    }
                )
            try:
                n0 = float(a.get("null_pct") or 0)
                n1 = float(b.get("null_pct") or 0)
                if abs(n1 - n0) > null_abs:
                    signals.append(
                        {
                            "kind": "null_rate_drift",
                            "column": c,
                            "previous": n0,
                            "current": n1,
                            "severity": "medium",
                        }
                    )
            except (TypeError, ValueError):
                pass
            try:
                u0 = int(a.get("unique") or 0)
                u1 = int(b.get("unique") or 0)
                if u0 > 10 and u1 > 0:
                    d = abs(u1 - u0) / max(u0, 1)
                    if d > dist_tol:
                        signals.append(
                            {
                                "kind": "distinct_count_drift",
                                "column": c,
                                "previous": u0,
                                "current": u1,
                                "relative_delta": round(d, 4),
                                "severity": "low",
                            }
                        )
            except (TypeError, ValueError):
                pass

    sev_order = {"high": 3, "medium": 2, "low": 1, "none": 0}
    top = "none"
    for s in signals:
        sv = str(s.get("severity") or "low")
        if sev_order.get(sv, 0) > sev_order.get(top, 0):
            top = sv

    return {"has_baseline": True, "signals": signals, "severity": top}
