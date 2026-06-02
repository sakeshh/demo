from __future__ import annotations

from typing import Any, Dict, List

def compute_etl_readiness(assessment: dict) -> dict:
    """
    Calculate an ETL readiness score and generate structured lists of
    blockers, warnings, and auto-fixable tasks based on data profiling and LLM hints
    using a formal severity engine (HIGH, MEDIUM, LOW).
    """
    blockers = []
    warnings = []
    auto_fixable = []
    score = 100
    
    datasets = assessment.get("datasets") or {}
    dq_issues = assessment.get("data_quality_issues", {})
    dq_datasets = dq_issues.get("datasets") or {}
    
    # 1. Process dataset-level business key confirmations & duplicates
    for ds_name, ds_meta in datasets.items():
        if not isinstance(ds_meta, dict):
            continue
            
        columns = ds_meta.get("columns") or {}
        llm_ds_hints = ds_meta.get("llm_hints") or {}
        dup_info = llm_ds_hints.get("business_key_confirmation") or {}
        if isinstance(dup_info, dict) and dup_info.get("business_key_duplicate_count", 0) > 0:
            cols_involved = dup_info.get("business_key_cols") or []
            blockers.append({
                "dataset": ds_name,
                "column": ", ".join(cols_involved),
                "issue": f"Business key {cols_involved} has {dup_info['business_key_duplicate_count']} duplicate values (case/whitespace insensitive)",
                "severity": "HIGH",
                "issue_type": "business_key_duplicate",
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
            
            # HIGH Blockers: High-importance column with > 30% nulls
            if importance == "high" and null_pct > 0.30:
                blockers.append({
                    "dataset": ds_name,
                    "column": col_name,
                    "issue": f"{null_pct:.0%} nulls in business-critical column '{col_name}'",
                    "severity": "HIGH",
                    "issue_type": "high_null_percentage",
                    "fix": "Investigate source system — data may be missing upstream"
                })
                score -= 20
                
            # MEDIUM Warnings: Mixed date formats
            if len(fmt_variants) > 1:
                warnings.append({
                    "dataset": ds_name,
                    "column": col_name,
                    "issue": f"Mixed date formats detected: {[f['format'] for f in fmt_variants]}",
                    "dominant_format": fmt_variants[0]["format"],
                    "severity": "MEDIUM",
                    "fix": f"Standardize to ISO 8601 using dominant format {fmt_variants[0]['format']}"
                })
                score -= 8
                
            # LOW Auto-fixable: Low/Medium importance with minor nulls
            if importance in ("low", "medium") and 0 < null_pct < 0.10:
                fill_strategy = (hints.get("null_pattern") or {}).get("fill_strategy_hint", "median_or_mode")
                auto_fixable.append({
                    "dataset": ds_name,
                    "column": col_name,
                    "issue": f"{null_pct:.1%} nulls — auto-fill with median/mode",
                    "strategy": fill_strategy,
                    "severity": "LOW"
                })

    # 2. Process data quality issues from the DQ report using formal severity engine
    for ds_name, dq_block in dq_datasets.items():
        for issue in dq_block.get("issues", []):
            issue_type = str(issue.get("type") or "").strip().lower()
            col = issue.get("column") or ""
            sev = str(issue.get("severity") or "medium").strip().lower()
            msg = str(issue.get("message") or "")
            
            # Classify severity and map warnings/blockers
            if sev == "high":
                # Ensure we don't add duplicate blockers
                if not any(b["dataset"] == ds_name and b["column"] == col and b["issue"] == msg for b in blockers):
                    blockers.append({
                        "dataset": ds_name,
                        "column": col,
                        "issue": msg,
                        "severity": "HIGH",
                        "issue_type": issue_type,
                        "fix": f"Apply constraint or filter: {issue_type}"
                    })
                    score -= 15
            elif sev == "medium" or issue_type in ("punctuation_only_value", "case_inconsistency", "invalid_email", "invalid_phone", "invalid_date_format"):
                # Deduct points for medium severity issues (null email, null city, null name, punctuation, duplicates)
                if not any(w["dataset"] == ds_name and w["column"] == col and w["issue"] == msg for w in warnings):
                    warnings.append({
                        "dataset": ds_name,
                        "column": col,
                        "issue": msg,
                        "severity": "MEDIUM",
                        "fix": f"Clean and standardize: {issue_type}"
                    })
                    score -= 8
            else: # Low severity
                if not any(a["dataset"] == ds_name and a["column"] == col and a["issue"] == msg for a in auto_fixable):
                    auto_fixable.append({
                        "dataset": ds_name,
                        "column": col,
                        "issue": msg,
                        "severity": "LOW",
                        "strategy": "auto_clean"
                    })
                    score -= 2

    # Global issues check
    global_issues = dq_issues.get("global_issues", {})
    for orphan in global_issues.get("orphan_foreign_keys", []):
        msg = f"Orphan foreign keys: {orphan.get('from')} -> {orphan.get('to')}"
        if not any(b["issue"] == msg for b in blockers):
            blockers.append({
                "dataset": "global",
                "column": orphan.get("from"),
                "issue": msg,
                "severity": "HIGH",
                "issue_type": "orphan_foreign_keys",
                "fix": "Set fk_integrity_action: reject_orphans / null_fill_fk / create_unknown_dim_record"
            })
            score -= 15

    # Governance: semantic confidence, drift, reconciliation, cross-table style signals
    sem_pkg = assessment.get("semantic_context") or {}
    try:
        overall_conf = float(sem_pkg.get("overall_semantic_confidence") or 1.0)
    except (TypeError, ValueError):
        overall_conf = 1.0
    if overall_conf < 0.55:
        warnings.append({
            "dataset": "global",
            "column": "",
            "issue": f"Low overall semantic confidence ({overall_conf:.2f}); validate glossary/metadata manifest.",
            "severity": "MEDIUM",
            "fix": "Provide business notes or config/metadata_manifest.yaml for critical columns.",
        })
        score -= 6

    drift_pkg = assessment.get("drift") or {}
    for ds_name, dblock in (drift_pkg.get("by_dataset") or {}).items():
        if not isinstance(dblock, dict):
            continue
        sev = str(dblock.get("severity") or "").lower()
        if sev == "high":
            warnings.append({
                "dataset": str(ds_name),
                "column": "",
                "issue": "High drift vs last profile snapshot (row/schema/null/distinct shifts).",
                "severity": "MEDIUM",
                "fix": "Compare with prior baseline; confirm upstream changes are expected.",
            })
            score -= 10
        elif sev == "medium":
            warnings.append({
                "dataset": str(ds_name),
                "column": "",
                "issue": "Moderate drift detected vs last profile snapshot.",
                "severity": "MEDIUM",
                "fix": "Review drift signals in the governance section of the report.",
            })
            score -= 5

    rec_pkg = assessment.get("reconciliation") or {}
    for ds_name, rec in (rec_pkg.get("by_dataset") or {}).items():
        if isinstance(rec, dict) and rec.get("balanced") is False:
            blockers.append({
                "dataset": str(ds_name),
                "column": "",
                "issue": "Reconciliation stages do not balance (possible row loss or skipped parsing).",
                "severity": "HIGH",
                "issue_type": "reconciliation_imbalance",
                "fix": "Inspect parse failures and filtered counts; align source-to-target accounting.",
            })
            score -= 12

    for u in assessment.get("unified_issues") or []:
        if not isinstance(u, dict):
            continue
        if u.get("source") != "gx":
            continue
        if str(u.get("business_criticality") or "").lower() != "high":
            continue
        msg = str(u.get("message") or "GX validation failure")
        if not any(w.get("issue") == msg for w in warnings):
            warnings.append({
                "dataset": str(u.get("dataset") or ""),
                "column": str(u.get("column") or ""),
                "issue": msg,
                "severity": "MEDIUM",
                "fix": "Review GX expectation failures on business-critical columns.",
            })
            score -= 4

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
