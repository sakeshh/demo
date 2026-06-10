"""
DQ Gate: Calculates dataset-level data quality scores and determines if they pass the Phase 2 transformations threshold.
"""
from __future__ import annotations

from typing import Any, Dict

def calculate_dataset_dq_score(assessment: Dict[str, Any], ds_name: str) -> Dict[str, Any]:
    """
    Calculates a DQ Score (0-100) using weighted metrics:
    - Null Rate: 30%
    - Type Mismatches: 30%
    - Duplicates: 20%
    - Outliers: 20%
    """
    ds_info = (assessment or {}).get("datasets", {}).get(ds_name, {})
    columns = ds_info.get("columns") or {}
    
    # 1. Null Score (30%)
    null_score = 100.0
    if columns:
        null_pcts = []
        for col in columns.values():
            if isinstance(col, dict):
                null_pcts.append(col.get("null_percentage") or col.get("null_pct") or 0.0)
        if null_pcts:
            avg_null = sum(null_pcts) / len(null_pcts)
            # Quadratic penalty: high null rates are penalized more aggressively
            null_score = max(0.0, 100.0 * ((1.0 - avg_null) ** 2))

    # 2. Type Mismatch / Format Score (30%)
    type_score = 100.0
    # Quality issues: check canonical path (datasets.{name}.quality.issues)
    # and legacy path (data_quality_issues.datasets.{name}.issues)
    dq_issues = list((ds_info.get("quality") or {}).get("issues") or [])
    legacy_issues = (assessment or {}).get("data_quality_issues", {}).get("datasets", {}).get(ds_name, {}).get("issues", [])
    if legacy_issues:
        dq_issues.extend(legacy_issues)
    type_mismatches = 0
    for issue in dq_issues:
        issue_type = str(issue.get("type") or "").strip().lower()
        if issue_type in ("type_mismatch", "invalid_date_format", "invalid_email", "invalid_phone"):
            type_mismatches += 1
    type_score = max(0.0, 100.0 - (type_mismatches * 10.0))

    # 3. Duplicate Score (20%)
    dup_score = 100.0
    llm_ds_hints = ds_info.get("llm_hints") or {}
    dup_info = llm_ds_hints.get("business_key_confirmation") or {}
    dup_count = 0
    if isinstance(dup_info, dict):
        dup_count = dup_info.get("business_key_duplicate_count", 0)
    # Also scan quality issues for duplicates
    for issue in dq_issues:
        issue_type = str(issue.get("type") or "").strip().lower()
        if "duplicate" in issue_type or "dup" in issue_type:
            dup_count += 1
    dup_score = max(0.0, 100.0 - (dup_count * 5.0))

    # 4. Outlier Score (20%)
    outlier_score = 100.0
    outliers_count = 0
    for issue in dq_issues:
        issue_type = str(issue.get("type") or "").strip().lower()
        if "outlier" in issue_type:
            outliers_count += 1
    outlier_score = max(0.0, 100.0 - (outliers_count * 10.0))

    # Weighted DQ Score
    dq_score = (0.30 * null_score) + (0.30 * type_score) + (0.20 * dup_score) + (0.20 * outlier_score)
    if null_score < 10.0:
        dq_score = max(0.0, dq_score - 15.0)
    
    return {
        "score": round(dq_score, 2),
        "details": {
            "null_score": round(null_score, 2),
            "type_score": round(type_score, 2),
            "duplicate_score": round(dup_score, 2),
            "outlier_score": round(outlier_score, 2)
        }
    }

def check_dq_gate(
    assessment: Dict[str, Any],
    ds_name: str,
    threshold: float = 70.0,
    force_unlock: bool = False,
    sem_schema: Dict[str, Any] = None,
) -> Dict[str, Any]:
    """Determines if a dataset passes the DQ gate for Phase 2 transformations."""
    res = calculate_dataset_dq_score(assessment, ds_name)
    score = res["score"]
    
    # Check for high-PII columns belonging to this dataset in semantic schema
    has_high_pii = False
    if sem_schema:
        for key, desc in sem_schema.items():
            if key.startswith(f"{ds_name}.") and isinstance(desc, dict) and desc.get("pii_level") == "high":
                has_high_pii = True
                break
                
    effective_threshold = min(threshold + 15.0, 95.0) if has_high_pii else threshold
    passed = score >= effective_threshold or force_unlock
    
    return {
        "passed": passed,
        "score": score,
        "threshold": effective_threshold,
        "force_unlocked": force_unlock,
        "details": res["details"],
        "has_high_pii": has_high_pii,
    }
