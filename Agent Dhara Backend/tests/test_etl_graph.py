from __future__ import annotations
import pytest
from unittest.mock import patch, MagicMock
from agent.etl_graph import build_etl_graph, run_etl_graph

@patch("agent.etl_graph.etl_plan_start")
@patch("agent.etl_graph.etl_confirm_plan")
@patch("agent.etl_graph.etl_generate_code")
@patch("agent.etl_graph.etl_execute_sql")
def test_build_etl_graph_compiles(mock_execute, mock_generate, mock_confirm, mock_plan):
    graph = build_etl_graph()
    assert graph is not None

def test_etl_state_partial_fields():
    # Verify typing/dict interface works as expected
    from agent.etl_graph import ETLState
    state: ETLState = {"session_id": "test_sess", "ok": True}
    assert state["session_id"] == "test_sess"
    assert state["ok"] is True

@patch("agent.etl_graph.etl_plan_start")
@patch("agent.etl_graph.etl_confirm_plan")
@patch("agent.etl_graph.etl_generate_code")
def test_plan_only_mode_stops_at_end(mock_generate, mock_confirm, mock_plan):
    mock_plan.return_value = {
        "ok": True,
        "plan": {"plan_id": "plan1"},
        "preview": {"preview_id": "preview1"},
        "recommended_codegen_engine": "python",
        "recommended_sql_dialect": "tsql"
    }
    
    res = run_etl_graph(
        session_id="test_sess",
        generation_mode="plan_only",
        engine="python"
    )
    
    assert res["ok"] is True
    assert res["plan"] == {"plan_id": "plan1"}
    assert res["preview"] == {"preview_id": "preview1"}
    assert mock_plan.call_count == 1
    assert mock_confirm.call_count == 0
    assert mock_generate.call_count == 0

@patch("agent.etl_graph.etl_plan_start")
@patch("agent.etl_graph.etl_confirm_plan")
@patch("agent.etl_graph.etl_generate_code")
def test_full_mode_runs_all_nodes(mock_generate, mock_confirm, mock_plan):
    mock_plan.return_value = {
        "ok": True,
        "plan": {"plan_id": "plan1"},
        "preview": {"preview_id": "preview1"},
        "recommended_codegen_engine": "python",
        "recommended_sql_dialect": "tsql"
    }
    mock_confirm.return_value = {
        "ok": True,
        "approved_plan": {"plan_id": "plan1", "approved": True},
        "preview": {"preview_id": "preview1"},
        "lineage": {"col1": "src1"}
    }
    mock_generate.return_value = {
        "ok": True,
        "code": "print('hello')",
        "validation_ok": True,
        "validation_errors": [],
        "generated_by": "llm",
        "artifact_rel_path": "output/etl_code/test.py"
    }
    
    res = run_etl_graph(
        session_id="test_sess",
        generation_mode="full",
        engine="python"
    )
    
    assert res["ok"] is True
    assert res["code"] == "print('hello')"
    assert res["validation_ok"] is True
    assert res["lineage"] == {"col1": "src1"}
    assert mock_plan.call_count == 1
    assert mock_confirm.call_count == 1
    assert mock_generate.call_count == 1

@patch("agent.etl_graph.etl_plan_start")
@patch("agent.etl_graph.etl_confirm_plan")
@patch("agent.etl_graph.etl_generate_code")
def test_failed_plan_stops_graph(mock_generate, mock_confirm, mock_plan):
    mock_plan.return_value = {
        "ok": False,
        "error": "NO_ASSESSMENT",
        "message": "Error occurred"
    }
    
    res = run_etl_graph(
        session_id="test_sess",
        generation_mode="full",
        engine="python"
    )
    
    assert res["ok"] is False
    assert res["error"] == "NO_ASSESSMENT"
    assert res["message"] == "Error occurred"
    assert mock_plan.call_count == 1
    assert mock_confirm.call_count == 0
    assert mock_generate.call_count == 0

@patch("agent.etl_graph.etl_plan_start")
def test_node_maps_handler_response(mock_plan):
    from agent.etl_graph import _node_etl_plan, ETLState
    mock_plan.return_value = {
        "ok": True,
        "plan": {"key": "val"},
        "preview": {"key": "val"},
        "recommended_codegen_engine": "sql",
        "recommended_sql_dialect": "ansi",
        "error": "some_warning",
        "message": "warning message"
    }
    
    state: ETLState = {
        "session_id": "test_sess",
        "engine": "python",
        "sql_dialect": "tsql",
        "generation_mode": "full"
    }
    
    new_state = _node_etl_plan(state)
    assert new_state["ok"] is True
    assert new_state["plan"] == {"key": "val"}
    assert new_state["engine_effective"] == "sql"
    assert new_state["sql_dialect"] == "ansi"
    assert new_state["error"] == "some_warning"
    assert new_state["message"] == "warning message"
