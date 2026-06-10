from __future__ import annotations
import pytest
from unittest.mock import patch, MagicMock
from agent.unified_graph import build_unified_graph, run_unified_graph
from agent.master_agent import Plan

@patch("agent.unified_graph.build_orchestrator_graph")
@patch("agent.unified_graph.build_etl_graph")
def test_build_unified_graph_compiles(mock_build_etl, mock_build_assess):
    # Setup mocks to return dummy graph instances
    mock_assess_g = MagicMock()
    mock_etl_g = MagicMock()
    mock_build_assess.return_value = mock_assess_g
    mock_build_etl.return_value = mock_etl_g
    
    g = build_unified_graph()
    assert g is not None

@patch("agent.unified_graph.build_unified_graph")
def test_run_unified_graph(mock_build_graph):
    mock_graph = MagicMock()
    mock_build_graph.return_value = mock_graph
    
    # State mock output
    mock_graph.invoke.return_value = {
        "ok": True,
        "session_id": "test_unified",
        "dq_score": 90,
        "etl_code": "print('etl')"
    }
    
    res = run_unified_graph(
        session_id="test_unified",
        user_request="assess and generate etl",
    )
    
    assert res["ok"] is True
    assert res["dq_score"] == 90
    assert res["etl_code"] == "print('etl')"
    mock_build_graph.assert_called_once()

@patch("agent.session_store.get_latest_pipeline_run")
@patch("agent.master_agent.MasterAgent.plan_with_memory")
def test_unified_route_node(mock_plan, mock_get_run):
    from agent.unified_graph import _node_unified_route
    
    mock_get_run.return_value = {"id": 1, "dq_score": 90, "schema_hash": "abc"}
    mock_plan.return_value = Plan(
        do_extract=False,
        do_dq_check=False,
        do_etl_plan=False,
        do_etl_generate=True,
        skip_extract=True
    )
    
    state = {
        "session_id": "test_sess",
        "user_request": "continue etl"
    }
    
    new_state = _node_unified_route(state)
    assert new_state["prior_run"] == {"id": 1, "dq_score": 90, "schema_hash": "abc"}
    assert new_state["routing_plan"]["skip_extract"] is True
    assert new_state["routing_plan"]["do_etl_generate"] is True

@patch("agent.session_store.save_pipeline_run")
@patch("agent.session_store.get_latest_pipeline_run")
def test_narrate_node(mock_get_run, mock_save_run):
    from agent.unified_graph import _node_narrate
    
    mock_get_run.return_value = None
    
    state = {
        "session_id": "test_sess",
        "routing_plan": {"resume_from": "assessed"},
        "extractions": [
            {
                "result": {
                    "datasets": {
                        "orders": {
                            "columns": {}
                        }
                    }
                }
            }
        ]
    }
    
    new_state = _node_narrate(state)
    assert new_state["dq_score"] is not None
    assert new_state["schema_hash"] is not None
    assert "improvement_narrative" in new_state
    assert mock_save_run.call_count == 1

