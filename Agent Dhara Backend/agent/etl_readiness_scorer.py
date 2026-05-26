from __future__ import annotations

from typing import Any, Dict, List

def compute_etl_readiness(assessment: dict) -> dict:
    """
    Calculate an ETL readiness score and generate structured lists of
    blockers, warnings, and auto-fixable tasks based on data profiling and LLM hints.
    """
    blockers = []
    warnings = []
    auto_fixable = []
    score = 100
    
    datasets = assessment.get("datasets") or {}
    for ds_name, ds_meta in datasets.items():
        if not isinstance(ds_meta, dict):
            continue
            
        columns = ds_meta.get("columns") or {}
        # Check dataset-level business key confirmations
        llm_ds_hints = ds_meta.get("llm_hints") or {}
        dup_info = llm_ds_hints.get("business_key_confirmation") or {}
        if isinstance(dup_info, dict) and dup_info.get("business_key_duplicate_count", 0) > 0:
            cols_involved = dup_info.get("business_key_cols") or []
            blockers.append({
                "dataset": ds_name,
                "column": ", ".join(cols_involved),
                "issue": f"Business key {cols_involved} has {dup_info['business_key_duplicate_count']} duplicates",
                "fix": "Define dedup strategy: keep_first / keep_last in business rules"
            })
            score -= 15

        for col_name, col in columns.items():
            if not isinstance(col, dict):
                continue
                
            hints = col.get("llm_hints") or {}
            importance = str(hints.get("business_importance") or "low").lower().strip()
            null_pct = col.get("null_percentage") or col.get("null_pct") or 0.0
            
            # Format variants
            fmt_variants = hints.get("format_variants") or []
            
            # BLOCKER: High-importance column with > 30% nulls
            if importance == "high" and null_pct > 0.30:
                blockers.append({
                    "dataset": ds_name,
                    "column": col_name,
                    "issue": f"{null_pct:.0%} nulls in business-critical column '{col_name}'",
                    "fix": "Investigate source system — data may be missing upstream"
                })
                score -= 20
                
            # WARNING: Mixed date formats
            if len(fmt_variants) > 1:
                warnings.append({
                    "dataset": ds_name,
                    "column": col_name,
                    "issue": f"Mixed date formats detected: {[f['format'] for f in fmt_variants]}",
                    "dominant_format": fmt_variants[0]["format"],
                    "fix": f"Standardize to ISO 8601 using dominant format {fmt_variants[0]['format']}"
                })
                score -= 5
                
            # AUTO-FIXABLE: Low/Medium importance with minor nulls
            if importance in ("low", "medium") and 0 < null_pct < 0.10:
                fill_strategy = (hints.get("null_pattern") or {}).get("fill_strategy_hint", "median_or_mode")
                auto_fixable.append({
                    "dataset": ds_name,
                    "column": col_name,
                    "issue": f"{null_pct:.1%} nulls — auto-fill with median/mode",
                    "strategy": fill_strategy
                })
                
    return {
        "score": max(0, score),
        "grade": "A" if score >= 90 else "B" if score >= 75 else "C" if score >= 50 else "F",
        "blockers": blockers,
        "warnings": warnings,
        "auto_fixable": auto_fixable,
        "etl_recommendation": (
            "Ready for ETL generation" if not blockers
            else f"Fix {len(blockers)} blocker(s) before generating ETL"
        )
    }
