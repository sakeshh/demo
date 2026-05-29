"""
Phase Classifier: maps actions to "cleanse" vs "transform" execution phases and splits plans.
"""
from __future__ import annotations

import copy
from typing import Any, Dict, Tuple

def classify_action_phase(action: str) -> str:
    """Classify action as 'cleanse' or 'transform'."""
    act = (action or "").strip().lower()
    cleanse_actions = {
        "trim", "lowercase", "uppercase", "fill_nulls_simple", "fill_or_drop",
        "cast_type", "coerce_numeric", "parse_dates", "sanitize_email",
        "normalize_phone", "range_clip", "clip_or_flag", "flag_outliers",
        "clip_outliers", "cap_outliers", "standardize_boolean", "zero_to_null",
        "deduplicate", "drop_column", "exclude_column", "nullify_future_dates",
        "noop", "drop_rows"
    }
    return "cleanse" if act in cleanse_actions else "transform"

def split_plan_phases(plan: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Splits a single ETL plan into cleanse-only and transform-only plan objects."""
    cleanse_plan = copy.deepcopy(plan)
    transform_plan = copy.deepcopy(plan)

    cleanse_plan["plan_id"] = f"{plan.get('plan_id', 'unknown')}_cleanse"
    transform_plan["plan_id"] = f"{plan.get('plan_id', 'unknown')}_transform"

    # Filter steps in cleanse_plan
    for ds_name, block in cleanse_plan.get("datasets", {}).items():
        if not isinstance(block, dict):
            continue
        steps = block.get("steps") or []
        cleanse_steps = []
        for st in steps:
            if classify_action_phase(st.get("action")) == "cleanse":
                cleanse_steps.append(st)
        # Re-index step order
        for idx, st in enumerate(cleanse_steps):
            st["order"] = idx + 1
        block["steps"] = cleanse_steps

    # Filter steps in transform_plan
    for ds_name, block in transform_plan.get("datasets", {}).items():
        if not isinstance(block, dict):
            continue
        steps = block.get("steps") or []
        transform_steps = []
        for st in steps:
            if classify_action_phase(st.get("action")) == "transform":
                transform_steps.append(st)
        # Re-index step order
        for idx, st in enumerate(transform_steps):
            st["order"] = idx + 1
        block["steps"] = transform_steps

    return cleanse_plan, transform_plan
