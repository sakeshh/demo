"""
MCP adapters used by the ExtractionAgent.

Your flow chart shows one "Extract Agent" that fans out to separate MCPs:
- Azure SQL MCP
- Blob MCP
- Local FS MCP
- Stream MCP

In this repo, the "MCP" functionality is already implemented as in-process wrappers
in `agent.mcp_interface.py` and shared loader helpers in `mcp_server.data_loaders`.
These adapters provide a clean, explicit separation per source type while still
reusing the existing project logic.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional


def _dump_config_text(cfg: Dict[str, Any]) -> str:
    try:
        import yaml  # type: ignore

        return yaml.safe_dump(cfg, sort_keys=False)
    except Exception:
        return json.dumps(cfg, indent=2)


def _single_location_config(source_root: Dict[str, Any], loc: Dict[str, Any]) -> str:
    src_name = source_root.get("name") or "source"
    cfg = {"source": {"name": src_name, "locations": [loc]}}
    return _dump_config_text(cfg)


class BaseExtractionMCP:
    """
    Minimal interface shared across source-specific MCP adapters.
    """

    kind: str = "base"

    def extract(self, *, source_root: Dict[str, Any], location: Dict[str, Any], job_id: Optional[str] = None, gx_enabled: bool = False) -> Dict[str, Any]:
        raise NotImplementedError


class AzureSQLMCP(BaseExtractionMCP):
    kind = "azure_sql"

    def __init__(self) -> None:
        from agent.mcp_interface import run_assessment  # type: ignore

        self._run_assessment = run_assessment

    def extract(self, *, source_root: Dict[str, Any], location: Dict[str, Any], job_id: Optional[str] = None, gx_enabled: bool = False) -> Dict[str, Any]:
        return self._run_assessment(_single_location_config(source_root, location), job_id=job_id, gx_enabled=gx_enabled)


class BlobMCP(BaseExtractionMCP):
    kind = "blob"

    def __init__(self) -> None:
        from agent.mcp_interface import run_assessment  # type: ignore

        self._run_assessment = run_assessment

    def extract(self, *, source_root: Dict[str, Any], location: Dict[str, Any], job_id: Optional[str] = None, gx_enabled: bool = False) -> Dict[str, Any]:
        return self._run_assessment(_single_location_config(source_root, location), job_id=job_id, gx_enabled=gx_enabled)


class LocalFSMCP(BaseExtractionMCP):
    kind = "local_fs"

    def __init__(self) -> None:
        from agent.mcp_interface import run_assessment  # type: ignore

        self._run_assessment = run_assessment

    def extract(self, *, source_root: Dict[str, Any], location: Dict[str, Any], job_id: Optional[str] = None, gx_enabled: bool = False) -> Dict[str, Any]:
        return self._run_assessment(_single_location_config(source_root, location), job_id=job_id, gx_enabled=gx_enabled)


class StreamMCP(BaseExtractionMCP):
    kind = "stream"

    def __init__(self) -> None:
        from agent.mcp_interface import process_stream_chunk  # type: ignore

        self._process_stream_chunk = process_stream_chunk

    def extract_records(self, *, records: List[Dict[str, Any]], name: str = "stream") -> Dict[str, Any]:
        return self._process_stream_chunk(records, name=name)

    def extract(self, *, source_root: Dict[str, Any], location: Dict[str, Any]) -> Dict[str, Any]:
        # Stream extraction needs payload (records or a file) and does not fit sources.yaml locations directly.
        raise ValueError("Stream extraction requires records; use StreamMCP.extract_records(...)")


def mcp_for_location_type(location_type: str) -> BaseExtractionMCP:
    """
    Factory used by ExtractionAgent. Maps sources.yaml location types to MCP adapters.
    """
    t = (location_type or "").lower().strip()
    if t in ("database", "azure_sql", "sql", "azure_sql_database"):
        return AzureSQLMCP()
    if t in ("azure_blob", "azure_blob_output", "blob"):
        return BlobMCP()
    if t in ("filesystem", "local", "local_fs"):
        return LocalFSMCP()
    if t in ("stream",):
        return StreamMCP()
    # Default to running through the core pipeline (acts like a generic MCP)
    return LocalFSMCP()

