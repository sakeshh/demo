from __future__ import annotations

from typing import Any, Dict, Optional


def _dq_totals(result: Optional[Dict[str, Any]]) -> str:
    if not isinstance(result, dict):
        return ""
    dq = result.get("data_quality_issues") or {}
    per = dq.get("datasets") if isinstance(dq, dict) else None
    if not isinstance(per, dict) or not per:
        return ""
    hi = me = lo = 0
    for _, block in per.items():
        summ = (block or {}).get("summary") or {}
        if isinstance(summ, dict):
            try:
                hi += int(summ.get("high_severity") or 0)
                me += int(summ.get("medium_severity") or 0)
                lo += int(summ.get("low_severity") or 0)
            except Exception:
                pass
    return f"Latest scan (facts): **high={hi}**, **medium={me}**, **low={lo}** — I won’t contradict these counts."


def format_boundary_ood(user_message: str) -> str:
    return (
        "### Out of scope for Agent Dhara\n\n"
        f"Your request (“{user_message.strip()}”) isn’t something I can answer here.\n\n"
        "**Agent Dhara** focuses on **data quality assessment**: CSV/JSON/XML profiling, DQ findings, "
        "relationships between loaded datasets, and practical ETL-oriented clean-up guidance.\n\n"
        "**Yes:** analyze uploaded files, explain DQ reports, prioritize fixes.\n"
        "**No:** live stock quotes, general-purpose coding tutorials, sports/news, or trivia.\n\n"
        "Upload or select a dataset, then ask e.g. **“top 5 data quality issues”** or **“null issues only”**."
    )


def format_boundary_adversarial(user_message: str, result: Optional[Dict[str, Any]] = None) -> str:
    facts = _dq_totals(result)
    return (
        "### I can’t follow that instruction\n\n"
        f"You asked: “{user_message.strip()}”\n\n"
        "I **must not** skip analysis, invent issues, or contradict the assessment verdict. "
        "That would be unsafe for data engineering decisions.\n\n"
        + (facts + "\n\n" if facts else "")
        + "Tell me what you want **within** the assessment (e.g. top HIGH issues, null-only table, or triage for a 2-hour fix window)."
    )
