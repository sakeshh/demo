"""
Build explicit step['params'] dicts from assessment stats, evidence, and business rules.
All engines read params — evidence remains advisory for UI only.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional


def _is_numeric_dtype(dtype: str, col_stats: Dict[str, Any]) -> bool:
    d = (dtype or "").lower()
    if d in ("int", "integer", "float", "double", "decimal", "numeric", "number"):
        return True
    inf = str(col_stats.get("dtype_inference") or "").lower()
    return inf in ("numeric", "integer", "float")


def _is_text_dtype(dtype: str, col_stats: Dict[str, Any]) -> bool:
    d = (dtype or "").lower()
    if d in ("str", "string", "text", "object", "varchar"):
        return True
    inf = str(col_stats.get("dtype_inference") or "").lower()
    return inf in ("string", "text", "categorical")


def build_step_params(
    action: str,
    *,
    column: Optional[str],
    col_stats: Dict[str, Any],
    evidence: Dict[str, Any],
    rules: Dict[str, Any],
    issue_type: str = "",
) -> Dict[str, Any]:
    """Return normalized params dict for a plan step."""
    act = (action or "").lower()
    params: Dict[str, Any] = {
        "execution_mode": "in_place",
    }
    dtype = str(col_stats.get("semantic_type") or col_stats.get("dtype") or "")
    strategy = str(rules.get("outlier_strategy") or "flag").lower()

    if act in ("fill_or_drop", "fill_nulls_simple"):
        semantic_type = str(col_stats.get("semantic_type") or "").lower().strip()
        
        # ID, Date, Email, Phone should never be filled with metric defaults. Default to NULL.
        if semantic_type in ("id", "date", "phone", "email"):
            params["fill_strategy"] = "value"
            params["fill_value"] = None
        else:
            rec = evidence.get("recommended_fill") if isinstance(evidence, dict) else None
            if rec in ("mean", "median"):
                params["fill_strategy"] = rec
            elif _is_numeric_dtype(dtype, col_stats) and semantic_type == "metric":
                params["fill_strategy"] = rec or "median"
            elif _is_text_dtype(dtype, col_stats) or semantic_type == "text":
                params["fill_strategy"] = "value"
                params["fill_value"] = None  # Leave as NULL instead of empty string
            else:
                params["fill_strategy"] = "value"
                params["fill_value"] = None

            if evidence.get("median") is not None and params.get("fill_strategy") == "median":
                params["fill_value"] = evidence["median"]
            elif evidence.get("mean") is not None and params.get("fill_strategy") == "mean":
                params["fill_value"] = evidence["mean"]

    elif act in ("flag_outliers", "clip_or_flag", "clip_outliers", "cap_outliers", "range_clip"):
        method = strategy if strategy in ("flag", "clip", "cap") else "flag"
        if act == "clip_outliers":
            method = "clip"
        elif act == "cap_outliers":
            method = "cap"
        elif act in ("flag_outliers", "clip_or_flag"):
            method = "flag"
        params["outlier_method"] = method
        params["outlier_iqr_multiplier"] = float(
            evidence.get("outlier_iqr_multiplier") or 1.5
        )
        if evidence.get("median") is not None:
            params["fill_value"] = evidence["median"]
        if evidence.get("p5") is not None:
            params["p5"] = evidence["p5"]
        if evidence.get("p95") is not None:
            params["p95"] = evidence["p95"]

    elif act in ("hash_phone", "mask_phone"):
        params["privacy"] = "hash" if act == "hash_phone" else "mask"
        params["execution_mode"] = "in_place"

    elif act in ("drop_column", "exclude_column"):
        params["privacy"] = "exclude"
        params["execution_mode"] = "in_place"

    elif act in ("lowercase", "uppercase"):
        params["case_mode"] = act.replace("case", "")

    elif act == "zero_to_null":
        import yaml
        import os
        backend_dir = r"c:\Users\ssakesh\Downloads\DHARA-GX\Agent Dhara Backend"
        sentinels = [0, -999, 999999, 9999999]
        try:
            with open(os.path.join(backend_dir, "config", "dq_thresholds.yaml"), "r") as f:
                cfg = yaml.safe_load(f) or {}
            sentinels = cfg.get("sentinels", sentinels)
        except Exception:
            pass
        
        # Merge sentinels with typical punctuation values
        params["replace_values"] = list(set([str(s) for s in sentinels] + ["0", "###", "nan", "null"]))
        params["execution_mode"] = "in_place"

    return params


def build_ri_step_params(rstep: Dict[str, Any], rules: Dict[str, Any]) -> Dict[str, Any]:
    """Params for referential-integrity validation steps from relationship planner."""
    mode = "quarantine" if rules.get("never_drop_rows") else "flag"
    
    fk_actions = rules.get("fk_integrity_actions") or {}
    ds = rstep.get("dataset") or ""
    col = rstep.get("column") or ""
    rel_ds = rstep.get("related_dataset") or ""
    rel_col = rstep.get("related_column") or ""
    
    rel_key = f"{ds}.{col}->{rel_ds}.{rel_col}"
    rel_key_clean = rel_key.replace("[", "").replace("]", "").replace("`", "").lower().strip()
    
    fk_action = "flag"
    for k, act in fk_actions.items():
        k_clean = str(k).replace("[", "").replace("]", "").replace("`", "").lower().strip()
        if k_clean == rel_key_clean:
            fk_action = act
            break
            
    return {
        "related_dataset": rel_ds,
        "related_column": rel_col,
        "enforcement_mode": mode,
        "execution_mode": "new_table",
        "fk_action": fk_action
    }
