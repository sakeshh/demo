"""Cross-dataset specialist - relationships, schema naming, load ordering, Sweetviz comparison."""
from __future__ import annotations
import logging
import os
import tempfile
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Sweetviz helpers
# ---------------------------------------------------------------------------

def _is_sweetviz_available() -> bool:
    try:
        import sweetviz  # type: ignore  # noqa: F401
        return True
    except ImportError:
        return False


def generate_sweetviz_comparison(
    df1,
    df2,
    name1: str = "Dataset A",
    name2: str = "Dataset B",
    output_path: Optional[str] = None,
) -> Tuple[bool, str]:
    """
    Generate a Sweetviz side-by-side HTML comparison report for two DataFrames.

    Args:
        df1:         First pandas DataFrame
        df2:         Second pandas DataFrame
        name1:       Label for first dataset
        name2:       Label for second dataset
        output_path: Where to save the HTML file.
                     If None, saves to system temp directory.

    Returns:
        (success: bool, html_path: str)
        success=False if sweetviz is unavailable or comparison fails.
    """
    if not _is_sweetviz_available():
        logger.info(
            "sweetviz not installed — skipping visual comparison. "
            "Install with: pip install sweetviz"
        )
        return False, ""

    try:
        import sweetviz as sv  # type: ignore

        if output_path is None:
            tmp = tempfile.NamedTemporaryFile(
                suffix=".html",
                prefix="dhara_sweetviz_",
                delete=False,
                dir=tempfile.gettempdir(),
            )
            output_path = tmp.name
            tmp.close()

        compare_report = sv.compare(
            [df1, name1],
            [df2, name2],
        )
        compare_report.show_html(
            output_path,
            open_browser=False,
            layout="widescreen",
        )

        logger.info(
            "Sweetviz comparison report saved: %s  (%s vs %s)",
            output_path, name1, name2,
        )
        return True, output_path

    except Exception as exc:
        logger.error("Sweetviz comparison failed: %s", exc)
        return False, ""


def generate_sweetviz_single(df, name: str = "Dataset", output_path: Optional[str] = None) -> Tuple[bool, str]:
    """
    Generate a Sweetviz single-dataset EDA HTML report.

    Returns:
        (success: bool, html_path: str)
    """
    if not _is_sweetviz_available():
        return False, ""

    try:
        import sweetviz as sv  # type: ignore

        if output_path is None:
            tmp = tempfile.NamedTemporaryFile(
                suffix=".html",
                prefix=f"dhara_sv_{name.replace(' ', '_')}_",
                delete=False,
                dir=tempfile.gettempdir(),
            )
            output_path = tmp.name
            tmp.close()

        report = sv.analyze([df, name])
        report.show_html(output_path, open_browser=False)
        logger.info("Sweetviz single-dataset report saved: %s", output_path)
        return True, output_path

    except Exception as exc:
        logger.error("Sweetviz single report failed: %s", exc)
        return False, ""


# ---------------------------------------------------------------------------
# Original cross-dataset helpers (unchanged)
# ---------------------------------------------------------------------------

def _collect_all_issues(assessment: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
    result = {}
    for ds_name, ds_data in assessment.items():
        if isinstance(ds_data, dict):
            result[ds_name] = ds_data.get("issues", [])
    return result


def _schema_naming_view(assessment: Dict[str, Any]) -> str:
    lines = ["**Schema Naming Analysis Across Datasets:**\n"]
    all_columns: Dict[str, List[str]] = {}
    for ds_name, ds_data in assessment.items():
        if not isinstance(ds_data, dict):
            continue
        cols = ds_data.get("columns", [])
        if isinstance(cols, list):
            all_columns[ds_name] = [str(c).lower() for c in cols]

    if not all_columns:
        return "Schema naming analysis requires column metadata in the assessment result."

    all_col_sets = [set(v) for v in all_columns.values()]
    if len(all_col_sets) >= 2:
        common = set.intersection(*all_col_sets)
        if common:
            lines.append(f"**Shared columns across all datasets:** {', '.join(sorted(common))}")
        else:
            lines.append("No exact column name matches found across datasets - possible naming inconsistencies.")

    join_candidates = ["id", "customer_id", "order_id", "user_id", "product_id", "account_id"]
    found_joins = {}
    for ds_name, cols in all_columns.items():
        hits = [c for c in cols if any(j in c for j in join_candidates)]
        if hits:
            found_joins[ds_name] = hits

    if found_joins:
        lines.append("\n**Potential join key columns:**")
        for ds_name, cols in found_joins.items():
            lines.append(f"  - `{ds_name}`: {', '.join(cols)}")

    return "\n".join(lines)


def summarize_load_order(assessment: Dict[str, Any]) -> List[str]:
    scores = []
    for ds_name, ds_data in assessment.items():
        if not isinstance(ds_data, dict):
            continue
        issues = ds_data.get("issues", [])
        score = sum(
            {"CRITICAL": 10, "BLOCKER": 10, "HIGH": 6, "MEDIUM": 3, "LOW": 1}.get(
                str(i.get("severity", "LOW")).upper(), 1
            ) for i in issues
        )
        scores.append((ds_name, score))
    scores.sort(key=lambda x: x[1])
    return [ds for ds, _ in scores]


# ---------------------------------------------------------------------------
# Main formatter — now with Sweetviz integration
# ---------------------------------------------------------------------------

def format_cross_dataset(
    assessment: Dict[str, Any],
    message: str = "",
    dataframes: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Format cross-dataset analysis response.

    Args:
        assessment:  The full assessment result dict (from last_assessment_result)
        message:     The user's original message
        dataframes:  Optional dict of {dataset_name: pd.DataFrame}.
                     If provided and Sweetviz is installed, a visual HTML comparison
                     report is generated and a download link is included in the reply.

    Returns:
        Formatted markdown string for the chat response.
    """
    if not assessment:
        return "No assessment data available. Please run an assessment first."

    low = message.lower() if message else ""

    # ── Schema naming view ────────────────────────────────────────────────
    if any(k in low for k in ("schema naming", "naming problems", "naming inconsistencies", "column naming")):
        return _schema_naming_view(assessment)

    # ── Load order view ──────────────────────────────────────────────────
    if any(k in low for k in ("load order", "order to load", "which to load first", "safest to load")):
        order = summarize_load_order(assessment)
        lines = ["**Cross-Dataset Load Order (cleanest first):**\n"]
        for idx, ds in enumerate(order, 1):
            lines.append(f"{idx}. `{ds}`")
        return "\n".join(lines)

    # ── Sweetviz visual comparison (when 2 DataFrames are available) ──────
    sweetviz_section = ""
    if dataframes and len(dataframes) >= 2:
        ds_names = list(dataframes.keys())
        df1, df2 = dataframes[ds_names[0]], dataframes[ds_names[1]]
        name1, name2 = ds_names[0], ds_names[1]

        success, html_path = generate_sweetviz_comparison(df1, df2, name1, name2)
        if success:
            sweetviz_section = (
                f"\n\n---\n"
                f"**📊 Sweetviz Visual Comparison Report Generated**\n"
                f"A side-by-side visual EDA comparison of `{name1}` vs `{name2}` "
                f"has been saved to:\n`{html_path}`\n"
                f"Open this file in a browser to explore distributions, "
                f"missing value patterns, and column-level differences visually."
            )
        else:
            sweetviz_section = (
                "\n\n*Visual comparison not available — install sweetviz: `pip install sweetviz`*"
            )

    # ── Default cross-dataset issues view ────────────────────────────────
    issues_by_ds = _collect_all_issues(assessment)
    datasets = list(issues_by_ds.keys())
    lines = [f"**Cross-Dataset Overview ({len(datasets)} datasets):**\n"]

    for ds_name, issues in issues_by_ds.items():
        key_issues = [i for i in issues if any(
            k in str(i.get("issue_type", i.get("type", ""))).lower()
            for k in ("key", "foreign", "join", "orphan", "reference")
        )]
        if key_issues:
            lines.append(f"\n**{ds_name}** - {len(key_issues)} relationship issue(s):")
            for i in key_issues[:3]:
                col = i.get("column", "")
                itype = i.get("issue_type", i.get("type", "unknown"))
                lines.append(f"  - `{col}` | {itype}")
        else:
            lines.append(f"\n**{ds_name}** - No relationship issues detected.")

    load_order = summarize_load_order(assessment)
    lines.append(f"\n**Suggested load order:** {' -> '.join(load_order)}")

    return "\n".join(lines) + sweetviz_section
