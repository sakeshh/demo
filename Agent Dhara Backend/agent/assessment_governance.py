from __future__ import annotations

import hashlib
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import pandas as pd

from agent.cross_field_rules import evaluate_cross_field_rules, load_cross_field_rules
from agent.drift_detector import compare_snapshots
from agent.gx_issue_mapper import map_gx_to_unified_issues
from agent.metadata_registry import (
    load_metadata_manifest,
    manifest_hash,
    resolve_dataset_manifest,
    validate_manifest_against_schema,
)
from agent.profile_snapshot_store import build_profile_fingerprint, load_latest_snapshot, save_snapshot
from agent.raw_payload_registry import empty_registry
from agent.reconciliation_tracker import build_reconciliation_from_profile, merge_reconciliations
from agent.semantic_context_builder import build_all_semantic_contexts

logger = logging.getLogger(__name__)


def _schema_hash(assessment: Dict[str, Any]) -> str:
    parts: List[str] = []
    for ds_name in sorted((assessment.get("datasets") or {}).keys()):
        parts.append(f"ds:{ds_name}")
        cols = (assessment.get("datasets") or {}).get(ds_name, {}).get("columns") or {}
        for col_name in sorted(cols.keys(), key=lambda x: str(x).lower()):
            c = cols.get(col_name) or {}
            parts.append(f"col:{col_name}|{c.get('dtype')}")
    return hashlib.sha256("\n".join(parts).encode("utf-8", errors="ignore")).hexdigest()[:16]


def _parse_failures_estimate(ds_meta: Dict[str, Any]) -> int:
    cols = ds_meta.get("columns") or {}
    n = 0
    if not isinstance(cols, dict):
        return 0
    total_rows = int(ds_meta.get("row_count") or 0)
    for c in cols.values():
        if not isinstance(c, dict):
            continue
        if c.get("dtype_inference") == "unparseable" or c.get("parse_failure_ratio"):
            try:
                ratio = float(c.get("parse_failure_ratio") or 0)
                n += int(ratio * total_rows) if total_rows else 0
            except (TypeError, ValueError):
                pass
    return n


def enrich_assessment_with_governance(
    assessment: Dict[str, Any],
    datasets: Optional[Dict[str, pd.DataFrame]] = None,
    *,
    job_id: Optional[str] = None,
    business_rules: Optional[Dict[str, Any]] = None,
    run_gx: Optional[bool] = None,
) -> Dict[str, Any]:
    """
    Post-process an assessment dict: semantic context, manifest versioning, drift,
    reconciliation, cross-field rules, optional GX + unified issues.
    Mutates assessment in place and returns it.
    """
    if not isinstance(assessment, dict) or not assessment.get("datasets"):
        return assessment

    datasets = datasets or {}
    business_rules = business_rules or {}
    notes = str(business_rules.get("notes") or "")[:4000]
    prior = business_rules.get("prior_report_hints") or business_rules.get("report_hints")

    manifest = load_metadata_manifest()
    m_hash = manifest_hash(manifest)
    gloss_hash = hashlib.sha256(json.dumps(manifest.get("datasets") or {}, sort_keys=True, default=str).encode()).hexdigest()[:16]
    schema_h = _schema_hash(assessment)

    assessment.setdefault("governance", {})
    gov = assessment["governance"]
    if not isinstance(gov, dict):
        gov = {}
        assessment["governance"] = gov
    gov.update(
        {
            "manifest_version": str(manifest.get("version") or "0"),
            "manifest_hash": m_hash,
            "glossary_hash": gloss_hash,
            "schema_hash": schema_h,
            "profile_version": "1",
            "run_timestamp": datetime.now(timezone.utc).isoformat(),
        }
    )

    assessment.setdefault("raw_payload_registry", empty_registry())

    # Semantic contexts
    sem_pkg = build_all_semantic_contexts(
        assessment,
        sample_by_dataset=datasets,
        manifest=manifest,
        user_notes=notes,
        prior_hints=prior if isinstance(prior, dict) else None,
    )
    assessment["semantic_context"] = sem_pkg

    # Per-dataset manifest errors
    for ds_name, ds_meta in (assessment.get("datasets") or {}).items():
        if not isinstance(ds_meta, dict):
            continue
        entry, _matched = resolve_dataset_manifest(str(ds_name), manifest)
        cols = list((ds_meta.get("columns") or {}).keys())
        if entry:
            errs = validate_manifest_against_schema(entry, cols)
            if errs:
                ds_meta.setdefault("manifest_validation_errors", errs)
                dq = (assessment.setdefault("data_quality_issues", {}).setdefault("datasets", {}))
                block = dq.setdefault(str(ds_name), {"issues": [], "summary": {"issue_count": 0, "high_severity": 0, "medium_severity": 0, "low_severity": 0}})
                for e in errs[:20]:
                    block["issues"].append(
                        {
                            "type": "metadata_manifest_mismatch",
                            "severity": "medium",
                            "column": "",
                            "count": 1,
                            "message": e,
                            "recommendation": "Update config/metadata_manifest.yaml to match the data.",
                        }
                    )
                summ = block.setdefault(
                    "summary",
                    {"issue_count": 0, "high_severity": 0, "medium_severity": 0, "low_severity": 0},
                )
                summ["issue_count"] = len(block["issues"])
                summ["high_severity"] = sum(1 for i in block["issues"] if str(i.get("severity")).lower() == "high")
                summ["medium_severity"] = sum(1 for i in block["issues"] if str(i.get("severity")).lower() == "medium")
                summ["low_severity"] = sum(1 for i in block["issues"] if str(i.get("severity")).lower() == "low")

    # Reconciliation + drift
    recon_items: List[Dict[str, Any]] = []
    drift_by: Dict[str, Any] = {}
    for ds_name, ds_meta in (assessment.get("datasets") or {}).items():
        if not isinstance(ds_meta, dict):
            continue
        rc = int(ds_meta.get("row_count") or 0)
        pf = _parse_failures_estimate(ds_meta)
        recon_items.append(build_reconciliation_from_profile(str(ds_name), rc, parse_failures=pf))
        fp = build_profile_fingerprint(ds_meta)
        prev = load_latest_snapshot(str(ds_name))
        drift = compare_snapshots(prev, fp)
        drift_by[str(ds_name)] = drift
        try:
            save_snapshot(str(ds_name), fp, run_id=job_id or gov.get("run_timestamp", "run"))
        except Exception as ex:
            logger.debug("snapshot skip: %s", ex)

    assessment["reconciliation"] = merge_reconciliations(recon_items)
    assessment["drift"] = {"by_dataset": drift_by}

    # Cross-field rules
    rules = load_cross_field_rules()
    dq = assessment.setdefault("data_quality_issues", {}).setdefault("datasets", {})
    for ds_name, df in datasets.items():
        if not isinstance(df, pd.DataFrame) or df.empty:
            continue
        extra = evaluate_cross_field_rules(str(ds_name), df, rules)
        if not extra:
            continue
        block = dq.setdefault(str(ds_name), {"issues": [], "summary": {"issue_count": 0, "high_severity": 0, "medium_severity": 0, "low_severity": 0}})
        block.setdefault("issues", []).extend(extra)
        summ = block.setdefault("summary", {"issue_count": 0, "high_severity": 0, "medium_severity": 0, "low_severity": 0})
        summ["issue_count"] = len(block["issues"])
        summ["high_severity"] = sum(1 for i in block["issues"] if str(i.get("severity")).lower() == "high")
        summ["medium_severity"] = sum(1 for i in block["issues"] if str(i.get("severity")).lower() == "medium")
        summ["low_severity"] = sum(1 for i in block["issues"] if str(i.get("severity")).lower() == "low")

    # Optional GX
    if run_gx is None:
        run_gx = os.getenv("DHARA_RUN_GX", "").strip().lower() in ("1", "true", "yes")
    gx_results: Dict[str, Any] = {}
    if run_gx and datasets:
        try:
            from agent.specialists.gx_validation_specialist import run_gx_validation

            gx_results = run_gx_validation(datasets, assessment) or {}
        except Exception as e:
            logger.warning("GX run skipped: %s", e)
            gx_results = {"_error": str(e)}
    assessment["gx_results"] = gx_results

    unified = map_gx_to_unified_issues(
        gx_results if isinstance(gx_results, dict) else {},
        semantic_by_dataset=(sem_pkg.get("by_dataset") or {}),
        drift_by_dataset=drift_by,
        reconciliation=assessment.get("reconciliation"),
    )
    assessment["unified_issues"] = unified

    # ETL hints for planner/codegen
    assessment.setdefault("enriched_etl_context", {})
    ee = assessment["enriched_etl_context"]
    if isinstance(ee, dict):
        ee.update(
            {
                "semantic_overall_confidence": sem_pkg.get("overall_semantic_confidence"),
                "drift_summary": {k: v.get("severity") for k, v in drift_by.items() if isinstance(v, dict)},
                "reconciliation_ok": all(
                    (r.get("balanced") is not False) for r in (assessment.get("reconciliation") or {}).get("by_dataset", {}).values()
                ),
                "gx_evaluated": bool(gx_results) and "_error" not in gx_results,
            }
        )

    try:
        from agent.etl_readiness_scorer import compute_etl_readiness

        assessment["etl_readiness"] = compute_etl_readiness(assessment)
    except Exception:
        pass

    return assessment
