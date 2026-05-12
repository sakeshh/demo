"""MCP-facing wrapper functions for the Intelligent Data Assessment agent.

These helpers allow an external controller (e.g. data_assessment_agent MCP) to run
the core logic without CLI or file I/O. They accept plain Python primitives and
return JSON-serializable dicts/lists.
"""

import io
import json
import os
import sys
from typing import Any, Dict, List, Optional

import pandas as pd

_PARENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PARENT not in sys.path:
    sys.path.insert(0, _PARENT)

from agent.intelligent_data_assessment import (
    load_and_profile,
    profile_dataframe,
    analyze_dataset_quality,
    load_sql_datasets,
    load_file_datasets,
    load_dq_thresholds,
    _sql_location_key_prefix,
)

try:
    from connectors.azure_sql_pythonnet import AzureSQLPythonNetConnector
except ImportError:
    AzureSQLPythonNetConnector = None

try:
    from connectors.azure_blob_storage import AzureBlobStorageConnector
except Exception:
    AzureBlobStorageConnector = None  # type: ignore


def _parse_config_text(cfg_text: str) -> Dict[str, Any]:
    try:
        import yaml  # type: ignore
        cfg = yaml.safe_load(cfg_text) or {}
    except Exception:
        cfg = json.loads(cfg_text)

    def _expand_env(obj: Any) -> Any:
        import re as _re

        if isinstance(obj, dict):
            return {k: _expand_env(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [_expand_env(v) for v in obj]
        if not isinstance(obj, str):
            return obj
        pattern = _re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::([^}]*))?\}")

        def _sub(m: "_re.Match") -> str:
            var = m.group(1)
            default = m.group(2)
            val = os.environ.get(var)
            if val:
                return val
            if default is not None:
                return default
            return m.group(0)

        return pattern.sub(_sub, obj)

    return _expand_env(cfg)


def run_assessment(
    config_text: str,
    *,
    additional_data: Optional[Dict[str, Any]] = None,
    dq_thresholds_path: Optional[str] = None,
    job_id: Optional[str] = None,
    max_rows: Optional[int] = None,
    gx_enabled: bool = False,
) -> Dict[str, Any]:
    """Run the full data-quality assessment from the given config string.

    Config is the contents of sources.yaml/.json. additional_data is merged in
    (e.g. DataFrames loaded from Azure Blob). Returns the same structure as load_and_profile().
    """
    cfg = _parse_config_text(config_text)
    source_cfg = cfg.get("source", cfg) if isinstance(cfg, dict) else {}
    return load_and_profile(
        source_cfg,
        additional_data=additional_data or {},
        dq_thresholds_path=dq_thresholds_path,
        job_id=job_id,
        max_rows=max_rows,
        gx_enabled=gx_enabled,
    )


def load_selected_blob_datasets(
    config_text: str,
    *,
    location_index: int = 0,
    blob_names: Optional[List[str]] = None,
    max_rows: Optional[int] = None,
    max_bytes: Optional[int] = None,
) -> Dict[str, pd.DataFrame]:
    """
    Load specific blob(s) from a configured azure_blob location into DataFrames.

    - `location_index`: selects which `type: azure_blob` block (0-based among azure_blob locations)
    - `blob_names`: list of exact blob names to load. If None/empty, loads all blobs.
    """
    if AzureBlobStorageConnector is None:
        raise ImportError("azure-storage-blob connector not available")
    cfg = _parse_config_text(config_text)
    source_cfg = cfg.get("source", cfg) if isinstance(cfg, dict) else {}
    locs = list(source_cfg.get("locations", []) or [])
    blob_locs = [loc for loc in locs if (loc.get("type") or "").lower() == "azure_blob"]
    if not blob_locs:
        raise ValueError("No azure_blob locations configured")
    if location_index < 0 or location_index >= len(blob_locs):
        raise ValueError(f"Invalid location_index={location_index} (have {len(blob_locs)} azure_blob locations)")
    loc = blob_locs[location_index]
    conn_cfg = loc.get("connection", {}) or {}
    conn = AzureBlobStorageConnector(conn_cfg)
    if blob_names:
        names = [str(x) for x in blob_names if str(x).strip()]
        return conn.load_all_blobs(folder_prefix="", blobs=names, max_rows=max_rows, max_bytes=max_bytes)
    # Load all blobs in the container
    all_names = sorted(conn.list_blobs())
    return conn.load_all_blobs(folder_prefix="", blobs=all_names, max_rows=max_rows, max_bytes=max_bytes)


def list_tables(config_text: str) -> List[str]:
    """Return SQL dataset keys (matches load_and_profile when multiple databases)."""
    cfg = _parse_config_text(config_text)
    root = cfg.get("source", cfg) if isinstance(cfg, dict) else {}
    locs = root.get("locations", []) if isinstance(root, dict) else []
    db_locs = [loc for loc in locs if (loc.get("type") or "").lower() == "database"]
    multi = len(db_locs) > 1
    tables: List[str] = []
    for idx, loc in enumerate(db_locs):
        conn_cfg = loc.get("connection", {}) or {}
        if AzureSQLPythonNetConnector is None:
            tables.append("[SQL connector unavailable]")
            continue
        try:
            conn = AzureSQLPythonNetConnector(conn_cfg)
            discovered = conn.discover_tables()
        except Exception as e:
            tables.append(f"[error listing tables: {e}]")
            continue
        prefix = _sql_location_key_prefix(loc, conn_cfg, idx, multi)
        for t in discovered:
            tables.append(f"{prefix}{t}" if prefix else t)
    return tables


def process_stream_chunk(
    records: List[Dict[str, Any]],
    name: str = "stream",
) -> Dict[str, Any]:
    """Validate a batch of streaming records; returns profile + quality for the named dataset."""
    df = pd.DataFrame(records)
    profile = profile_dataframe(df)
    dq = analyze_dataset_quality(name, df, profile)
    return {"dataset": name, "profile": profile, "quality": dq}


def assess_dataframe(name: str, df: pd.DataFrame) -> Dict[str, Any]:
    """Run profiling and quality pipeline on a single DataFrame."""
    profile = profile_dataframe(df)
    dq = analyze_dataset_quality(name, df, profile)
    return {
        "datasets": {name: profile},
        "relationships": [],
        "data_quality_issues": {"datasets": {name: dq}, "global_issues": {}},
    }


def process_uploaded_file(file_bytes: bytes, filename: str) -> Dict[str, Any]:
    """Parse an uploaded file and run the assessment pipeline."""
    ext = os.path.splitext(filename)[1].lower()
    stream = io.BytesIO(file_bytes)

    if ext in (".csv", ".tsv"):
        df = pd.read_csv(stream, sep=None, engine="python")
    elif ext in (".json",):
        df = pd.read_json(stream, lines=False)
    elif ext in (".jsonl", ".ndjson"):
        df = pd.read_json(stream, lines=True)
    elif ext in (".parquet",):
        df = pd.read_parquet(stream)
    elif ext in (".xlsx", ".xls"):
        df = pd.read_excel(stream)
    else:
        raise ValueError(f"unsupported upload type: {ext}")

    return assess_dataframe(filename, df)


def load_path(path: str) -> Dict[str, pd.DataFrame]:
    """Load datasets from a filesystem path (directory of supported files)."""
    if os.path.isdir(path):
        return load_file_datasets(path)
    raise FileNotFoundError(f"Path not found or unsupported: {path}")


def read_file(path: str) -> str:
    """Return the text contents of a file (for agent to inspect reports)."""
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


