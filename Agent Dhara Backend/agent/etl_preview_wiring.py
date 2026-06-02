"""
Optional DuckDB preview + structural diff for generated ETL SQL (best-effort).

``preview_sql`` must reference DuckDB-registered table names (see ``preview_table_aliases``).
"""
from __future__ import annotations

import os
from typing import Any, Dict, Optional

import pandas as pd

from agent.duckdb_preview_runner import (
    duckdb_available,
    extract_duckdb_preview_sql,
    preview_generated_sql_against_assessment,
    preview_table_aliases,
)
from agent.etl_diff_engine import summarize_frame_diff


def build_duckdb_sql_preview_diff(
    sql_code: str,
    datasets: Dict[str, pd.DataFrame],
    *,
    preview_sql: Optional[str] = None,
    before_dataset_name: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Run DuckDB against ``preview_sql`` (or first SELECT extracted from ``sql_code``),
    then ``summarize_frame_diff`` between a source sample and the preview result.
    """
    if not datasets:
        return {"skipped": True, "reason": "no_datasets"}
    explicit = str(preview_sql or "").strip()
    extracted = extract_duckdb_preview_sql(sql_code) if not explicit else None
    sql_to_run = explicit or (extracted or "")
    if not sql_to_run:
        return {"skipped": True, "reason": "no_preview_sql"}

    if not duckdb_available():
        return {
            "skipped": True,
            "reason": "duckdb_not_installed",
            "preview_sql": sql_to_run[:500],
        }

    pr = preview_generated_sql_against_assessment(
        sql_to_run,
        datasets,
        return_dataframe=True,
    )
    if not pr.get("ok"):
        return {
            "skipped": True,
            "reason": pr.get("error") or "preview_failed",
            "preview": {k: v for k, v in pr.items() if k != "result_df"},
        }

    after_df = pr.get("result_df")
    if not isinstance(after_df, pd.DataFrame):
        return {
            "skipped": True,
            "reason": "no_result_frame",
            "preview": {k: v for k, v in pr.items() if k != "result_df"},
        }

    names = [k for k, v in datasets.items() if isinstance(v, pd.DataFrame)]
    if not names:
        return {"skipped": True, "reason": "no_dataframe_inputs"}
    before_key = before_dataset_name if before_dataset_name in names else names[0]
    before_full = datasets[before_key]
    try:
        cap = min(len(after_df), len(before_full), int(os.getenv("DHARA_DUCKDB_DIFF_BEFORE_ROWS", "50000")))
    except ValueError:
        cap = min(len(after_df), len(before_full), 50000)
    before_df = before_full.head(max(cap, 1))

    meta = {k: v for k, v in pr.items() if k != "result_df"}
    diff = summarize_frame_diff(before_df, after_df)
    return {
        "skipped": False,
        "preview": meta,
        "diff": diff,
        "before_dataset": str(before_key),
        "table_aliases": preview_table_aliases(datasets),
        "preview_sql_used": sql_to_run[:4000],
    }
