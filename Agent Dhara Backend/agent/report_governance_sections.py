"""
HTML/Markdown snippets for governance blocks (semantic, drift, reconciliation, preview).
"""
from __future__ import annotations

import html as html_module
from typing import Any, Dict, List


def render_governance_markdown(result: Dict[str, Any]) -> str:
    lines: List[str] = []
    if not isinstance(result, dict):
        return ""

    sem = result.get("semantic_context") or {}
    if sem.get("by_dataset"):
        lines.append("## Semantic & governance")
        lines.append(f"- Overall semantic confidence: **{sem.get('overall_semantic_confidence')}**")
        if sem.get("contract"):
            lines.append("- Validated semantic contract: **present** (`semantic_context.contract`)")
        gov = result.get("governance") or {}
        if gov:
            lines.append(
                f"- Manifest v{gov.get('manifest_version')} · schema `{gov.get('schema_hash')}` · glossary `{gov.get('glossary_hash')}`"
            )
        lines.append("")

    da = result.get("drift_analysis") or {}
    if da.get("per_dataset"):
        lines.append("### Drift analysis (rollup)")
        lines.append(f"- Drift score (100=stable): **{da.get('drift_score')}** · worst: **{da.get('worst_severity')}** · signals: {da.get('total_signal_count')}")
        lines.append("")

    ra = result.get("reconciliation_analysis") or {}
    if ra.get("by_dataset"):
        lines.append("### Reconciliation analysis")
        for ds, block in (ra.get("by_dataset") or {}).items():
            if not isinstance(block, dict):
                continue
            d = block.get("deltas") or {}
            lines.append(f"- **{ds}**: parsed loss={d.get('source_to_parsed_loss')}, write delta={d.get('parsed_to_written_loss')}")
            for ex in (block.get("explainable_losses") or [])[:3]:
                lines.append(f"  - {ex}")
        lines.append("")

    sup = (result.get("data_quality_issues") or {}).get("global_issues", {}).get("relationship_row_issues_supplemental") or []
    if sup:
        lines.append("### Relationship integrity (supplemental SQL checks)")
        for it in sup[:15]:
            if isinstance(it, dict):
                lines.append(
                    f"- `{it.get('dataset')}`.{it.get('column')} → `{it.get('related_dataset')}`.{it.get('related_column')} — {it.get('count')}"
                )
        lines.append("")

    dp = result.get("duckdb_preview") or {}
    if dp.get("ok"):
        lines.append("### DuckDB preview")
        lines.append(f"- Sample rows materialized: **{dp.get('rowcount_sample')}** (full **{dp.get('rowcount_full')}**)")
        lines.append(f"- Columns: {', '.join(str(c) for c in (dp.get('columns') or [])[:20])}")
        lines.append("")
    elif dp.get("error") == "duckdb_not_installed":
        lines.append("### DuckDB preview")
        lines.append("- _(duckdb package not installed — install to enable SQL preview)_")
        lines.append("")

    amb = result.get("semantic_ambiguity") or {}
    if amb.get("columns"):
        lines.append("### Unresolved ambiguity (low type confidence)")
        for row in amb["columns"][:15]:
            lines.append(f"- `{row.get('dataset')}`.`{row.get('column')}` — type_confidence={row.get('type_confidence')}")
        lines.append("")

    uni = result.get("unified_issues") or []
    if uni:
        lines.append("### ETL impact (unified issues)")
        for it in uni[:12]:
            if not isinstance(it, dict):
                continue
            lines.append(
                f"- [{it.get('source')}] {it.get('dataset')}.{it.get('column')}: **{it.get('business_impact')}** — {str(it.get('message', ''))[:120]}"
            )
        lines.append("")

    return "\n".join(lines)


def render_governance_html(result: Dict[str, Any]) -> str:
    if not isinstance(result, dict):
        return ""
    parts: List[str] = ['<section id="governance" class="datasets-section">', "<h2>Governance & drift</h2>"]

    sem = result.get("semantic_context") or {}
    if sem.get("by_dataset"):
        parts.append("<p class=\"section-lead\">Semantic contract, drift rollup, reconciliation, and optional DuckDB preview.</p>")
        parts.append(
            f"<p><strong>Semantic confidence (overall):</strong> {html_module.escape(str(sem.get('overall_semantic_confidence')))}</p>"
        )
        gov = result.get("governance") or {}
        if gov:
            parts.append(
                "<p class=\"muted\">Manifest v"
                + html_module.escape(str(gov.get("manifest_version")))
                + " · schema "
                + html_module.escape(str(gov.get("schema_hash")))
                + "</p>"
            )

    da = result.get("drift_analysis") or {}
    if da.get("per_dataset"):
        parts.append("<h3>Drift analysis</h3><ul>")
        parts.append(
            "<li>Drift score: <strong>"
            + html_module.escape(str(da.get("drift_score")))
            + "</strong> · worst severity: <strong>"
            + html_module.escape(str(da.get("worst_severity")))
            + "</strong></li>"
        )
        for row in da.get("per_dataset") or []:
            if isinstance(row, dict):
                parts.append(
                    "<li>"
                    + html_module.escape(str(row.get("dataset")))
                    + ": "
                    + html_module.escape(str(row.get("severity")))
                    + f" ({row.get('signal_count')} signals)</li>"
                )
        parts.append("</ul>")

    ra = result.get("reconciliation_analysis") or {}
    if ra.get("by_dataset"):
        parts.append("<h3>Reconciliation deltas</h3><ul>")
        for ds, block in (ra.get("by_dataset") or {}).items():
            if not isinstance(block, dict):
                continue
            d = block.get("deltas") or {}
            parts.append(
                "<li><code>"
                + html_module.escape(str(ds))
                + "</code> — parsed loss "
                + html_module.escape(str(d.get("source_to_parsed_loss")))
                + ", write delta "
                + html_module.escape(str(d.get("parsed_to_written_loss")))
                + "</li>"
            )
        parts.append("</ul>")

    dp = result.get("duckdb_preview") or {}
    if dp.get("ok"):
        parts.append("<h3>DuckDB preview</h3>")
        parts.append(
            "<p>Rows: "
            + html_module.escape(str(dp.get("rowcount_sample")))
            + " sample / "
            + html_module.escape(str(dp.get("rowcount_full")))
            + " total</p>"
        )
    elif dp.get("error") == "duckdb_not_installed":
        parts.append("<h3>DuckDB preview</h3><p class=\"muted\">Install <code>duckdb</code> to enable SQL preview.</p>")

    parts.append("</section>")
    return "\n".join(parts)
