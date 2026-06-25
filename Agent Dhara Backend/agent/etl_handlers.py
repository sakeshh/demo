from __future__ import annotations

import json
import logging
import os
import re
import time
from typing import Any, Dict, List, Optional

from agent.business_rules_loader import (
    list_tenant_ids,
    merge_business_rules_for_datasets,
    pending_rules_from_session,
    tenant_id_from_session,
)
from agent.session_store import load_session, save_session
from agent.etl_pipeline import (
    build_etl_plan,
    build_impact_preview,
    generate_python_etl,
    normalize_business_rules,
)
from agent.etl_pipeline.llm_codegen import (
    generate_adf_with_llm,
    generate_etl_with_llm,
    is_llm_generation_error,
    parse_adf_json_from_llm,
)
from agent.etl_pipeline.schema_lineage import build_lineage
from agent.etl_pipeline.validate_plan import validate_etl_plan, validate_etl_plan_for_confirm
from agent.etl_pipeline.validate_python import validate_etl_python_source, validate_python_source
from agent.etl_pipeline.validate_pyspark import validate_pyspark_source
from agent.etl_pipeline.source_context import build_source_context
from agent.etl_pipeline.connector_manifest import build_connector_manifest
from agent.etl_pipeline.plan_narrator import narrate_plan
from agent.etl_pipeline.manual_review_promote import (
    apply_manual_resolutions,
    count_pending_manual_review,
    enrich_plan_manual_review,
)
from agent.etl_pipeline.agentic_rules import analyze_agentic_intent

logger = logging.getLogger("agent.etl")


def _collect_etl_preview_datasets(ctx: Dict[str, Any], assess: Dict[str, Any]) -> tuple[Dict[str, Any], str]:
    """Return (dataset name -> DataFrame, debug_msg) for optional DuckDB preview (session or assessment)."""
    import pandas as pd

    out: Dict[str, Any] = {}
    raw = ctx.get("etl_preview_datasets")
    if isinstance(raw, dict):
        for k, v in raw.items():
            if isinstance(v, pd.DataFrame):
                out[str(k)] = v
    if out:
        return out, "loaded from ctx.etl_preview_datasets"
    ep = assess.get("etl_preview_input") if isinstance(assess, dict) else None
    if isinstance(ep, dict):
        d = ep.get("datasets")
        if isinstance(d, dict):
            for k, v in d.items():
                if isinstance(v, pd.DataFrame):
                    out[str(k)] = v
    if out:
        return out, "loaded from assess.etl_preview_input"

    debug_parts = []
    # Dynamic loading fallback if not already in memory
    if assess and isinstance(assess, dict) and assess.get("datasets"):
        import os
        import json
        from agent.master_agent import load_sources_config

        selected = list((assess.get("datasets") or {}).keys())
        sources_path = ctx.get("sources_path") or "config/sources.yaml"
        debug_parts.append(f"sources_path={sources_path}")
        debug_parts.append(f"selected={selected}")
        
        try:
            source_root = load_sources_config(sources_path)
            debug_parts.append(f"locations={len(source_root.get('locations', []))}")
        except Exception as exc:
            source_root = {}
            debug_parts.append(f"config_err={exc}")
        
        try:
            max_rows = int(os.getenv("DHARA_DUCKDB_SAMPLE_ROWS", "5000"))
        except ValueError:
            max_rows = 5000

        locations = source_root.get("locations") or []
        for loc in locations:
            typ = str(loc.get("type") or "").lower()
            if typ == "database":
                conn_cfg = loc.get("connection", {}) or {}
                try:
                    from connectors.azure_sql_pythonnet import AzureSQLPythonNetConnector
                    conn = AzureSQLPythonNetConnector(conn_cfg)
                    discovered = conn.discover_tables()
                    for t in selected:
                        try:
                            # Database tables might have prefixes or be exact match
                            if t in discovered:
                                out[t] = conn.load_table(t, max_rows=max_rows)
                                debug_parts.append(f"loaded_db_{t}")
                            else:
                                # Try stripping prefix
                                matched = False
                                for real_t in discovered:
                                    if t.endswith(real_t):
                                        out[t] = conn.load_table(real_t, max_rows=max_rows)
                                        debug_parts.append(f"loaded_db_suffix_{t}")
                                        matched = True
                                        break
                                if not matched:
                                    debug_parts.append(f"db_no_match_{t}")
                        except Exception as tbl_err:
                            debug_parts.append(f"db_tbl_err_{t}={tbl_err}")
                except Exception as db_err:
                    debug_parts.append(f"db_conn_err={db_err}")
            elif typ == "filesystem":
                fp = loc.get("path")
                if fp and os.path.isdir(fp):
                    for t in selected:
                        p = os.path.join(fp, t)
                        if os.path.isfile(p):
                            low = p.lower()
                            try:
                                if low.endswith(".csv"):
                                    out[t] = pd.read_csv(p, nrows=max_rows, low_memory=False)
                                elif low.endswith(".tsv"):
                                    out[t] = pd.read_csv(p, sep="\t", nrows=max_rows, low_memory=False)
                                elif low.endswith(".jsonl"):
                                    rows = []
                                    with open(p, "r", encoding="utf-8") as f:
                                        for line in f:
                                            line = line.strip()
                                            if not line:
                                                continue
                                            try:
                                                rows.append(json.loads(line))
                                            except Exception:
                                                pass
                                            if len(rows) >= max_rows:
                                                break
                                    out[t] = pd.json_normalize(rows, max_level=1) if rows else pd.DataFrame()
                                elif low.endswith((".xlsx", ".xls")):
                                    out[t] = pd.read_excel(p, nrows=max_rows)
                                elif low.endswith(".parquet"):
                                    out[t] = pd.read_parquet(p).head(max_rows)
                                debug_parts.append(f"loaded_fs_{t}")
                            except Exception as fs_err:
                                debug_parts.append(f"fs_err_{t}={fs_err}")
                        else:
                            debug_parts.append(f"fs_file_not_found_{t}")
            elif typ == "azure_blob":
                conn_cfg = loc.get("connection", {}) or {}
                try:
                    from connectors.azure_blob_storage import AzureBlobStorageConnector
                    conn = AzureBlobStorageConnector(conn_cfg)
                    discovered = conn.list_blobs()
                    for t in selected:
                        if t in discovered:
                            try:
                                loaded = conn.load_all_blobs(folder_prefix="", blobs=[t], max_rows=max_rows)
                                if loaded and t in loaded:
                                    out[t] = loaded[t]
                                    debug_parts.append(f"loaded_blob_{t}")
                                else:
                                    debug_parts.append(f"blob_empty_{t}")
                            except Exception as blob_err:
                                debug_parts.append(f"blob_err_{t}={blob_err}")
                        else:
                            debug_parts.append(f"blob_not_discovered_{t}")
                except Exception as blob_conn_err:
                    debug_parts.append(f"blob_conn_err={blob_conn_err}")
    else:
        debug_parts.append("assess_datasets_missing")

    return out, ", ".join(debug_parts) if debug_parts else "empty_fallback"


def _maybe_build_etl_duckdb_diff(
    *,
    eng: str,
    code: str,
    ok: bool,
    ctx: Dict[str, Any],
    assess: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """
    After SQL output: optional DuckDB preview + frame diff when preview frames exist.

    Enable with ``DHARA_ETL_DUCKDB_DIFF=1`` and/or ``etl_preview_input.preview_sql`` /
    ``DHARA_ETL_DUCKDB_PREVIEW_SQL``, or ``DHARA_ETL_DUCKDB_AUTO_EXTRACT=1`` to try the first SELECT.
    """
    if eng not in ("sql", "tsql", "ansi"):
        return None
    if not ok or not (code or "").strip():
        return None
    dfs, debug_msg = _collect_etl_preview_datasets(ctx, assess)
    if not dfs:
        return {"skipped": True, "reason": f"no_preview_datasets. Debug info: {debug_msg}"}
    env_on = os.getenv("DHARA_ETL_DUCKDB_DIFF", "").strip().lower() in ("1", "true", "yes")
    auto_ex = os.getenv("DHARA_ETL_DUCKDB_AUTO_EXTRACT", "").strip().lower() in ("1", "true", "yes")
    ep = assess.get("etl_preview_input") if isinstance(assess, dict) else {}
    ep = ep if isinstance(ep, dict) else {}
    preview_sql = str(ep.get("preview_sql") or os.getenv("DHARA_ETL_DUCKDB_PREVIEW_SQL", "") or "").strip()
    if not (env_on or preview_sql or auto_ex):
        return {"skipped": True, "reason": "duckdb_diff_not_enabled"}
    from agent.etl_preview_wiring import build_duckdb_sql_preview_diff

    before_ds = ep.get("before_dataset_name")
    before_ds_s = str(before_ds).strip() if before_ds else None
    try:
        return build_duckdb_sql_preview_diff(
            code,
            dfs,
            preview_sql=preview_sql or None,
            before_dataset_name=before_ds_s,
        )
    except Exception as exc:
        logger.warning("etl duckdb preview/diff failed: %s", exc)
        return {"skipped": True, "reason": str(exc)[:300]}


def _resolve_codegen_mode(
    engine: str,
    *,
    requested: Optional[str] = None,
) -> str:
    """
    template | llm | llm_then_template
    Resolution order: explicit API `codegen_mode`, then env ETL_CODEGEN_MODE, then:
    - default **template** (fast, deterministic)
    - set ETL_CODEGEN_LLM_DEFAULT=1 to restore **llm_then_template** for python/sql/adf when no API mode is sent.
    PySpark still honors DHARA_ETL_FAST_PYSPARK=1 under ETL_CODEGEN_LLM_DEFAULT=1.
    """
    if requested and str(requested).strip().lower() in ("template", "llm", "llm_then_template"):
        return str(requested).strip().lower()
    env = os.getenv("ETL_CODEGEN_MODE", "").strip().lower()
    if env in ("template", "llm", "llm_then_template"):
        return env
    # Fast default: deterministic template codegen. Opt in to LLM paths via ETL_CODEGEN_MODE or
    # ETL_CODEGEN_LLM_DEFAULT=1 (restores previous llm_then_template default for python/sql/adf).
    if os.getenv("ETL_CODEGEN_LLM_DEFAULT", "0").strip().lower() in ("1", "true", "yes"):
        eng = (engine or "python").lower()
        if eng in ("spark", "pyspark"):
            fast = os.getenv("DHARA_ETL_FAST_PYSPARK", "1").strip().lower() in ("1", "true", "yes")
            if fast:
                return "template"
        return "llm_then_template"
    return "template"


# ── Phase state machine ───────────────────────────────────────────────────────

ETL_PHASES = [
    "planned",
    "preview_ready",
    "approved",
    "generating",
    "validated",
    "code_ready",
    "downloadable",
    "failed",
]

ALLOWED_TRANSITIONS: Dict[str, List[str]] = {
    "planned": ["preview_ready", "failed"],
    "preview_ready": ["approved", "failed", "planned"],
    "approved": ["generating", "failed", "planned"],
    "generating": ["validated", "failed", "planned"],
    "validated": ["code_ready", "failed", "planned", "generating"],
    "code_ready": ["downloadable", "failed", "planned", "generating"],
    "failed": ["planned"],
    "downloadable": ["planned", "generating"],
}

_LEGACY_PHASE_MAP = {
    "no_plan": "planned",
    "plan_built": "planned",
    "plan_validated": "preview_ready",
    "preview_shown": "preview_ready",
    "code_failed": "failed",
}


def _migrate_phase(flow: dict) -> None:
    current = flow.get("phase")
    if current in _LEGACY_PHASE_MAP:
        flow["phase"] = _LEGACY_PHASE_MAP[current]


def _can_transition(from_phase: str, to_phase: str) -> bool:
    _migrate_phase({"phase": from_phase})
    from_phase = _LEGACY_PHASE_MAP.get(from_phase, from_phase)
    if from_phase == to_phase:
        return True
    return to_phase in ALLOWED_TRANSITIONS.get(from_phase, [])


def _transition(flow: dict, to_phase: str, *, by: str = "system", reason: str = "") -> None:
    if to_phase not in ETL_PHASES:
        raise ValueError(f"Unknown phase: {to_phase}")
    _migrate_phase(flow)
    from_phase = flow.get("phase") or "planned"
    if from_phase not in ETL_PHASES:
        from_phase = _LEGACY_PHASE_MAP.get(from_phase, "planned")
        flow["phase"] = from_phase
    if not _can_transition(from_phase, to_phase):
        raise ValueError(f"Invalid ETL phase transition: {from_phase} -> {to_phase}")
    history = flow.setdefault("phase_history", [])
    history.append(
        {
            "from": from_phase,
            "to": to_phase,
            "ts": time.time(),
            "by": by,
            "reason": reason,
        }
    )
    flow["phase"] = to_phase


def rollback_on_failure(flow: dict, *, reason: str = "") -> None:
    """Reset flow to planned while preserving plan, assessment context, and history."""
    flow["failure_reason"] = reason
    flow["last_failure_reason"] = reason
    try:
        _transition(flow, "failed", by="system", reason=reason)
    except ValueError:
        flow["phase"] = "failed"
    flow["approved_plan"] = None
    flow["validation_ok"] = False
    try:
        _transition(flow, "planned", by="system", reason="rollback_on_failure")
    except ValueError:
        flow["phase"] = "planned"


def _plan_all_auto(plan: Dict[str, Any]) -> bool:
    for block in (plan.get("datasets") or {}).values():
        for st in (block or {}).get("steps") or []:
            if str(st.get("classification") or st.get("bucket") or "auto").lower() != "auto":
                return False
            if st.get("requires_user_choice"):
                return False
    if plan.get("blocked"):
        return False
    if count_pending_manual_review(plan) > 0:
        return False
    return True


def _invariants_pass(plan: Dict[str, Any]) -> bool:
    inv = plan.get("invariants") or []
    for item in inv:
        if item.get("enabled") and item.get("name") == "never_drop_rows":
            rules = plan.get("business_rules") or {}
            if not rules.get("never_drop_rows"):
                return False
    return True


def _ctx(session: Dict[str, Any]) -> Dict[str, Any]:
    return session.setdefault("context", {})


def _get_assessment(session: Dict[str, Any], override: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if isinstance(override, dict) and override.get("datasets"):
        return override
    raw = (_ctx(session) or {}).get("last_assessment_result")
    return raw if isinstance(raw, dict) and raw.get("datasets") else None


def _safe_segment(s: str) -> str:
    t = re.sub(r"[^a-zA-Z0-9_-]+", "_", (s or "default").strip())[:80]
    return t or "default"


def _rehydrate_plan(plan: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    """Restore session-owned fields stripped by UI plan edits."""
    out = dict(plan)
    if not out.get("connector_manifest") and ctx.get("connector_manifest"):
        out["connector_manifest"] = ctx["connector_manifest"]
    if not out.get("source_context") and ctx.get("source_context"):
        out["source_context"] = ctx["source_context"]
    if not out.get("relationships") and (ctx.get("etl_flow") or {}).get("plan", {}).get("relationships"):
        out["relationships"] = (ctx.get("etl_flow") or {})["plan"]["relationships"]
    flow = ctx.get("etl_flow") or {}
    if not out.get("etl_intent") and flow.get("etl_intent"):
        out["etl_intent"] = flow["etl_intent"]
    if not out.get("engine_recommendation") and flow.get("plan", {}).get("engine_recommendation"):
        out["engine_recommendation"] = flow["plan"]["engine_recommendation"]
    if not out.get("narration") and flow.get("plan", {}).get("narration"):
        out["narration"] = flow["plan"]["narration"]
    return out


def _engine_rec_to_codegen(rec: Dict[str, Any]) -> tuple[str, str]:
    """Map engine_recommendation to (codegen_engine, sql_dialect)."""
    eng = str(rec.get("engine") or "python").lower()
    dialect = str(rec.get("dialect") or "tsql").lower()
    if eng == "pyspark":
        return "pyspark", dialect
    if eng == "adf":
        return "adf", dialect
    if eng == "sql":
        return "sql", dialect if dialect in ("ansi", "tsql") else "tsql"
    return "python", dialect


def _assessment_schema_signature(assess: Dict[str, Any]) -> str:
    """Compute a stable hash of the datasets, column names, and types to detect schema changes."""
    if not isinstance(assess, dict) or "datasets" not in assess:
        return ""
    import hashlib
    parts = []
    datasets = assess.get("datasets") or {}
    for ds_name in sorted(datasets.keys()):
        parts.append(f"ds:{ds_name}")
        cols = datasets[ds_name].get("columns") or {}
        for col_name in sorted(cols.keys()):
            col_info = cols[col_name] or {}
            dtype = str(col_info.get("dtype") or "")
            parts.append(f"col:{col_name}|type:{dtype}")
    sig_str = "\n".join(parts)
    return hashlib.sha256(sig_str.encode("utf-8")).hexdigest()


def etl_plan_start(
    session_id: str,
    business_rules: Any,
    assessment_result: Optional[Dict[str, Any]] = None,
    engine: str = "python",
    codegen_engine: Optional[str] = None,
    sql_dialect: str = "tsql",
    target_destination: str = "dataframe_only",
    target_path: Optional[str] = None,
    tenant_id: Optional[str] = None,
    source_context: Optional[Dict[str, Any]] = None,
    engine_user_override: bool = False,
    generation_mode: Optional[str] = "full",
) -> Dict[str, Any]:
    sid = (session_id or "default").strip() or "default"
    sess = load_session(sid)
    ctx = _ctx(sess)
    assess = _get_assessment(sess, assessment_result)

    if not assess:
        return {
            "ok": False,
            "error": "NO_ASSESSMENT",
            "message": "Run an assessment first, or pass assessment_result in the request body.",
        }

    if isinstance(assessment_result, dict) and assessment_result.get("datasets"):
        ctx["last_assessment_result"] = assessment_result

    flow = ctx.setdefault("etl_flow", {})
    schema_sig = _assessment_schema_signature(assess)
    flow["assessment_schema_signature"] = schema_sig
    sess["session_state"] = "planned"

    ds_names = list((assess.get("datasets") or {}).keys())
    tid = (tenant_id or tenant_id_from_session(ctx) or "default").strip() or "default"
    ctx["etl_tenant_id"] = tid
    pending = pending_rules_from_session(ctx)
    merged_raw = business_rules
    if pending:
        merged_raw = {**(pending or {}), **(business_rules if isinstance(business_rules, dict) else {})}
    rules_merged = merge_business_rules_for_datasets(merged_raw, ds_names, tenant_id=tid)

    # ── Zep memory: inject recalled dataset facts ────────────────────
    try:
        from agent.memory import recall_dataset_facts
        zep_facts = []
        for ds in ds_names[:3]:
            zep_facts.extend(recall_dataset_facts(user_id=sid, dataset_name=ds))
        if zep_facts:
            existing_notes = rules_merged.get("notes") or ""
            rules_merged["notes"] = existing_notes + "\n" + "\n".join(zep_facts)
            rules_merged["_zep_facts_applied"] = len(zep_facts)
    except Exception:
        pass
    # ─────────────────────────────────────────────────────────────────


    src_ctx = build_source_context(ctx, assess, override=source_context)
    ctx["source_context"] = src_ctx
    if target_destination == "overwrite":
        out_base = "__overwrite__"
    elif target_destination == "new_path" and target_path:
        out_base = target_path
    else:
        out_base = "cleaned/"
    manifest = build_connector_manifest(
        ctx, assess, output_base=out_base, overwrite_in_place=(target_destination == "overwrite")
    )
    ctx["connector_manifest"] = manifest

    t0 = time.time()
    
    # --- Agentic Intelligence Pass ---
    # First, build a draft plan to generate the initial manual review queue
    dq_recs = assess.get("dq_recommendations") if isinstance(assess, dict) else None
    draft_plan = build_etl_plan(
        assess,
        rules_merged,
        engine=engine,
        source_context=src_ctx,
        generation_mode=generation_mode,
        dq_recommendations=dq_recs,
    )
    draft_plan = enrich_plan_manual_review(draft_plan)
    
    agentic_result = analyze_agentic_intent(draft_plan, rules_merged)
    
    updated_rules = agentic_result.get("updated_business_rules") or {}
    if updated_rules:
        logger.info(f"Agentic rules override applied: {updated_rules}")
        rules_merged.update(updated_rules)
        # Re-build plan with updated structured toggles
        plan = build_etl_plan(
            assess,
            rules_merged,
            engine=engine,
            source_context=src_ctx,
            generation_mode=generation_mode,
            dq_recommendations=dq_recs,
        )
        plan = enrich_plan_manual_review(plan)
    else:
        plan = draft_plan
        
    resolutions = agentic_result.get("manual_review_resolutions") or []
    if resolutions:
        logger.info(f"Agentic manual review auto-resolution applied: {len(resolutions)} items")
        plan, res_errs = apply_manual_resolutions(plan, resolutions)
        if res_errs:
            logger.warning(f"Agentic auto-resolution errors: {res_errs}")
    plan["connector_manifest"] = manifest
    plan["source_context"] = src_ctx
    plan["etl_intent"] = {
        "engine": (engine or "python").lower(),
        "target_destination": target_destination or "dataframe_only",
        "target_path": target_path,
    }

    # Compute ETL readiness and map blockers to manual review
    from agent.etl_readiness_scorer import compute_etl_readiness
    readiness = compute_etl_readiness(assess)
    assess["etl_readiness"] = readiness
    if readiness["blockers"]:
        existing = plan.get("manual_review") or []
        for blocker in readiness["blockers"]:
            b_ds = blocker.get("dataset")
            b_col = blocker.get("column")
            b_it = blocker.get("issue_type") or "unknown"
            if not any(
                str(m.get("dataset")).lower() == str(b_ds).lower() and
                str(m.get("column")).lower() == str(b_col).lower() and
                str(m.get("issue_type")).lower() == str(b_it).lower()
                for m in existing if isinstance(m, dict)
            ):
                plan.setdefault("manual_review", []).append({
                    "dataset": b_ds,
                    "column": b_col,
                    "issue_type": b_it,
                    "severity": blocker.get("severity") or "HIGH",
                    "message": blocker.get("issue"),
                    "guidance": blocker.get("fix") or "",
                })
        plan = enrich_plan_manual_review(plan)
    plan["blocked"] = []

    flow = ctx.setdefault("etl_flow", {})
    # Default "fallback" avoids LLM calls during plan build (tiered/llm add significant latency).
    narr_mode = os.getenv("ETL_NARRATOR_MODE", "fallback").strip().lower()
    use_llm_full = narr_mode in ("llm", "full") or os.getenv(
        "ETL_NARRATOR_USE_LLM", "0"
    ).strip().lower() in ("1", "true", "yes")
    if (generation_mode or "").strip().lower() == "cleanse_only":
        narr_mode = "fallback"
        use_llm_full = False
    cache_key = f"narr_{plan.get('plan_id')}_{plan.get('assessment_signature')}"
    cached = (flow.get("narration_cache") or {}).get(cache_key)
    if isinstance(cached, dict) and cached.get("engine_explanation"):
        plan["narration"] = cached
    else:
        plan["narration"] = narrate_plan(plan, mode=narr_mode, use_llm=use_llm_full)
        flow.setdefault("narration_cache", {})[cache_key] = plan["narration"]

    plan_ok, plan_errs = validate_etl_plan(plan, assess, rules_merged)

    eng_rec = plan.get("engine_recommendation") or {}
    if engine_user_override:
        ce = (codegen_engine or engine or "python").lower()
        sd = (sql_dialect or "tsql").lower()
        ctx["etl_engine_override"] = True
    else:
        ce, sd = _engine_rec_to_codegen(eng_rec)
        if codegen_engine:
            ce = codegen_engine.lower()
        ctx.pop("etl_engine_override", None)
    _migrate_phase(flow)
    _transition(flow, "planned", by="system", reason="etl_plan_start")
    preview = None
    if plan_ok and not (plan.get("blocked") or []):
        preview = build_impact_preview(assess, plan)
        flow["preview"] = preview
        _transition(flow, "preview_ready", by="system", reason="plan_enriched_with_evidence")
    elif plan.get("blocked"):
        flow["failure_reason"] = "Plan has blocking issues"
        _transition(flow, "failed", by="system", reason="plan_blocked")

    if pending:
        ctx.pop("pending_business_rules", None)

    flow.update(
        {
            "plan": plan,
            "plan_validation_ok": plan_ok,
            "plan_validation_errors": plan_errs,
            "target_engine": (engine or "python").lower(),
            "codegen_engine": ce,
            "sql_dialect": sd,
            "business_rules": rules_merged,
            "etl_intent": {
                "engine": (engine or "python").lower(),
                "sql_dialect": sd,
                "target_destination": target_destination or "dataframe_only",
                "target_path": target_path,
                "generation_mode": generation_mode,
            },
            "approved_plan": None,
            "preview": preview,
            "code": None,
            "validation_ok": None,
            "validation_errors": [],
            "generated_by": None,
            "artifact_rel_path": None,
            "is_draft": False,
            "lineage": None,
            "artifact_version": flow.get("artifact_version") or 0,
        }
    )

    save_session(sess)
    logger.info(
        "etl_plan_start session=%s plan_id=%s ok=%s steps=%s latency_ms=%.0f",
        sid,
        plan.get("plan_id"),
        plan_ok,
        sum(len((v or {}).get("steps") or []) for v in (plan.get("datasets") or {}).values()),
        (time.time() - t0) * 1000,
    )
    blocked = plan.get("blocked") or []
    plan_success = plan_ok and not blocked
    pending_manual = count_pending_manual_review(plan)
    return {
        "ok": plan_success,
        "session_id": sid,
        "plan": plan,
        "blocked": blocked,
        "pending_manual_review": pending_manual,
        "plan_validation_ok": plan_ok,
        "plan_validation_errors": plan_errs,
        "engine_recommendation": plan.get("engine_recommendation"),
        "source_context": src_ctx,
        "recommended_codegen_engine": ce,
        "recommended_sql_dialect": sd,
        "message": (
            None
            if plan_success
            else (
                "Plan has blocking issues."
                if blocked
                else "Plan built with validation warnings — review plan_validation_errors."
            )
        ),
    }


def etl_apply_manual_resolutions(
    session_id: str,
    resolutions: List[Dict[str, Any]],
    plan_override: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Apply user picks for manual_review items; promotes steps into plan.datasets."""
    sid = (session_id or "default").strip() or "default"
    sess = load_session(sid)
    ctx = _ctx(sess)
    assess = _get_assessment(sess, None)
    flow = ctx.get("etl_flow") or {}

    plan = (
        plan_override
        if isinstance(plan_override, dict) and plan_override.get("datasets") is not None
        else flow.get("plan")
    )
    if not isinstance(plan, dict):
        return {"ok": False, "error": "NO_PLAN", "message": "Create a plan first (POST /etl/plan)."}

    plan = enrich_plan_manual_review(_rehydrate_plan(plan, ctx))
    rules = flow.get("business_rules") or plan.get("business_rules") or {}
    updated, apply_errs = apply_manual_resolutions(plan, resolutions, business_rules=rules)

    if apply_errs and not resolutions:
        return {
            "ok": False,
            "error": "NO_RESOLUTIONS",
            "message": "Provide at least one resolution.",
            "errors": apply_errs,
        }

    struct_ok, plan_errs = validate_etl_plan(updated, assess or {}, rules)
    pending = count_pending_manual_review(updated)
    plan_ok = struct_ok and pending == 0
    flow = ctx.setdefault("etl_flow", {})
    flow["plan"] = updated
    flow["plan_validation_ok"] = plan_ok
    flow["plan_validation_errors"] = plan_errs
    flow["approved_plan"] = None
    save_session(sess)

    return {
        "ok": len(apply_errs) == 0 and pending == 0,
        "session_id": sid,
        "plan": updated,
        "pending_manual_review": pending,
        "plan_validation_ok": plan_ok,
        "plan_validation_errors": plan_errs,
        "errors": apply_errs,
        "message": (
            None
            if pending == 0 and not apply_errs
            else (
                f"{pending} manual review item(s) still pending."
                if pending
                else "Some resolutions could not be applied."
            )
        ),
    }


def etl_confirm_plan(session_id: str, plan_override: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    sid = (session_id or "default").strip() or "default"
    sess = load_session(sid)
    ctx = _ctx(sess)
    assess = _get_assessment(sess, None)
    flow = ctx.setdefault("etl_flow", {})
    _migrate_phase(flow)

    schema_sig = _assessment_schema_signature(assess or {})
    saved_sig = flow.get("assessment_schema_signature")
    if saved_sig and schema_sig != saved_sig:
        rollback_on_failure(flow, reason="Schema signature mismatch (underlying dataset/schema changed).")
        save_session(sess)
        return {
            "ok": False,
            "error": "SCHEMA_INVALIDATED",
            "message": "The underlying dataset schema or connection has changed, invalidating the planned transformations. Rollback to planned state triggered.",
        }

    plan = (
        plan_override
        if isinstance(plan_override, dict) and plan_override.get("datasets") is not None
        else flow.get("plan")
    )
    if not isinstance(plan, dict) or not plan.get("datasets"):
        return {"ok": False, "error": "NO_PLAN", "message": "Create a plan first (POST /etl/plan)."}

    plan = enrich_plan_manual_review(_rehydrate_plan(plan, ctx))

    pending_manual = count_pending_manual_review(plan)
    if pending_manual > 0:
        return {
            "ok": False,
            "error": "MANUAL_REVIEW_PENDING",
            "message": f"Resolve {pending_manual} manual review item(s) in the UI before confirming.",
            "pending_manual_review": pending_manual,
            "manual_review": plan.get("manual_review") or [],
        }

    blocked = plan.get("blocked") or []
    if blocked:
        return {
            "ok": False,
            "error": "PLAN_BLOCKED",
            "message": "Plan has blocking issues; resolve required columns or rules first.",
            "blocked": blocked,
        }

    rules = flow.get("business_rules") or plan.get("business_rules") or {}
    plan_ok, plan_errs = validate_etl_plan_for_confirm(plan, assess or {}, rules)
    if not plan_ok:
        return {
            "ok": False,
            "error": "PLAN_VALIDATION_FAILED",
            "message": "Plan failed validation. Fix issues before confirming.",
            "plan_validation_errors": plan_errs,
        }

    _migrate_phase(flow)
    phase = flow.get("phase", "planned")
    if phase not in ("preview_ready", "planned"):
        return {
            "ok": False,
            "error": "INVALID_PHASE",
            "message": f"Cannot approve plan in phase '{phase}'. Build plan first.",
            "phase": phase,
        }

    auto_ok = _plan_all_auto(plan) and _invariants_pass(plan)
    if phase == "planned":
        flow["preview"] = flow.get("preview") or build_impact_preview(assess or {}, plan)
        _transition(flow, "preview_ready", by="system", reason="preview_before_approve")
        phase = "preview_ready"

    preview = flow.get("preview") or build_impact_preview(assess or {}, plan)
    lineage = build_lineage(plan, assess or {})
    flow = ctx.setdefault("etl_flow", {})
    flow["approved_plan"] = plan
    flow["preview"] = preview
    flow["lineage"] = lineage
    flow["plan_validation_ok"] = True
    _transition(
        flow,
        "approved",
        by="user" if not auto_ok else "system",
        reason="confirm_plan_called" if not auto_ok else "auto_approved_all_steps_safe",
    )

    save_session(sess)
    logger.info(
        "etl_confirm_plan session=%s plan_id=%s lineage_cols=%s",
        sid,
        plan.get("plan_id"),
        sum(len(v) for v in lineage.values()),
    )
    return {
        "ok": True,
        "session_id": sid,
        "preview": preview,
        "approved_plan": plan,
        "lineage": lineage,
    }


def _generate_for_engine(
    eng: str,
    plan: Dict[str, Any],
    assess: Dict[str, Any],
    *,
    sql_dialect: str,
    output_mode: str,
    output_path: Optional[str],
    inject_errors: Optional[List[str]],
) -> tuple[str, bool, List[str], str]:
    """Returns (code, ok, errs, generated_by)."""
    generated_by = "llm"

    if eng == "python":
        code = generate_etl_with_llm(
            plan,
            assess,
            engine="python",
            output_mode=output_mode,
            output_path=output_path,
            validation_errors=inject_errors,
            validate_fn=lambda src: validate_etl_python_source(src),
        )
        if is_llm_generation_error(code):
            return code, False, [code], generated_by
        ok, errs = validate_etl_python_source(code)
        return code, ok, errs, generated_by

    if eng in ("sql", "tsql", "ansi"):
        from agent.etl_pipeline.validate_sql import validate_sql_basic

        dialect = "ansi" if eng == "ansi" else (sql_dialect or "tsql")
        code = generate_etl_with_llm(
            plan,
            assess,
            engine=f"sql-{dialect}",
            sql_dialect=dialect,
            output_mode=output_mode,
            validation_errors=inject_errors,
        )
        if is_llm_generation_error(code):
            return code, False, [code], generated_by
        ok, errs = validate_sql_basic(code)
        return code, ok, errs, generated_by

    if eng in ("spark", "pyspark"):
        code = generate_etl_with_llm(
            plan,
            assess,
            engine="pyspark",
            output_mode=output_mode,
            output_path=output_path,
            validation_errors=inject_errors,
            validate_fn=lambda src: validate_pyspark_source(src, plan),
        )
        if is_llm_generation_error(code):
            return code, False, [code], generated_by
        ok, errs = validate_pyspark_source(code, plan)
        return code, ok, errs, generated_by

    if eng == "adf":
        from agent.etl_pipeline.validate_adf import validate_adf_json

        if inject_errors:
            raw = generate_etl_with_llm(plan, assess, engine="adf", validation_errors=inject_errors)
            if is_llm_generation_error(raw):
                return raw, False, [raw], generated_by
            obj, parse_errs = parse_adf_json_from_llm(raw)
            if obj is None:
                return raw, False, parse_errs, generated_by
            code = json.dumps(obj, indent=2)
            ok, errs = validate_adf_json(obj)
            return code, ok, errs, generated_by

        obj, llm_err = generate_adf_with_llm(plan, assess, validate_fn=validate_adf_json)
        if obj is None:
            return llm_err or "# Error: ADF generation failed", False, [llm_err or "ADF failed"], generated_by
        code = json.dumps(obj, indent=2)
        ok, errs = validate_adf_json(obj)
        return code, ok, errs, generated_by

    return "", False, [f"Unsupported engine: {eng}"], generated_by


def _template_fallback(
    eng: str,
    plan: Dict[str, Any],
    assess: Dict[str, Any],
    *,
    sql_dialect: str,
) -> tuple[str, bool, List[str]]:
    if eng == "python":
        code = generate_python_etl(plan, assess)
        return code, *validate_etl_python_source(code, plan)

    if eng in ("sql", "tsql", "ansi"):
        from agent.etl_pipeline.sql_codegen import generate_sql_etl
        from agent.etl_pipeline.validate_sql import validate_sql_basic

        dialect = "ansi" if eng == "ansi" else (sql_dialect or "tsql")
        code = generate_sql_etl(plan, assess, dialect=dialect)
        return code, *validate_sql_basic(code)

    if eng in ("spark", "pyspark"):
        from agent.etl_pipeline.pyspark_codegen import generate_pyspark_etl

        code = generate_pyspark_etl(plan, assess)
        return code, *validate_pyspark_source(code, plan)

    if eng == "adf":
        from agent.etl_pipeline.adf_codegen import generate_adf_mapping_flow
        from agent.etl_pipeline.validate_adf import validate_adf_bundle

        obj = generate_adf_mapping_flow(plan, assess)
        code = json.dumps(obj, indent=2)
        return code, *validate_adf_bundle(obj)

    return "", False, [f"Unsupported engine: {eng}"]


def etl_generate_code(
    session_id: str,
    engine: str = "python",
    sql_dialect: str = "tsql",
    *,
    codegen_mode: Optional[str] = None,
    generation_mode: Optional[str] = "full",
) -> Dict[str, Any]:
    sid = (session_id or "default").strip() or "default"
    sess = load_session(sid)
    ctx = _ctx(sess)
    assess = _get_assessment(sess, None) or {}
    flow = ctx.setdefault("etl_flow", {})
    _migrate_phase(flow)

    schema_sig = _assessment_schema_signature(assess)
    saved_sig = flow.get("assessment_schema_signature")
    if saved_sig and schema_sig != saved_sig:
        rollback_on_failure(flow, reason="Schema signature mismatch (underlying dataset/schema changed).")
        save_session(sess)
        return {
            "ok": False,
            "error": "SCHEMA_INVALIDATED",
            "message": "The underlying dataset schema or connection has changed, invalidating the planned transformations. Rollback to planned state triggered.",
        }

    _migrate_phase(flow)
    current_phase = flow.get("phase", "planned")
    allowed_phases = {"approved", "failed", "code_ready", "generating", "validated", "downloadable"}
    if current_phase not in allowed_phases:
        return {
            "ok": False,
            "error": "PLAN_NOT_APPROVED",
            "http_status": 409,
            "message": (
                f"Cannot generate code: phase is '{current_phase}'. "
                "Approve the plan first via POST /etl/confirm."
            ),
            "phase": current_phase,
        }

    plan = flow.get("approved_plan")
    if not isinstance(plan, dict) or not plan.get("datasets"):
        return {
            "ok": False,
            "error": "NO_APPROVED_PLAN",
            "message": "Confirm the plan first (POST /etl/confirm).",
        }
    plan = _rehydrate_plan(plan, ctx)
    plan["generation_mode"] = generation_mode or plan.get("generation_mode") or flow.get("etl_intent", {}).get("generation_mode") or "full"

    eng = (engine or flow.get("codegen_engine") or "python").lower()

    # Engine change check and cleanup
    current_engine = str(flow.get("target_engine") or "").lower()
    if current_engine and eng != current_engine:
        logger.info(f"etl_generate_code: engine changed from '{current_engine}' to '{eng}'. Clearing old phase codes.")
        flow.pop("code_cleanse", None)
        flow.pop("code_transform", None)
        flow.pop("code", None)

    intent = flow.get("etl_intent") or {}
    output_mode = intent.get("target_destination", "dataframe_only")
    output_path = intent.get("target_path")
    sd = (sql_dialect or flow.get("sql_dialect") or "tsql").lower()

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out_dir = os.path.join(root, "output", "etl_code", _safe_segment(sid))
    os.makedirs(out_dir, exist_ok=True)
    pid = _safe_segment(str(plan.get("plan_id") or "plan"))
    ts = int(time.time())
    version = int(flow.get("artifact_version") or 0) + 1

    _transition(flow, "generating", by="system")
    save_session(sess)

    mode = _resolve_codegen_mode(eng, requested=codegen_mode)
    t_gen = time.time()
    ok = False
    errs: List[str] = []
    code = ""
    generated_by = "template" if mode == "template" else "llm"

    try:
        if mode == "template":
            code, ok, errs = _template_fallback(eng, plan, assess, sql_dialect=sd)
            generated_by = "template"
        elif mode == "llm":
            code, ok, errs, generated_by = _generate_for_engine(
                eng,
                plan,
                assess,
                sql_dialect=sd,
                output_mode=output_mode,
                output_path=output_path,
                inject_errors=None,
            )
        else:
            code, ok, errs, generated_by = _generate_for_engine(
                eng,
                plan,
                assess,
                sql_dialect=sd,
                output_mode=output_mode,
                output_path=output_path,
                inject_errors=None,
            )
            if not ok and not is_llm_generation_error(code):
                logger.info(
                    "etl_generate_code LLM validation failed session=%s — using template fallback",
                    sid,
                )
            if not ok:
                generated_by = "template"
                code, ok, errs = _template_fallback(eng, plan, assess, sql_dialect=sd)
    except Exception as exc:
        logger.exception("etl_generate_code failed session=%s", sid)
        code = code or f"# Generation failed: {exc}"
        ok = False
        errs = [str(exc)]
        generated_by = "error"

    flow = ctx.setdefault("etl_flow", {})
    gen_mode = str(generation_mode or "full").lower()
    combined_code = code
    if gen_mode == "cleanse_only":
        flow["code_cleanse"] = code
        if "code_transform" in flow and flow["code_transform"]:
            if eng in ("sql", "tsql", "ansi"):
                combined_code = code + "\nGO\n\n" + flow["code_transform"]
            elif eng in ("python", "pyspark", "spark"):
                combined_code = code + "\n\n# ============================================================\n# Phase 2: Transform\n# ============================================================\n\n" + flow["code_transform"]
    elif gen_mode == "transform_only":
        flow["code_transform"] = code
        if "code_cleanse" in flow and flow["code_cleanse"]:
            if eng in ("sql", "tsql", "ansi"):
                combined_code = flow["code_cleanse"] + "\nGO\n\n" + code
            elif eng in ("python", "pyspark", "spark"):
                combined_code = flow["code_cleanse"] + "\n\n# ============================================================\n# Phase 2: Transform\n# ============================================================\n\n" + code
    else:
        flow.pop("code_cleanse", None)
        flow.pop("code_transform", None)

    ext_map = {
        "python": "py",
        "sql": "sql",
        "tsql": "sql",
        "ansi": "sql",
        "pyspark": "py",
        "spark": "py",
        "adf": "json",
    }
    ext = ext_map.get(eng, "py")
    fname = f"etl_{pid}_{eng}_v{version}_{ts}.{ext}"

    abs_path = os.path.join(out_dir, fname)
    with open(abs_path, "w", encoding="utf-8") as f:
        f.write(combined_code)

    rel = os.path.relpath(abs_path, root).replace("\\", "/")

    if ok:
        _transition(flow, "validated", by="system", reason=f"validator_passed generated_by={generated_by}")
        _transition(flow, "code_ready", by="system", reason="artifact_written")
        sess["session_state"] = "generated"
    else:
        rollback_on_failure(flow, reason=f"validation_failed: {(errs or ['unknown'])[:3]}")
    latency_ms = (time.time() - t_gen) * 1000
    duckdb_diff: Optional[Dict[str, Any]] = None
    if eng in ("sql", "tsql", "ansi"):
        duckdb_diff = _maybe_build_etl_duckdb_diff(eng=eng, code=combined_code, ok=ok, ctx=ctx, assess=assess)
    flow_update: Dict[str, Any] = {
        "code": combined_code,
        "target_engine": eng,
        "codegen_engine": eng,
        "validation_ok": ok,
        "validation_errors": errs or [],
        "generated_by": generated_by,
        "artifact_rel_path": rel,
        "is_draft": not ok,
        "artifact_version": version,
        "last_generate_latency_ms": round(latency_ms, 1),
    }
    if duckdb_diff is not None:
        flow_update["duckdb_diff"] = duckdb_diff
    flow.update(flow_update)
    save_session(sess)

    logger.info(
        "etl_generate_code session=%s plan_id=%s engine=%s by=%s ok=%s version=%s latency_ms=%.0f",
        sid,
        plan.get("plan_id"),
        eng,
        generated_by,
        ok,
        version,
        latency_ms,
    )

    return {
        "ok": ok,
        "session_id": sid,
        "engine": eng,
        "format": ext,
        "code": code,
        "validation_ok": ok,
        "validation_errors": errs or [],
        "generated_by": generated_by,
        "is_draft": not ok,
        "label": "Validated" if ok else "UNVALIDATED — do not deploy",
        "artifact_rel_path": rel,
        "artifact_version": version,
        "latency_ms": round(latency_ms, 1),
        "codegen_mode": mode,
        "message": (
            None
            if ok
            else "Code generated as draft — fix validation_errors before production deploy."
        ),
        "duckdb_diff": flow.get("duckdb_diff"),
    }


def etl_get_lineage(session_id: str) -> Dict[str, Any]:
    sid = (session_id or "default").strip() or "default"
    sess = load_session(sid)
    flow = (_ctx(sess).get("etl_flow") or {})
    lineage = flow.get("lineage")
    if not isinstance(lineage, dict):
        return {"ok": False, "error": "NO_LINEAGE", "message": "Confirm the plan first to build lineage."}
    return {"ok": True, "session_id": sid, "lineage": lineage, "plan_id": (flow.get("approved_plan") or {}).get("plan_id")}




def etl_list_tenants() -> Dict[str, Any]:
    return {"ok": True, "tenants": list_tenant_ids()}


def etl_deploy(session_id: str) -> Dict[str, Any]:
    sid = (session_id or "default").strip() or "default"
    sess = load_session(sid)
    flow = sess.setdefault("context", {}).setdefault("etl_flow", {})
    if flow.get("phase") != "code_ready" and not flow.get("validation_ok"):
        return {
            "ok": False,
            "error": "NOT_READY",
            "message": "ETL code must be generated and validated before deployment."
        }
    sess["session_state"] = "deployed"
    save_session(sess)
    return {"ok": True, "session_id": sid, "session_state": "deployed"}


def etl_execute_sql(
    session_id: str,
    *,
    approved: bool = False,
    dry_run: bool = False,
    connection_string: str | None = None,
    timeout_s: int = 120,
) -> dict:
    """
    Execute the already-generated SQL for a session.
    Reads generated code from flow["code"] and flow["target_engine"].
    Only runs for sql/tsql/ansi engines — returns error for others.
    Calls orchestrate_sql_execution() from execution_orchestrator.py.
    Saves execution_result to flow["sql_execution_result"].
    Saves execution metadata to governance if assessment is present:
        assessment["governance"]["sql_execution_status"]
        assessment["governance"]["sql_execution_summary"]
    Transitions ETL phase to "downloadable" on success.
    Returns the orchestrator result dict + session_id.
    """
    sid = (session_id or "default").strip() or "default"
    sess = load_session(sid)
    ctx = _ctx(sess)
    flow = ctx.setdefault("etl_flow", {})

    target_engine = str(flow.get("target_engine") or "").lower()
    if target_engine not in ("sql", "tsql", "ansi"):
        return {
            "ok": False,
            "session_id": sid,
            "error": "UNSUPPORTED_ENGINE",
            "message": f"Execution only supported for SQL/T-SQL/ANSI target engines, not '{target_engine}'."
        }

    sql = flow.get("code")
    if not sql:
        return {
            "ok": False,
            "session_id": sid,
            "error": "NO_CODE",
            "message": "No generated SQL code found for this session. Generate code first."
        }

    plan = flow.get("approved_plan")
    table_names = []
    if plan and isinstance(plan, dict) and "datasets" in plan:
        table_names = list(plan["datasets"].keys())

    from agent.etl_pipeline.execution_orchestrator import orchestrate_sql_execution, build_pre_execution_counts
    
    pre_counts = None
    if table_names and not dry_run:
        pre_counts = build_pre_execution_counts(table_names, connection_string)

    assess = _get_assessment(sess, None)
    result = orchestrate_sql_execution(
        sql,
        session_id=sid,
        run_id=None,
        approved=approved,
        dry_run=dry_run,
        connection_string=connection_string,
        pre_execution_counts=pre_counts,
        assessment=assess,
        timeout_s=timeout_s,
    )

    flow["sql_execution_result"] = result

    if assess and isinstance(assess, dict):
        gov = assess.setdefault("governance", {})
        gov["sql_execution_status"] = "success" if result.get("ok") else "failed"
        gov["sql_execution_summary"] = result.get("post_execution_summary")
        ctx["last_assessment_result"] = assess

    if result.get("ok") and not dry_run:
        # ── Fabric Lakehouse Mirror Hook ──
        from connectors.fabric_lakehouse_connector import is_fabric_mirror_enabled, write_to_lakehouse
        if is_fabric_mirror_enabled():
            logger.info("Fabric Lakehouse Mirror is enabled. Starting mirror process...")
            mirror_results = []
            conn = None
            try:
                from agent.azure_sql_executor import get_connection
                import pandas as pd
                conn = get_connection(connection_string)
                
                for ds_name in table_names:
                    try:
                        from agent.etl_pipeline.sql_codegen import _get_clean_table_name, _get_transformed_table_name
                        clean_tbl = _get_clean_table_name(ds_name)
                        transformed_tbl = _get_transformed_table_name(ds_name)
                        candidate_tables = [clean_tbl, transformed_tbl, ds_name]

                        df_clean = None
                        chosen_table = None
                        for tbl in candidate_tables:
                            tbl_parts = tbl.split(".", 1)
                            quoted_tbl = f"[{tbl_parts[0]}].[{tbl_parts[1]}]" if len(tbl_parts) == 2 else f"[{tbl}]"
                            try:
                                df_temp = pd.read_sql(f"SELECT * FROM {quoted_tbl}", conn)
                                if not df_temp.empty:
                                    df_clean = df_temp
                                    chosen_table = tbl
                                    logger.info(f"Fabric mirror: found {len(df_temp)} rows in '{tbl}' for source '{ds_name}'.")
                                    break
                                else:
                                    logger.info(f"Fabric mirror: '{tbl}' exists but is empty, trying next candidate.")
                            except Exception:
                                logger.info(f"Fabric mirror: '{tbl}' not found or not readable, trying next candidate.")
                                continue

                        if df_clean is not None:
                            logger.info(f"Mirroring {len(df_clean)} rows from '{chosen_table}' to Fabric Lakehouse...")
                            res = write_to_lakehouse(df_clean, chosen_table)
                            res["source_table"] = chosen_table
                            mirror_results.append(res)
                        else:
                            msg = (
                                f"All candidate tables are empty or missing for source '{ds_name}'. "
                                f"Candidates tried: {candidate_tables}. "
                                "Ensure the ETL cleanse step ran and populated at least one output table."
                            )
                            logger.warning(f"Fabric mirror: {msg}")
                            mirror_results.append({
                                "ok": False,
                                "error": "NO_DATA_FOUND",
                                "message": msg,
                                "source": ds_name,
                                "candidates_tried": candidate_tables,
                            })
                    except Exception as select_err:
                        logger.error(f"Failed to read/mirror table for {ds_name}: {select_err}")
                        mirror_results.append({
                            "ok": False,
                            "error": "READ_OR_WRITE_FAILED",
                            "message": str(select_err),
                            "table": ds_name,
                        })
                
                flow["fabric_mirror_result"] = {
                    "ok": all(r.get("ok", False) for r in mirror_results),
                    "details": mirror_results
                }
            except Exception as conn_err:
                logger.error(f"Fabric mirror process failed: connection error or other error: {conn_err}")
                flow["fabric_mirror_result"] = {
                    "ok": False,
                    "error": "CONNECTION_FAILED",
                    "message": str(conn_err)
                }
            finally:
                if conn:
                    try:
                        conn.close()
                    except Exception:
                        pass
        else:
            logger.info("Fabric Lakehouse Mirror is not enabled.")

        try:
            _transition(flow, "downloadable", by="system", reason="sql_execution_succeeded")
        except ValueError:
            flow["phase"] = "downloadable"

    if "fabric_mirror_result" in flow:
        result["fabric_mirror_result"] = flow["fabric_mirror_result"]

    save_session(sess)
    result["session_id"] = sid
    return result
