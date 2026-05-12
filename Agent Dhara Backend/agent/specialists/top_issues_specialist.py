"""Top-issues specialist — concise issue list answer modes."""
from __future__ import annotations
from typing import Any, Dict, List


def _impact_text(issue_type: str) -> str:
    impacts = {
        "null": "causes NULLs to propagate in joins and aggregations",
        "missing": "leads to incomplete records and skewed metrics",
        "duplicate": "inflates row counts and breaks primary key constraints",
        "email": "invalid emails cause CRM sync failures",
        "phone": "invalid phones break notification pipelines",
        "format": "format mismatches cause ETL type-cast errors",
        "range": "out-of-range values corrupt aggregation results",
        "key": "broken keys cause orphan records in joins",
    }
    for k, v in impacts.items():
        if k in issue_type.lower():
            return v
    return "may cause downstream pipeline failures"


def _collect_issues(assessment: Dict[str, Any]) -> List[Dict[str, Any]]:
    issues = []
    for ds_name, ds_data in assessment.items():
        if not isinstance(ds_data, dict):
            continue
        for issue in ds_data.get("issues", []):
            issue["_dataset"] = ds_name
            issues.append(issue)
    return issues


def _format_red_flags(issues: List[Dict[str, Any]]) -> str:
    blockers = [i for i in issues if str(i.get("severity", "")).upper() in ("HIGH", "CRITICAL", "BLOCKER")]
    if not blockers:
        return "No critical blockers found. Data looks reasonably clean for loading."
    lines = ["**Red Flags (Blockers):**\n"]
    for i in blockers[:8]:
        ds = i.get("_dataset", "unknown")
        col = i.get("column", "")
        itype = i.get("issue_type", i.get("type", "unknown"))
        sev = i.get("severity", "HIGH")
        impact = _impact_text(itype)
        lines.append(f"- **[{sev}]** `{ds}` -> `{col}` | {itype} - {impact}")
    return "\n".join(lines)


def _format_etl_columns(issues: List[Dict[str, Any]]) -> str:
    col_scores: Dict[str, int] = {}
    col_issues: Dict[str, List[str]] = {}
    for i in issues:
        col = i.get("column", "unknown")
        sev = str(i.get("severity", "LOW")).upper()
        score = {"CRITICAL": 10, "BLOCKER": 10, "HIGH": 6, "MEDIUM": 3, "LOW": 1}.get(sev, 1)
        col_scores[col] = col_scores.get(col, 0) + score
        col_issues.setdefault(col, []).append(i.get("issue_type", i.get("type", "issue")))
    ranked = sorted(col_scores.items(), key=lambda x: x[1], reverse=True)[:8]
    if not ranked:
        return "No column-level ETL risks found."
    lines = ["**ETL Risk Columns (ranked):**\n", "| Column | Risk Score | Issues |", "|---|---|---|"]
    for col, score in ranked:
        itypes = ", ".join(set(col_issues.get(col, [])))
        lines.append(f"| `{col}` | {score} | {itypes} |")
    return "\n".join(lines)


def _format_autofixable(issues: List[Dict[str, Any]]) -> str:
    auto = [i for i in issues if i.get("auto_fixable") is True or "trim" in str(i.get("fix", "")).lower()
            or "fillna" in str(i.get("fix", "")).lower() or "strip" in str(i.get("fix", "")).lower()]
    manual = [i for i in issues if i not in auto]
    lines = [f"**Auto-fixable:** {len(auto)} issues\n**Needs manual review:** {len(manual)} issues\n"]
    if auto:
        lines.append("*Auto-fix candidates:*")
        for i in auto[:5]:
            lines.append(f"- `{i.get('column','')}` -> {i.get('issue_type', i.get('type',''))}: {i.get('fix','apply standard fix')}")
    if manual:
        lines.append("\n*Manual review needed:*")
        for i in manual[:5]:
            lines.append(f"- `{i.get('column','')}` -> {i.get('issue_type', i.get('type',''))}: requires domain knowledge")
    return "\n".join(lines)


def _format_pipeline_risk(issues: List[Dict[str, Any]]) -> str:
    risk_types = ("null", "missing", "key", "duplicate", "format", "type")
    risky = [i for i in issues if any(r in str(i.get("issue_type", i.get("type", ""))).lower() for r in risk_types)]
    if not risky:
        return "No direct pipeline risk issues found. Data appears structurally sound."
    lines = ["**Pipeline Risk Issues:**\n"]
    for i in risky[:8]:
        ds = i.get("_dataset", "unknown")
        col = i.get("column", "")
        itype = i.get("issue_type", i.get("type", "unknown"))
        impact = _impact_text(itype)
        lines.append(f"- `{ds}.{col}` | **{itype}** -> {impact}")
    return "\n".join(lines)


def format_top_issues(assessment: Dict[str, Any], message: str = "") -> str:
    if not assessment:
        return "No assessment data available. Please run an assessment first."
    issues = _collect_issues(assessment)
    if not issues:
        return "No issues found in the assessment. Your data looks clean!"
    low = message.lower() if message else ""

    if any(k in low for k in ("red flag", "blocker", "critical", "blocking")):
        return _format_red_flags(issues)
    if any(k in low for k in ("which column", "etl column", "riskiest column", "column risk")):
        return _format_etl_columns(issues)
    if any(k in low for k in ("auto-fix", "auto fix", "autofixable", "manual review")):
        return _format_autofixable(issues)
    if any(k in low for k in ("pipeline", "downstream", "break", "broken")):
        return _format_pipeline_risk(issues)

    severity_order = {"CRITICAL": 0, "BLOCKER": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
    sorted_issues = sorted(issues, key=lambda x: severity_order.get(str(x.get("severity", "LOW")).upper(), 3))
    lines = [f"**Top Issues ({len(issues)} total):**\n"]
    for i in sorted_issues[:8]:
        ds = i.get("_dataset", "unknown")
        col = i.get("column", "")
        itype = i.get("issue_type", i.get("type", "unknown"))
        sev = i.get("severity", "LOW")
        impact = _impact_text(itype)
        lines.append(f"- **[{sev}]** `{ds}` -> `{col}` | {itype} - {impact}")
    return "\n".join(lines)
