# Agent Dhara — Bug Fixes (2026-05-07)

## Problem

Typing a bare source keyword like `blob` on a fresh session caused the agent to
enter **report-clarification mode** even though no data source had been selected
and no assessment had been run. The UI showed:

- `Available: (none selected in this session yet)`
- `Last step: unknown`

This was a dead-end — no buttons, no way forward without refreshing the page.

---

## Root Causes

| # | File | Issue |
|---|------|-------|
| 1 | `router_orchestrator.py` | `normalize_source_message()` and `guard_fresh_session_fallback()` existed in `routing_guards.py` but were **never imported or called** in the orchestrator. |
| 2 | `routing_guards.py` | `guard_fresh_session_fallback()` did not exist — only `guard_needs_source()` and `guard_needs_assessment()` were present, and they were not called from the main routing path. |
| 3 | `session_store.py` | New sessions were created without a `last_step` key, so it defaulted to `None`/`"unknown"` instead of `"awaiting_source_selection"`. The guard could not distinguish a fresh session from a mid-flow session. |

---

## Fixes Applied

### `routing_guards.py`
- Added `guard_fresh_session_fallback(msg, ctx)`: fires before any routing for
  fully empty sessions; returns source-selection options immediately.
- Extended `_SOURCE_ALIASES` with more aliases (`csv`, `excel`, `parquet`,
  `adls`, `s3`, `postgres`, `mysql`, `mssql`, `sqlite`, `storage`, `files`).
- `guard_needs_source()` now has a clear docstring explaining the change:
  it blocks ALL non-navigation actions by default (not just an optional
  allow-list subset).
- All `payload` dicts now include `current_step` alongside `step` for
  frontend compatibility.

### `router_orchestrator.py`
- Added **Layer 0**: imports and calls `guard_fresh_session_fallback()` before
  any other layer. Returns a guided source-selection response if fired.
- Added **Layer 0b**: calls `normalize_source_message()` to rewrite bare
  source keywords before the keyword classifier runs.

### `session_store.py`
- Added `_DEFAULT_SESSION_PAYLOAD` constant: new sessions initialise
  `last_step` as `"awaiting_source_selection"` instead of being absent.
- `load_session()` back-fills `last_step` for older sessions where the value
  is `None`, `""`, or `"unknown"` and no source has been selected.
- Added `reset_session(session_id)` helper for clean resets from chat.

---

## Correct Flow After Fix

```
User types: "blob"
    ↓
Layer 0b  normalize_source_message()  →  "select source blob"
    ↓
Layer 2a  keyword classifier          →  intent: select_source, source: blob
    ↓
Agent sets selected_source = "blob", last_step = "list_blob_files"
    ↓
UI shows blob file listing
```

If the user types something completely unrecognised on a fresh session:

```
User types: "what is my data quality?"
    ↓
Layer 0  guard_fresh_session_fallback()  →  source-selection buttons shown
    ↓
User clicks "Azure Blob"
    ↓
normal flow continues
```
