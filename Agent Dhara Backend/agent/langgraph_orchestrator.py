"""
LangGraph-based multi-agent orchestration for Agent Dhara Backend.

This module defines a small LangGraph workflow:
- Route user request (MasterAgent.plan)
- Extract per selected source location (ExtractionAgent, parallel)

**Note:** Interactive chat uses a separate graph in `agent.chat_graph` (including
`classify_intent` / conversational specialists); this orchestrator covers batch extraction/assessment flows.

The workflow is designed to be callable from:
- CLI glue code (future)
- FastAPI endpoints (future)
- other Python code (unit tests, scripts)
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, List, Optional, Sequence, TypedDict

try:
    from langgraph.graph import END, StateGraph
except Exception as e:  # pragma: no cover
    END = None  # type: ignore
    StateGraph = None  # type: ignore
    _LANGGRAPH_IMPORT_ERROR = e
else:
    _LANGGRAPH_IMPORT_ERROR = None

from agent.master_agent import MasterAgent
from agent.data_quality_agent import DataQualityAgent, dq_result_to_dict
from agent.dq_recommendations_agent import DQRecommendationsAgent, dq_recommendations_to_dict
from agent.transformation_suggester import suggest_transformations


class OrchestratorState(TypedDict, total=False):
    """
    Shared state passed between LangGraph nodes.
    """

    # Inputs
    user_request: str
    sources_path: str
    selected_sources: List[str]
    stream_records: List[Dict[str, Any]]
    stream_name: str
    job_id: str
    gx_enabled: bool

    # Derived / intermediate
    plan: Dict[str, Any]
    selected_location_count: int

    # Outputs
    extractions: List[Dict[str, Any]]
    extraction_errors: List[Dict[str, Any]]
    data_quality: Dict[str, Any]
    dq_recommendations: Dict[str, Any]
    transform_suggestions: Dict[str, Any]
    timings: Dict[str, Any]
    request_id: str


def _merge_timings(state: OrchestratorState, extra: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(state.get("timings") or {})
    out.update(extra or {})
    return out
def _node_route(state: OrchestratorState) -> OrchestratorState:
    t0 = time.time()
    master = MasterAgent()
    p = master.plan(state.get("user_request", ""))
    out: OrchestratorState = {
        "plan": {
            "do_extract": p.do_extract,
            "do_dq_check": p.do_dq_check,
            "do_dq_recommendations": p.do_dq_recommendations,
            "do_transform": p.do_transform,
        },
    }
    out["timings"] = _merge_timings(state, {"route_ms": int((time.time() - t0) * 1000)})
    return out


async def _node_extract_async(state: OrchestratorState) -> OrchestratorState:
    t0 = time.time()
    master = MasterAgent()
    source_root, locations = master.load_and_select_sources(
        sources_path=state.get("sources_path", "config/sources.yaml"),
        selected_sources=state.get("selected_sources") or None,
        user_request=state.get("user_request") or "",
    )

    extraction_agent = master.registry["extraction"]
    results, errors = await extraction_agent.extract_many(
        source_root=source_root,
        locations=locations,
        parallel=True,
        stream_records=state.get("stream_records"),
        stream_name=state.get("stream_name") or "stream",
        job_id=state.get("job_id"),
        gx_enabled=state.get("gx_enabled", False),
    )

    # Normalize to JSON-serializable output (no dataclasses)
    extractions_out: List[Dict[str, Any]] = []
    for r in results:
        extractions_out.append(
            {
                "source": r.source_name,
                "location_type": r.location_type,
                "result": r.result,
            }
        )

    return {
        "selected_location_count": len(locations),
        "extractions": extractions_out,
        "extraction_errors": errors,
        "timings": _merge_timings(state, {"extract_ms": int((time.time() - t0) * 1000)}),
    }


def _node_extract(state: OrchestratorState) -> OrchestratorState:
    """
    Sync wrapper around the async extraction node for LangGraph.
    """
    return asyncio.run(_node_extract_async(state))


def _node_dq_check(state: OrchestratorState) -> OrchestratorState:
    t0 = time.time()
    dq_agent = DataQualityAgent()
    extractions = state.get("extractions") or []
    merged = dq_agent.run_from_extractions(extractions)
    return {
        "data_quality": dq_result_to_dict(merged),
        "timings": _merge_timings(state, {"dq_check_ms": int((time.time() - t0) * 1000)}),
    }


def _node_dq_recommend(state: OrchestratorState) -> OrchestratorState:
    """
    LLM-assisted cleaning recommendations based on merged DQ issues.
    """
    t0 = time.time()
    dq = state.get("data_quality") or {}
    agent = DQRecommendationsAgent()
    rec, _usage = agent.recommend(merged_dq=dq, user_intent=state.get("user_request") or "")
    return {
        "dq_recommendations": dq_recommendations_to_dict(rec),
        "timings": _merge_timings(state, {"dq_recommend_ms": int((time.time() - t0) * 1000)}),
    }


def _node_transform_suggest(state: OrchestratorState) -> OrchestratorState:
    """
    Build transformation suggestions per extracted source.
    """
    t0 = time.time()
    extractions = state.get("extractions") or []
    out_by_source: Dict[str, Any] = {}
    for ex in extractions:
        source = str(ex.get("source") or ex.get("source_name") or "source")
        res = ex.get("result") if isinstance(ex.get("result"), dict) else {}
        if not isinstance(res, dict):
            out_by_source[source] = {"error": "Missing extraction result"}
            continue
        try:
            out_by_source[source] = suggest_transformations(res)
        except Exception as e:
            out_by_source[source] = {"error": str(e)}
    return {
        "transform_suggestions": {"sources": out_by_source},
        "timings": _merge_timings(state, {"transform_suggest_ms": int((time.time() - t0) * 1000)}),
    }


def _route_after_plan(state: OrchestratorState) -> str:
    plan = state.get("plan") or {}
    do_extract = bool(plan.get("do_extract", True))
    do_dq = bool(plan.get("do_dq_check", True))
    do_rec = bool(plan.get("do_dq_recommendations", False))
    do_transform = bool(plan.get("do_transform", False))

    # If extraction is requested, always do it first.
    if do_extract:
        return "extract"

    # If caller provided extractions in state (e.g. from a session), allow DQ/transform without re-extract.
    if (state.get("extractions") or []) and do_dq:
        return "dq_check"
    if (state.get("extractions") or []) and do_rec:
        return "dq_recommend"
    if (state.get("extractions") or []) and do_transform:
        return "transform_suggest"
    return END  # type: ignore[return-value]


def _route_after_extract(state: OrchestratorState) -> str:
    plan = state.get("plan") or {}
    do_dq = bool(plan.get("do_dq_check", True))
    do_rec = bool(plan.get("do_dq_recommendations", False))
    do_transform = bool(plan.get("do_transform", False))
    if do_dq:
        return "dq_check"
    if do_rec:
        # Recommendations depend on merged DQ output.
        return "dq_check"
    if do_transform:
        return "transform_suggest"
    return END  # type: ignore[return-value]


def _route_after_dq(state: OrchestratorState) -> str:
    plan = state.get("plan") or {}
    do_rec = bool(plan.get("do_dq_recommendations", False))
    do_transform = bool(plan.get("do_transform", False))
    if do_rec:
        return "dq_recommend"
    return "transform_suggest" if do_transform else END  # type: ignore[return-value]


def _route_after_dq_recommend(state: OrchestratorState) -> str:
    plan = state.get("plan") or {}
    do_transform = bool(plan.get("do_transform", False))
    return "transform_suggest" if do_transform else END  # type: ignore[return-value]


def build_orchestrator_graph():
    """
    Build and compile the LangGraph orchestrator.
    """
    if _LANGGRAPH_IMPORT_ERROR is not None or StateGraph is None:
        raise ImportError(
            "LangGraph is not installed (or failed to import). "
            "Install with: pip install -r requirements.txt"
        ) from _LANGGRAPH_IMPORT_ERROR
    g = StateGraph(OrchestratorState)
    g.add_node("route", _node_route)
    g.add_node("extract", _node_extract)
    g.add_node("dq_check", _node_dq_check)
    g.add_node("dq_recommend", _node_dq_recommend)
    g.add_node("transform_suggest", _node_transform_suggest)

    g.set_entry_point("route")
    g.add_conditional_edges("route", _route_after_plan)
    g.add_conditional_edges("extract", _route_after_extract)
    g.add_conditional_edges("dq_check", _route_after_dq)
    g.add_conditional_edges("dq_recommend", _route_after_dq_recommend)
    g.add_edge("transform_suggest", END)
    return g.compile()


def run_orchestrator(
    *,
    user_request: str,
    sources_path: str = "config/sources.yaml",
    selected_sources: Optional[Sequence[str]] = None,
    stream_records: Optional[List[Dict[str, Any]]] = None,
    stream_name: str = "stream",
    request_id: str = "",
    job_id: str = "",
    gx_enabled: bool = False,
) -> Dict[str, Any]:
    """
    High-level convenience wrapper.
    """
    graph = build_orchestrator_graph()
    final = graph.invoke(
        {
            "user_request": user_request,
            "sources_path": sources_path,
            "selected_sources": list(selected_sources or []),
            "stream_records": stream_records,
            "stream_name": stream_name,
            "request_id": request_id or "",
            "job_id": job_id or "",
            "gx_enabled": gx_enabled,
            "timings": {},
        }
    )
    return dict(final)

