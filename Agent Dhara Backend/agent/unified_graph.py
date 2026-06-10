from __future__ import annotations
import json
import logging
import time
from typing import Any, Dict, List, Optional, TypedDict
from langgraph.graph import StateGraph, END

from agent.langgraph_orchestrator import build_orchestrator_graph
from agent.etl_graph import build_etl_graph, run_etl_graph, ETLState
from agent.master_agent import MasterAgent

logger = logging.getLogger("agent.unified.graph")

class UnifiedState(TypedDict, total=False):
    # Routing inputs
    session_id: str
    user_request: str
    sources_path: str
    selected_sources: List[str]
    job_id: str
    request_id: str
    approved_semantics: Dict[str, Dict[str, str]]

    # Memory inputs (injected by route node from pipeline_runs)
    prior_run: Optional[Dict[str, Any]]
    schema_changed: bool
    prior_dq_score: Optional[int]
    memory_facts: List[str]

    # Routing plan (from MasterAgent.plan_with_memory)
    routing_plan: Dict[str, Any]

    # Assessment sub-graph outputs (OrchestratorState fields)
    extractions: List[Dict[str, Any]]
    extraction_errors: List[Dict[str, Any]]
    data_quality: Dict[str, Any]
    dq_recommendations: Dict[str, Any]
    transform_suggestions: Dict[str, Any]
    assessment_result: Dict[str, Any]
    schema_hash: str
    dq_score: int

    # ETL sub-graph outputs (ETLState fields)
    generation_mode: str
    engine: str
    sql_dialect: str
    business_rules: Dict[str, Any]
    etl_plan: Dict[str, Any]
    etl_preview: Dict[str, Any]
    etl_code: str
    etl_validation_ok: bool
    etl_artifact_path: str

    # Improvement narrative
    improvement_narrative: str

    # Status
    ok: bool
    error: Optional[str]
    timings: Dict[str, Any]

def _merge_timings(state: UnifiedState, extra: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(state.get("timings") or {})
    out.update(extra or {})
    return out

def _node_unified_route(state: UnifiedState) -> UnifiedState:
    t0 = time.time()
    sid = state.get("session_id") or "default"

    # Fast operational memory (SQLite — always available)
    from agent.session_store import get_latest_pipeline_run
    prior_run = get_latest_pipeline_run(sid)

    # Memory-aware routing
    master = MasterAgent()
    plan = master.plan_with_memory(
        state.get("user_request") or "",
        prior_run=prior_run,
        current_schema_hash=None,   # computed after extraction
    )

    return {
        "routing_plan": plan.__dict__,
        "prior_run": prior_run,
        "schema_changed": True,   # conservative default
        "timings": _merge_timings(state, {"route_ms": int((time.time() - t0) * 1000)}),
    }

def _node_narrate(state: UnifiedState) -> UnifiedState:
    logger.info("Executing unified node: narrate")
    from agent.session_store import save_pipeline_run, get_latest_pipeline_run
    from agent.etl_readiness_scorer import compute_etl_readiness
    from agent.etl_handlers import _assessment_schema_signature
    from agent.improvement_narrator import build_improvement_narrative

    sid = state.get("session_id") or "default"
    
    # Grab current run data from assessment outputs in state, or fallback to session load
    datasets = {}
    extractions = state.get("extractions") or []
    for ext in extractions:
        ext_res = ext.get("result") or {}
        if isinstance(ext_res, dict) and "datasets" in ext_res:
            datasets.update(ext_res["datasets"])
            
    if not datasets:
        # Fallback to session load if assess node was skipped
        from agent.session_store import load_session
        sess = load_session(sid)
        last_assess = sess.get("context", {}).get("last_assessment_result") or {}
        datasets = last_assess.get("datasets") or {}
            
    merged_assess = {"datasets": datasets}
    
    # Calculate readiness score & schema signature
    readiness = compute_etl_readiness(merged_assess)
    schema_hash = _assessment_schema_signature(merged_assess)
    
    dq_score = readiness["score"]
    dq_issues = len(readiness["blockers"]) + len(readiness["warnings"])
    notes = readiness["etl_recommendation"]

    # Save to pipeline_runs
    save_pipeline_run(
        session_id=sid,
        dataset_names=list(datasets.keys()),
        schema_hash=schema_hash,
        dq_score=dq_score,
        dq_issue_count=dq_issues,
        etl_phase=state.get("routing_plan", {}).get("resume_from") or "assessed",
        notes=notes,
    )

    # Load prior run to compare
    prior = state.get("prior_run")
    current_run_summary = {
        "dq_score": dq_score,
        "dq_issue_count": dq_issues,
        "schema_hash": schema_hash,
        "run_ts": time.time(),
    }
    
    narrative = build_improvement_narrative(current_run_summary, prior)

    return {
        "dq_score": dq_score,
        "schema_hash": schema_hash,
        "improvement_narrative": narrative,
    }

def _route_after_unified_route(state: UnifiedState) -> str:
    plan = state.get("routing_plan") or {}
    if plan.get("resume_from"):
        return "etl"
    if plan.get("do_extract"):
        return "assess"
    if plan.get("do_etl_plan"):
        return "etl"
    return END

def _route_after_assess(state: UnifiedState) -> str:
    plan = state.get("routing_plan") or {}
    if plan.get("do_etl_plan"):
        return "etl"
    return "narrate"

def build_unified_graph(checkpointer=None):
    assessment_graph = build_orchestrator_graph()   # compiled sub-graph
    etl_graph_compiled = build_etl_graph()
    
    g = StateGraph(UnifiedState)
    g.add_node("route", _node_unified_route)
    g.add_node("assess", assessment_graph)
    g.add_node("etl", etl_graph_compiled)
    g.add_node("narrate", _node_narrate)

    g.set_entry_point("route")
    g.add_conditional_edges("route", _route_after_unified_route)
    g.add_conditional_edges("assess", _route_after_assess)
    g.add_edge("etl", "narrate")
    g.add_edge("narrate", END)
    
    return g.compile(checkpointer=checkpointer)

def run_unified_graph(
    session_id: str,
    user_request: str,
    sources_path: str = "config/sources.yaml",
    selected_sources: Optional[List[str]] = None,
    generation_mode: str = "full",
    engine: str = "python",
    business_rules: Optional[Dict] = None,
    job_id: str = "",
    checkpointer=None,
) -> Dict[str, Any]:
    graph = build_unified_graph(checkpointer=checkpointer)
    initial_state: UnifiedState = {
        "session_id": session_id,
        "user_request": user_request,
        "sources_path": sources_path,
        "selected_sources": selected_sources or [],
        "generation_mode": generation_mode,
        "engine": engine,
        "business_rules": business_rules or {},
        "job_id": job_id,
        "timings": {},
    }
    
    config = {"configurable": {"thread_id": session_id}} if checkpointer else None
    final_state = graph.invoke(initial_state, config=config)
    
    return dict(final_state)
