"""
LLM Recommendation Mapper.
Translates LLM-generated recommendations to standard ETL actions.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional


def map_llm_recommendation_to_action(rec: Dict[str, Any]) -> Optional[str]:
    """
    Maps an LLM recommendation's suggested_fix or mapped_action to a standard ETL action.
    Returns: action string or 'noop' if unmappable.
    """
    action = rec.get("mapped_action")
    if action and isinstance(action, str):
        action = action.strip().lower()
        known_actions = {
            "trim", "fill_nulls_simple", "cast_type", "regex_replace",
            "deduplicate", "parse_dates", "sanitize_email", "normalize_phone",
            "clip_or_flag", "flag_outliers", "zero_to_null", "lowercase",
            "uppercase", "exclude_column", "drop_column", "noop"
        }
        if action in known_actions:
            return action

    # Fallback keyword matching on suggested_fix
    import re
    fix_text = str(rec.get("suggested_fix") or "").lower()
    
    # Check lowercase/uppercase first to avoid "convert to lowercase" matching "convert" -> cast_type
    if "lowercase" in fix_text or "lower case" in fix_text:
        return "lowercase"
    if "uppercase" in fix_text or "upper case" in fix_text:
        return "uppercase"

    if "trim" in fix_text or "whitespace" in fix_text or "strip" in fix_text:
        return "trim"
    if "fill" in fix_text or "impute" in fix_text or "null" in fix_text:
        return "fill_nulls_simple"
    if re.search(r"\bdate\b", fix_text) or "parse" in fix_text or "format" in fix_text:
        return "parse_dates"
    if "email" in fix_text:
        return "sanitize_email"
    if "phone" in fix_text or "mobile" in fix_text:
        return "normalize_phone"
    if "duplicate" in fix_text:
        return "deduplicate"
    if "outlier" in fix_text or "skew" in fix_text:
        return "flag_outliers"
    if "cast" in fix_text or "convert" in fix_text:
        return "cast_type"
    if "drop" in fix_text or "remove" in fix_text:
        return "drop_column"

    return "noop"


def compute_llm_confidence(rec: Dict[str, Any]) -> float:
    """
    Computes a confidence score [0.0 - 1.0] for the LLM recommendation.
    Derived from severity, specificity of suggestion, and existence of examples.
    """
    severity = str(rec.get("severity") or "medium").lower().strip()
    base_conf = 0.50
    if severity == "high":
        base_conf = 0.80
    elif severity == "medium":
        base_conf = 0.65

    boost = 0.0
    if rec.get("suggested_fix"):
        boost += 0.05
    if rec.get("example_sql") or rec.get("example_pandas"):
        boost += 0.10

    mapped_action = rec.get("mapped_action") or ""
    if not mapped_action or mapped_action == "noop":
        base_conf = 0.10
        boost = 0.0

    return min(1.0, base_conf + boost)
