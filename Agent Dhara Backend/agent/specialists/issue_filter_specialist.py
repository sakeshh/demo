"""Issue filter specialist - slice issues by type (null, duplicate, email, phone)."""
from __future__ import annotations
import re
from typing import Any, Dict, List

NULL_ALIASES = {"null", "nulls", "missing", "missing_values", "missing values", "null-related", "null related", "null issues"}
DUPE_ALIASES = {"duplicate", "duplicates", "duplicate_rows", "duplicate rows", "duplicate-related", "duplicate issues", "duplicate only", "duplicates only", "duplicate_primary_key"}
EMAIL_ALIASES = {"email", "emails", "email issues", "invalid email", "invalid emails"}
PHONE_ALIASES = {"phone", "phones", "phone issues", "invalid phone", "invalid phones"}
KEY_ALIASES = {"identifier", "primary key", "primary_key", "foreign key", "foreign_key"}


def _collect_all(assessment: Dict[str, Any]) -> List[Dict[str, Any]]:
    issues = []
    for ds_name, ds_data in assessment.items():
        if not isinstance(ds_data, dict):
            continue
        for issue in ds_data.get("issues", []):
            issue = dict(issue)
            issue["_dataset"] = ds_name
            issues.append(issue)
    return issues


def _match_type(issue: Dict[str, Any], aliases: set) -> bool:
    itype = str(issue.get("issue_type", issue.get("type", ""))).lower().replace("-", "_")
    return any(a.replace("-", "_") in itype for a in aliases)


def _extract_column_candidate(message: str) -> str:
    m = re.search(r"`([^`]+)`", message)
    if m:
        return m.group(1)
    m = re.search(r"column[s]?\s+['\"]?(\w+)['\"]?", message, re.IGNORECASE)
    if m:
        return m.group(1)
    return ""


def _format_simple_language(issues: List[Dict[str, Any]], issue_label: str) -> str:
    if not issues:
        return f"No {issue_label} issues found in the assessment."
    total = len(issues)
    datasets = list({i["_dataset"] for i in issues})
    cols = list({i.get("column", "") for i in issues if i.get("column")})
    lines = [
        f"There are **{total} {issue_label} issue(s)** found across {len(datasets)} dataset(s).",
        "",
        f"**Affected datasets:** {', '.join(datasets)}",
        f"**Affected columns:** {', '.join(cols[:8]) if cols else 'not specified'}",
        "",
        f"**What this means:** These columns have {issue_label} values that could cause",
        "problems in joins, aggregations, and reporting if not fixed.",
        "",
        "**Recommended fix:** Fill with a default value, flag for manual review, or",
        "drop rows depending on how critical the column is.",
    ]
    return "\n".join(lines)


def _format_issues(issues: List[Dict[str, Any]], label: str) -> str:
    if not issues:
        return f"No {label} issues found in the assessment."
    lines = [f"**{label.title()} Issues ({len(issues)} found):**\n"]
    for i in issues[:10]:
        ds = i.get("_dataset", "unknown")
        col = i.get("column", "")
        itype = i.get("issue_type", i.get("type", "unknown"))
        sev = i.get("severity", "LOW")
        fix = i.get("fix", "review and fix manually")
        lines.append(f"- **[{sev}]** `{ds}` -> `{col}` | {itype}")
        lines.append(f"  Fix: {fix}")
    return "\n".join(lines)


def format_issue_filter(assessment: Dict[str, Any], message: str = "") -> str:
    if not assessment:
        return "No assessment data available. Please run an assessment first."
    low = message.lower() if message else ""
    all_issues = _collect_all(assessment)
    col_hint = _extract_column_candidate(message)
    simple_mode = any(k in low for k in ("simple", "plain english", "explain", "in simple language", "easy language"))

    if any(k in low for k in NULL_ALIASES):
        filtered = [i for i in all_issues if _match_type(i, NULL_ALIASES)]
        if col_hint:
            filtered = [i for i in filtered if col_hint.lower() in str(i.get("column", "")).lower()] or filtered
        if simple_mode:
            return _format_simple_language(filtered, "null/missing")
        return _format_issues(filtered, "null/missing")

    if any(k in low for k in DUPE_ALIASES):
        filtered = [i for i in all_issues if _match_type(i, DUPE_ALIASES)]
        if col_hint:
            filtered = [i for i in filtered if col_hint.lower() in str(i.get("column", "")).lower()] or filtered
        return _format_issues(filtered, "duplicate")

    if any(k in low for k in EMAIL_ALIASES):
        filtered = [i for i in all_issues if _match_type(i, EMAIL_ALIASES)]
        return _format_issues(filtered, "email")

    if any(k in low for k in PHONE_ALIASES):
        filtered = [i for i in all_issues if _match_type(i, PHONE_ALIASES)]
        return _format_issues(filtered, "phone")

    if any(k in low for k in KEY_ALIASES):
        filtered = [i for i in all_issues if _match_type(i, KEY_ALIASES)]
        return _format_issues(filtered, "key/identifier")

    return _format_issues(all_issues, "filtered")
