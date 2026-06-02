from __future__ import annotations

import os

import pandas as pd

from agent import etl_handlers as eh


def test_collect_etl_preview_datasets_from_ctx():
    ctx = {"etl_preview_datasets": {"ds1": pd.DataFrame({"x": [1]})}}
    out = eh._collect_etl_preview_datasets(ctx, {})
    assert list(out.keys()) == ["ds1"]


def test_maybe_build_duckdb_diff_not_sql_engine():
    r = eh._maybe_build_etl_duckdb_diff(eng="python", code="x", ok=True, ctx={}, assess={})
    assert r is None


def test_maybe_build_duckdb_diff_not_enabled():
    os.environ.pop("DHARA_ETL_DUCKDB_DIFF", None)
    os.environ.pop("DHARA_ETL_DUCKDB_AUTO_EXTRACT", None)
    ctx = {"etl_preview_datasets": {"t": pd.DataFrame({"a": [1]})}}
    r = eh._maybe_build_etl_duckdb_diff(eng="sql", code="SELECT 1", ok=True, ctx=ctx, assess={})
    assert isinstance(r, dict)
    assert r.get("skipped") is True
    assert r.get("reason") == "duckdb_diff_not_enabled"
