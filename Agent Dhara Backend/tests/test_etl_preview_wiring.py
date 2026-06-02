from __future__ import annotations

import pandas as pd
import pytest

from agent.etl_preview_wiring import build_duckdb_sql_preview_diff


def test_preview_diff_skips_without_duckdb(monkeypatch):
    monkeypatch.setattr("agent.etl_preview_wiring.duckdb_available", lambda: False)
    df = pd.DataFrame({"x": [1, 2]})
    r = build_duckdb_sql_preview_diff("SELECT 1 AS x", {"t": df}, preview_sql="SELECT 1 AS x")
    assert r.get("skipped") is True
    assert r.get("reason") == "duckdb_not_installed"


def test_preview_diff_skips_no_sql():
    df = pd.DataFrame({"x": [1]})
    r = build_duckdb_sql_preview_diff("/* no select */", {"t": df})
    assert r.get("skipped") is True
    assert r.get("reason") == "no_preview_sql"


def test_preview_diff_runs_with_duckdb_when_installed():
    pytest.importorskip("duckdb")
    df = pd.DataFrame({"x": [1, 2, 3]})
    r = build_duckdb_sql_preview_diff("--", {"orders": df}, preview_sql="SELECT * FROM orders")
    assert r.get("skipped") is False
    assert "diff" in r
    assert r["diff"]["after_rows"] >= 1
