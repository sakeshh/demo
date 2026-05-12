"""Triage specialist — prioritization and ETL readiness answer modes."""
from __future__ import annotations
from typing import Any, Dict, List, Tuple


def _score_dataset(ds_data: Dict[str, Any]) -> Tuple[str, int]:
    issues = ds_data.get("issues", [])
    score = 0
    for i in issues:
        sev = str(i.get("severity", "LOW")).upper()
        score += {"CRITICAL": 10, "BLOCKER": 10, "HIGH": 6, "MEDIUM": 3, "LOW": 1}.get(sev, 1)
    if score == 0:
        status = "READY"
    elif score <= 10:
        status = "NEEDS_WORK"
    else:
        status = "BLOCKED"
    return status, score


def _blocked_datasets(assessment: Dict[str, Any]) -> str:
    lines = ["**Dataset Readiness Status:**\n"]
    rows = []
    for ds_name, ds_data in assessment.items():
        if not isinstance(ds_data, dict):
            continue
        status, score = _score_dataset(ds_data)
        issue_count = len(ds_data.get("issues", []))
        rows.append((ds_name, status, score, issue_count))
    rows.sort(key=lambda x: x[2], reverse=True)
    status_icons = {"BLOCKED": "blocked", "NEEDS_WORK": "needs_work", "READY": "ready"}
    for ds_name, status, score, issue_count in rows:
        icon = status_icons.get(status, "unknown")
        lines.append(f"[{icon}] **{ds_name}** - {status} (risk score: {score}, issues: {issue_count})")
    return "\n".join(lines)


def _load_order(assessment: Dict[str, Any]) -> str:
    rows = []
    for ds_name, ds_data in assessment.items():
        if not isinstance(ds_data, dict):
            continue
        _, score = _score_dataset(ds_data)
        rows.append((ds_name, score))
    rows.sort(key=lambda x: x[1])
    lines = ["**Recommended Load Order (cleanest first):**\n"]
    for idx, (ds_name, score) in enumerate(rows, 1):
        tag = "Load first" if score == 0 else ("Fix then load" if score <= 10 else "Block until fixed")
        lines.append(f"{idx}. `{ds_name}` - risk score {score} | {tag}")
    return "\n".join(lines)


def _manual_review_burden(assessment: Dict[str, Any]) -> str:
    lines = ["**Manual Review Burden per Dataset:**\n"]
    rows = []
    for ds_name, ds_data in assessment.items():
        if not isinstance(ds_data, dict):
            continue
        issues = ds_data.get("issues", [])
        manual = [i for i in issues if not i.get("auto_fixable") and
                  not any(k in str(i.get("fix", "")).lower() for k in ("trim", "strip", "fillna", "replace"))]
        rows.append((ds_name, len(manual), len(issues)))
    rows.sort(key=lambda x: x[1], reverse=True)
    for ds_name, manual_count, total in rows:
        pct = int(manual_count / total * 100) if total else 0
        lines.append(f"- **{ds_name}**: {manual_count}/{total} issues need manual review ({pct}%)")
    return "\n".join(lines)


def _source_vs_user(assessment: Dict[str, Any]) -> str:
    source_signals = ("format", "type", "schema", "key", "range")
    user_signals = ("email", "phone", "duplicate", "null", "missing")
    lines = ["**Issue Origin Classification:**\n"]
    for ds_name, ds_data in assessment.items():
        if not isinstance(ds_data, dict):
            continue
        issues = ds_data.get("issues", [])
        src = sum(1 for i in issues if any(s in str(i.get("issue_type", i.get("type", ""))).lower() for s in source_signals))
        usr = sum(1 for i in issues if any(s in str(i.get("issue_type", i.get("type", ""))).lower() for s in user_signals))
        lines.append(f"- **{ds_name}**: {src} source-system issues | {usr} user-entry issues")
    return "\n".join(lines)


def _default_triage(assessment: Dict[str, Any]) -> str:
    lines = ["**2-Hour ETL Triage Plan:**\n"]
    rows = []
    for ds_name, ds_data in assessment.items():
        if not isinstance(ds_data, dict):
            continue
        status, score = _score_dataset(ds_data)
        issues = ds_data.get("issues", [])
        high = [i for i in issues if str(i.get("severity", "")).upper() in ("HIGH", "CRITICAL", "BLOCKER")]
        rows.append((ds_name, status, score, high))
    rows.sort(key=lambda x: x[2], reverse=True)
    for ds_name, status, score, high_issues in rows:
        lines.append(f"\n### {ds_name} - {status}")
        if high_issues:
            for i in high_issues[:3]:
                col = i.get("column", "")
                itype = i.get("issue_type", i.get("type", "unknown"))
                fix = i.get("fix", "investigate and fix")
                lines.append(f"  - `{col}` | {itype} -> Fix: {fix}")
        else:
            lines.append("  - No high-priority issues. Safe to load.")
    return "\n".join(lines)


def format_triage(assessment: Dict[str, Any], message: str = "") -> str:
    if not assessment:
        return "No assessment data available. Please run an assessment first."
    low = message.lower() if message else ""

    if any(k in low for k in ("blocked", "blocked and why", "which dataset is blocked")):
        return _blocked_datasets(assessment)
    if any(k in low for k in ("load order", "safest to load", "clean first", "order to load")):
        return _load_order(assessment)
    if any(k in low for k in ("manual review burden", "manual review")):
        return _manual_review_burden(assessment)
    if any(k in low for k in ("source-system", "source system", "user-entry", "user entry")):
        return _source_vs_user(assessment)
    return _default_triage(assessment)
