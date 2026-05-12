"""
MCP runtime: configuration + in-process clients for the four data-source MCPs.

- **Servers** (stdio, for Cursor / Claude / Foundry MCP): `python -m mcp_server.mcp_azure_sql` etc.
- **Clients** (same Python process, no subprocess): use `InProcessMCPBridge` for orchestration code.

Environment (project root):
- `AGENT_DHARA_PROJECT_ROOT` — folder containing `main.py`
- `AGENT_DHARA_SOURCES_PATH` — path to `sources.yaml` (or env-based copy)
"""

from mcp_runtime.in_process_client import InProcessMCPBridge

__all__ = ["InProcessMCPBridge"]
