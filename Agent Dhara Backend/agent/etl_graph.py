from __future__ import annotations
import logging
from typing import Any, Dict, List, Optional, TypedDict
from langgraph.graph import StateGraph, END

from agent.etl_handlers import (
    etl_plan_start,
    etl_confirm_plan,
    etl_generate_code,
    etl_execute_sql,
)

logger = logging.getLogger("agent.etl.graph")

class ETLState(TypedDict, total=False):
    # Inputs
    session_id: str
    generation_mode: str          # "full" | "cleanse_only" | "transform_only" | "plan_only"
    engine: str                   # "python" | "sql" | "pyspark" | "adf"
    sql_dialect: str              # "tsql" | "ansi" | "spark"
    business_rules: Dict[str, Any]
    assessment_result: Optional[Dict[str, Any]]

    # Plan node outputs
    plan: Dict[str, Any]
    preview: Dict[str, Any]
    lineage: Dict[str, Any]

    # Generate node outputs
    code: str
    validation_ok: bool
    validation_errors: List[str]
    artifact_rel_path: str
    generated_by: str             # "agentic" | "template" | "llm"
    engine_effective: str

    # Execute node outputs (optional path)
    execution_result: Dict[str, Any]

    # Status
    ok: bool
    error: Optional[str]
    message: Optional[str]

def _node_etl_plan(state: ETLState) -> ETLState:
    logger.info("Executing ETL node: plan")
    res = etl_plan_start(
        session_id=state.get("session_id") or "default",
        business_rules=state.get("business_rules") or {},
        assessment_result=state.get("assessment_result"),
        engine=state.get("engine") or "python",
        sql_dialect=state.get("sql_dialect") or "tsql",
        generation_mode=state.get("generation_mode") or "full",
    )
    
    ok = bool(res.get("ok"))
    engine_eff = res.get("recommended_codegen_engine") or state.get("engine") or "python"
    dialect_eff = res.get("recommended_sql_dialect") or state.get("sql_dialect") or "tsql"
    
    return {
        "ok": ok,
        "plan": res.get("plan") or {},
        "preview": res.get("preview") or {},
        "engine_effective": engine_eff,
        "sql_dialect": dialect_eff,
        "error": res.get("error"),
        "message": res.get("message"),
    }

def _node_etl_confirm(state: ETLState) -> ETLState:
    logger.info("Executing ETL node: confirm")
    res = etl_confirm_plan(
        session_id=state.get("session_id") or "default",
        plan_override=state.get("plan"),
    )
    
    ok = bool(res.get("ok"))
    return {
        "ok": ok,
        "preview": res.get("preview") or state.get("preview") or {},
        "plan": res.get("approved_plan") or state.get("plan") or {},
        "lineage": res.get("lineage") or {},
        "error": res.get("error"),
        "message": res.get("message"),
    }

def _node_etl_generate(state: ETLState) -> ETLState:
    logger.info("Executing ETL node: generate")
    engine_eff = state.get("engine_effective") or state.get("engine") or "python"
    dialect_eff = state.get("sql_dialect") or "tsql"
    
    res = etl_generate_code(
        session_id=state.get("session_id") or "default",
        engine=engine_eff,
        sql_dialect=dialect_eff,
        generation_mode=state.get("generation_mode") or "full",
    )
    
    ok = bool(res.get("ok"))
    
    try:
        from agent.session_store import save_pipeline_run, get_latest_pipeline_run
        sid = state.get("session_id") or "default"
        prior = get_latest_pipeline_run(sid)
        dataset_names = list(state.get("plan", {}).get("datasets", {}).keys())
        if not dataset_names and prior:
            dataset_names = prior.get("dataset_names") or []
        schema_hash = prior.get("schema_hash", "") if prior else ""
        dq_score = prior.get("dq_score", 0) if prior else 0
        dq_issue_count = prior.get("dq_issue_count", 0) if prior else 0
        
        save_pipeline_run(
            session_id=sid,
            dataset_names=dataset_names,
            schema_hash=schema_hash,
            dq_score=dq_score,
            dq_issue_count=dq_issue_count,
            etl_phase="generated",
            etl_engine=engine_eff,
            etl_outcome="succeeded" if ok else "failed",
            generation_mode=state.get("generation_mode", ""),
            notes=res.get("message") or "",
        )
    except Exception as e:
        logger.warning(f"Failed to save pipeline run in _node_etl_generate: {e}")
        
    return {
        "ok": ok,
        "code": res.get("code") or "",
        "validation_ok": bool(res.get("validation_ok")),
        "validation_errors": res.get("validation_errors") or [],
        "generated_by": res.get("generated_by") or "template",
        "artifact_rel_path": res.get("artifact_rel_path") or "",
        "error": res.get("error"),
        "message": res.get("message"),
    }


def _node_etl_execute(state: ETLState) -> ETLState:
    logger.info("Executing ETL node: execute")
    res = etl_execute_sql(
        session_id=state.get("session_id") or "default",
        approved=True,
    )
    
    ok = bool(res.get("ok"))
    return {
        "ok": ok,
        "execution_result": res,
        "error": res.get("error"),
        "message": res.get("message"),
    }

def _route_after_plan(state: ETLState) -> str:
    if not state.get("ok"):
        return END
    if (state.get("generation_mode") or "full") == "plan_only":
        return END
    return "confirm"

def _route_after_confirm(state: ETLState) -> str:
    if not state.get("ok"):
        return END
    return "generate"

def _route_after_generate(state: ETLState) -> str:
    # Execute is opt-in for future use cases, default goes to END
    return END

def build_etl_graph(checkpointer=None):
    g = StateGraph(ETLState)
    g.add_node("plan", _node_etl_plan)
    g.add_node("confirm", _node_etl_confirm)
    g.add_node("generate", _node_etl_generate)
    g.add_node("execute", _node_etl_execute)
    
    g.set_entry_point("plan")
    
    g.add_conditional_edges("plan", _route_after_plan)
    g.add_conditional_edges("confirm", _route_after_confirm)
    g.add_conditional_edges("generate", _route_after_generate)
    g.add_edge("execute", END)
    
    return g.compile(checkpointer=checkpointer)

def run_etl_graph(
    session_id: str,
    generation_mode: str = "full",
    engine: str = "python",
    sql_dialect: str = "tsql",
    business_rules: Optional[Dict] = None,
    assessment_result: Optional[Dict] = None,
    checkpointer=None,
) -> ETLState:
    graph = build_etl_graph(checkpointer=checkpointer)
    initial_state: ETLState = {
        "session_id": session_id,
        "generation_mode": generation_mode,
        "engine": engine,
        "sql_dialect": sql_dialect,
        "business_rules": business_rules or {},
        "assessment_result": assessment_result,
    }
    
    # Run the graph using synchronous invocation
    # LangGraph state graph invoke returns the final state dict
    config = {"configurable": {"thread_id": session_id}} if checkpointer else None
    return graph.invoke(initial_state, config=config)
