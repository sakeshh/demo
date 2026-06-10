from __future__ import annotations
import pytest
import time
from agent.session_store import (
    save_pipeline_run,
    get_latest_pipeline_run,
    get_pipeline_runs_for_datasets,
    _connect
)
from agent.improvement_narrator import build_improvement_narrative
from agent.mcp_server import api_pipeline_history

def test_pipeline_runs_crud():
    # Setup test DB tables (they should be auto-created by _connect)
    session_id = "test_run_sess"
    
    # Save a baseline run
    run_id1 = save_pipeline_run(
        session_id=session_id,
        dataset_names=["orders", "customers"],
        schema_hash="hash123",
        dq_score=80,
        dq_issue_count=5,
        etl_phase="assessed",
        notes="Some initial issues"
    )
    assert run_id1 is not None
    assert run_id1 > 0
    
    # Save a second run
    time.sleep(0.01) # ensure run_ts is slightly different
    run_id2 = save_pipeline_run(
        session_id=session_id,
        dataset_names=["orders"],
        schema_hash="hash123",
        dq_score=95,
        dq_issue_count=1,
        etl_phase="generated",
        etl_engine="python",
        etl_outcome="succeeded",
        generation_mode="full",
        notes="Generated cleanly"
    )
    assert run_id2 > run_id1

    # Get latest run
    latest = get_latest_pipeline_run(session_id)
    assert latest is not None
    assert latest["dq_score"] == 95
    assert latest["dataset_names"] == ["orders"]
    
    # Get latest run filtering by dataset that was in run1 but not run2
    latest_cust = get_latest_pipeline_run(session_id, dataset_names=["customers"])
    assert latest_cust is not None
    assert latest_cust["dq_score"] == 80
    assert "customers" in latest_cust["dataset_names"]

    # Get runs for datasets
    runs = get_pipeline_runs_for_datasets(["orders"], limit=5)
    assert len(runs) >= 2
    assert runs[0]["id"] == run_id2
    assert runs[1]["id"] == run_id1

def test_improvement_narrator():
    # First run narrative
    run1 = {
        "dq_score": 80,
        "dq_issue_count": 5,
        "schema_hash": "hash123",
        "run_ts": time.time()
    }
    
    narrative1 = build_improvement_narrative(run1, None)
    assert "Initial Run Baseline" in narrative1
    assert "80/100" in narrative1
    
    # Second run narrative (improved)
    run2 = {
        "dq_score": 95,
        "dq_issue_count": 1,
        "schema_hash": "hash123",
        "run_ts": time.time()
    }
    
    narrative2 = build_improvement_narrative(run2, run1)
    assert "DQ Score" in narrative2
    assert "95/100" in narrative2
    assert "decreased by 4 from 5" in narrative2
    assert "Schema**: Unchanged since last run" in narrative2
    
    # Schema change narrative
    run3 = {
        "dq_score": 90,
        "dq_issue_count": 2,
        "schema_hash": "hash456",
        "run_ts": time.time()
    }
    
    narrative3 = build_improvement_narrative(run3, run2)
    assert "Schema**: Schema changes detected!" in narrative3


def test_api_pipeline_history():
    session_id = "history_test_sess"
    
    save_pipeline_run(
        session_id=session_id,
        dataset_names=["orders"],
        schema_hash="hash1",
        dq_score=90,
        dq_issue_count=2,
    )
    
    res = api_pipeline_history(session_id)
    assert res["ok"] is True
    assert res["session_id"] == session_id
    assert len(res["history"]) >= 1
    assert res["history"][0]["dq_score"] == 90
