"""
DuckDB sandbox for previewing generated SQL on local files or in-memory frames.
Optional dependency: duckdb (install separately if not present).
"""
from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

logger = logging.getLogger(__name__)


def _sanitize_table_name(ds_name: str) -> str:
    safe = "".join(c if c.isalnum() or c == "_" else "_" for c in str(ds_name))[:60] or "t"
    if safe[0].isdigit():
        safe = "t_" + safe
    return safe


def preview_table_aliases(datasets: Dict[str, pd.DataFrame]) -> Dict[str, str]:
    """Map original dataset name -> DuckDB-registered identifier."""
    return {str(k): _sanitize_table_name(str(k)) for k in (datasets or {}).keys()}


def extract_duckdb_preview_sql(full_sql: str) -> Optional[str]:
    """
    Best-effort: first SELECT-only statement for DuckDB (won't parse T-SQL GO batches).
    """
    if not full_sql or not str(full_sql).strip():
        return None
    s = re.sub(r"/\*.*?\*/", "", str(full_sql), flags=re.S).strip()
    if not s:
        return None
    lower = s.lower()
    pos = lower.find("select")
    if pos < 0:
        return None
    tail = s[pos:]
    parts = [p.strip() for p in tail.split(";") if p.strip()]
    for p in parts:
        if re.match(r"(?is)^select\b", p):
            return p
    return parts[0] if parts else None


def duckdb_available() -> bool:
    try:
        import duckdb  # noqa: F401

        return True
    except ImportError:
        return False


def run_duckdb_sql_preview(
    sql: str,
    *,
    tables: Optional[Dict[str, pd.DataFrame]] = None,
    file_paths: Optional[Dict[str, str]] = None,
    dialect_hint: str = "ansi",
    return_dataframe: bool = False,
) -> Dict[str, Any]:
    """
    Execute SQL in an ephemeral DuckDB database.

    - `tables`: map logical table name -> DataFrame (registered as view).
    - `file_paths`: map logical name -> path (CSV/Parquet); registered as read_* view.

    Returns { ok, error?, columns?, rowcount_sample?, sql_executed }
    """
    if not duckdb_available():
        return {"ok": False, "error": "duckdb_not_installed", "sql_executed": sql[:2000]}

    import duckdb as ddb

    tables = tables or {}
    file_paths = file_paths or {}
    con: Any = None
    try:
        con = ddb.connect(database=":memory:")
        for name, df in tables.items():
            if isinstance(df, pd.DataFrame) and not df.empty:
                con.register(str(name).replace('"', ""), df)
        for name, path in (file_paths or {}).items():
            p = Path(path)
            if not p.is_file():
                continue
            nm = str(name).replace('"', "")
            suf = p.suffix.lower()
            if suf == ".parquet":
                con.execute(f'DROP VIEW IF EXISTS "{nm}"')
                con.execute(f'CREATE VIEW "{nm}" AS SELECT * FROM read_parquet(?)', [str(p)])
            elif suf in (".csv", ".txt"):
                con.execute(f'DROP VIEW IF EXISTS "{nm}"')
                con.execute(f'CREATE VIEW "{nm}" AS SELECT * FROM read_csv_auto(?)', [str(p)])

        cur = con.execute(sql)
        try:
            rel = cur.df()
        except AttributeError:
            rel = cur.fetchdf()
        sample = rel.head(int(os.getenv("DHARA_DUCKDB_PREVIEW_ROWS", "50")))
        out: Dict[str, Any] = {
            "ok": True,
            "columns": [str(c) for c in sample.columns],
            "rowcount_sample": int(len(sample)),
            "rowcount_full": int(len(rel)),
            "dialect_hint": dialect_hint,
            "sql_executed": sql[:8000],
        }
        if return_dataframe:
            try:
                cap = int(os.getenv("DHARA_DUCKDB_RESULT_MAX_ROWS", "10000"))
            except ValueError:
                cap = 10000
            out["result_df"] = rel.head(cap).copy()
        return out
    except Exception as e:
        logger.warning("duckdb preview failed: %s", e)
        return {"ok": False, "error": str(e), "sql_executed": sql[:2000]}
    finally:
        if con is not None:
            try:
                con.close()
            except Exception:
                pass


def preview_generated_sql_against_assessment(
    sql: str,
    datasets: Dict[str, pd.DataFrame],
    *,
    sample_rows: Optional[int] = None,
    return_dataframe: bool = False,
) -> Dict[str, Any]:
    """
    Convenience: register each assessed dataset under a sanitized name and run SQL.
    """
    if not datasets:
        return {"ok": False, "error": "no_datasets"}
    n = sample_rows
    if n is None:
        try:
            n = int(os.getenv("DHARA_DUCKDB_SAMPLE_ROWS", "5000"))
        except ValueError:
            n = 5000
    tables: Dict[str, pd.DataFrame] = {}
    for ds_name, df in datasets.items():
        if not isinstance(df, pd.DataFrame):
            continue
        safe = _sanitize_table_name(str(ds_name))
        tables[safe] = df.head(n) if len(df) > n else df
    return run_duckdb_sql_preview(sql, tables=tables, return_dataframe=return_dataframe)
