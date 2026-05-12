"""
routing_guards.py
-----------------
Centralised pre-dispatch guards and message normalisation helpers used by
chat_graph.py and router_orchestrator.py.

This file is imported to:
- normalise bare source keywords like "blob" → "select source blob" BEFORE LLM routing
- block report-only actions when no assessment exists
- block ANY non-navigation action when no source has been selected yet
- provide a fresh-session fallback that sends the user to source selection
- keep the set of context keys to clear on reset_flow in a single place

FIX LOG (2026-05-07)
---------------------
- guard_fresh_session_fallback() added: catches 100% empty-context turns and
  returns source-selection options before any routing layer runs.
- guard_needs_source() now fires for ALL non-navigation actions (not just an
  optional allow-list), matching the intent that source selection is mandatory.
- normalize_source_message() unchanged (already correct).
- guard_needs_assessment() unchanged (already correct).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Actions that require a completed assessment in session context.
# ---------------------------------------------------------------------------
REPORT_ACTIONS: frozenset = frozenset({
    "summarize_report",
    "dq_overview",
    "dq_duplicates",
    "show_null_columns",
    "relationships_overview",
    "extract_columns",
    "show_cleaning_recommendations",
    "show_transform_suggestions",
})

# ---------------------------------------------------------------------------
# Context keys that must be wiped on reset_flow / new chat.
# ---------------------------------------------------------------------------
RESET_CONTEXT_KEYS: List[str] = [
    "selected_source",
    "selected_blob_files",
    "selected_local_files",
    "selected_tables",
    "selected_table",
    "last_assessment_result",
    "last_assessment_signature",
    "last_assessment_datasets",
    "last_step",
    "selected_db_location_index",
    "selected_blob_location_index",
    "selected_fs_location_index",
]

# ---------------------------------------------------------------------------
# Source keyword normalisation — maps bare user input to deterministic commands.
# ---------------------------------------------------------------------------
_SOURCE_ALIASES: Dict[str, str] = {
    "blob":          "select source blob",
    "azure blob":    "select source blob",
    "azure":         "select source blob",
    "database":      "select source database",
    "sql":           "select source database",
    "db":            "select source database",
    "azure sql":     "select source database",
    "local":         "select source local",
    "filesystem":    "select source local",
    "local files":   "select source local",
    "local file":    "select source local",
    "files":         "select source local",
    "csv":           "select source local",
    "excel":         "select source local",
    "parquet":       "select source local",
    "s3":            "select source blob",
    "storage":       "select source blob",
    "adls":          "select source blob",
    "postgres":      "select source database",
    "mysql":         "select source database",
    "mssql":         "select source database",
    "sqlite":        "select source database",
}


def normalize_source_message(msg: str, ctx: Dict[str, Any]) -> str:
    """
    Expand bare source keywords to deterministic commands on fresh sessions.
    Only fires when no source has been selected yet.
    """
    if ctx.get("selected_source"):
        return msg  # source already set — never override
    stripped = (msg or "").strip().lower()
    return _SOURCE_ALIASES.get(stripped, msg)


def _flow_options_minimal() -> List[Dict[str, str]]:
    """Source-selection buttons for guard replies."""
    return [
        {"id": "blob",  "text": "\u2601\ufe0f Azure Blob",  "send": "select source blob"},
        {"id": "db",    "text": "\U0001f5c4\ufe0f Database",    "send": "select source database"},
        {"id": "local", "text": "\U0001f4c1 Local Files", "send": "select source local"},
    ]


def guard_fresh_session_fallback(msg: str, ctx: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    NEW FIX: If the session is completely fresh (no source, no assessment,
    last_step is unknown/missing) and the user sends anything that is NOT
    already a deterministic source-selection command, return a guided
    source-selection response immediately.

    This prevents the router from ever entering report-clarification mode
    before the workflow is initialised.
    """
    if ctx.get("selected_source"):
        return None  # session already in progress
    if ctx.get("last_assessment_result"):
        return None  # assessment already exists

    stripped = (msg or "").strip().lower()

    # These are already deterministic — let them pass through to the router
    _PASS_THROUGH_PREFIXES = (
        "select source",
        "restart",
        "reset",
        "help",
        "back",
        "hi",
        "hello",
        "hey",
        "start",
        "begin",
    )
    if any(stripped.startswith(p) for p in _PASS_THROUGH_PREFIXES):
        return None

    # If the message is a known source alias it will have already been
    # normalised to "select source X" by normalize_source_message() — so it
    # will match the prefix check above.  Any other text in a fresh session
    # should be caught here and guided to source selection.
    last_step = (ctx.get("last_step") or "unknown").strip()
    if last_step in ("unknown", "", "awaiting_source_selection"):
        return {
            "reply": (
                "\U0001f44b Welcome to Agent Dhara!\n\n"
                "Please choose a data source to get started:"
            ),
            "payload": {
                "step": "select_source",
                "current_step": "select_source",
                "options": _flow_options_minimal(),
            },
        }

    return None


def guard_needs_assessment(action: str, ctx: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    If `action` is a report-only action but no assessment exists in context,
    return a ready-made reply that guides the user back to source/assessment.
    Otherwise return None to let dispatch continue.
    """
    if action not in REPORT_ACTIONS:
        return None
    if ctx.get("last_assessment_result"):
        return None

    source_selected = ctx.get("selected_source")
    if source_selected:
        # Source chosen but assessment not run yet
        reply = (
            "\u26a0\ufe0f No assessment has been run yet for the selected source.\n"
            "Please select your files / tables and run an assessment first."
        )
        return {
            "reply": reply,
            "payload": {
                "step": "awaiting_assessment",
                "current_step": "awaiting_assessment",
                "options": [
                    {"id": "assess",  "text": "\U0001f680 Run Assessment", "send": "assess selected files"},
                    {"id": "back",    "text": "\U0001f519 Back",           "send": "back"},
                    {"id": "restart", "text": "\u2705 Restart",           "send": "restart"},
                ],
            },
        }

    # No source at all — restart from the top
    reply = (
        "\u26a0\ufe0f No data source selected yet.\n"
        "Please choose a source to get started."
    )
    return {
        "reply": reply,
        "payload": {
            "step": "select_source",
            "current_step": "select_source",
            "options": _flow_options_minimal(),
        },
    }


# ---------------------------------------------------------------------------
# Navigation actions that are ALWAYS allowed regardless of session state.
# ---------------------------------------------------------------------------
_NAV_ACTIONS: frozenset = frozenset({
    "help",
    "reset_flow",
    "back_flow",
    "list_sources",
    "select_source",
    "show_selection_status",
    "restart",
    "greeting",
})


def guard_needs_source(
    action: str,
    ctx: Dict[str, Any],
    source_required_actions: Optional[frozenset] = None,
) -> Optional[Dict[str, Any]]:
    """
    Block non-navigation actions when no selected_source exists in context.

    FIX: The previous version had an optional `source_required_actions` allow-list
    that let many actions bypass this guard when the list was None.  The guard
    now fires for ALL non-navigation actions by default, which is the correct
    behaviour — nothing meaningful can happen until a source is selected.
    """
    if action in _NAV_ACTIONS:
        return None
    if ctx.get("selected_source"):
        return None

    # Optional explicit allow-list (kept for backwards compat but defaults to block-all)
    if source_required_actions is not None and action not in source_required_actions:
        return None

    return {
        "reply": "\u26a0\ufe0f Please select a data source first.",
        "payload": {
            "step": "select_source",
            "current_step": "select_source",
            "options": _flow_options_minimal(),
        },
    }
