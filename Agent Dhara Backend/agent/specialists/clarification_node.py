from __future__ import annotations

from typing import Any, Dict, List


def _list_datasets(context: Dict[str, Any]) -> List[str]:
    out: List[str] = []
    ctx = context or {}
    for k in ("selected_blob_files", "selected_local_files", "selected_tables"):
        for x in ctx.get(k) or []:
            s = str(x).strip()
            if s and s not in out:
                out.append(s)
    one = ctx.get("selected_table")
    if isinstance(one, str) and one.strip() and one.strip() not in out:
        out.insert(0, one.strip())
    return out


def format_clarification(user_message: str, context: Dict[str, Any]) -> str:
    """
    Exactly one short clarifying question (no full report).
    """
    ds = _list_datasets(context)
    last = str(context.get("last_ui_step") or context.get("selected_action") or "unknown")
    ds_line = ", ".join(f"`{d}`" for d in ds[:12]) if ds else "(none selected in this session yet)"

    low = (user_message or "").lower().strip()
    q: str
    if "compare" in low and len(ds) < 2:
        q = f"Which two datasets should I compare? Currently I only see: {ds_line}."
    elif len(low) <= 20 and ("this" in low or "too" in low or "it" in low or low in ("fix this.", "fix this")):
        q = f"Which file or dataset do you mean? Available in this session: {ds_line}."
    elif "better" in low or "again" in low:
        q = "Do you want a shorter issue list, a full narrative report, or deeper checks on one column?"
    else:
        q = f"Which dataset or issue should I focus on? Available: {ds_line}. (Last step: `{last}`.)"

    return (
        "### Quick clarification\n\n"
        f"You said: “{user_message.strip()}”\n\n"
        f"{q}\n\n"
        "_One answer from you is enough — I’ll stay focused after that._"
    )
