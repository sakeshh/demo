"""
YData Profiling engine for Agent Dhara assessment enrichment.

This module wraps ydata-profiling (formerly pandas-profiling) to provide
richer statistical profiling of any DataFrame during assessment.

What it adds over custom checks:
    - Distribution analysis (skewness, kurtosis, histogram)
    - Correlation matrix (Pearson, Spearman, Kendall)
    - Zero/infinite value detection
    - High cardinality detection
    - Constant / near-constant column detection
    - Interaction alerts (correlated columns)
    - Duplicate row detection
    - Data type mismatch hints

Usage:
    from agent.specialists.ydata_profiler import enrich_assessment_with_profile

    # Pass a DataFrame + existing assessment dict
    enriched = enrich_assessment_with_profile(df, existing_assessment_dict)

Fallback:
    If ydata-profiling is not installed, returns the original assessment unchanged.
    No crash — the profiler is an enhancement layer, not a hard dependency.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# Max rows to profile — sampling above this threshold avoids OOM on huge files
PROFILE_ROW_LIMIT = 50_000


def _is_ydata_available() -> bool:
    try:
        import ydata_profiling  # type: ignore  # noqa: F401
        return True
    except ImportError:
        return False


def profile_dataframe(df, minimal: bool = False) -> Optional[Dict[str, Any]]:
    """
    Run YData Profiling on a DataFrame and return a structured dict.

    Args:
        df:       pandas DataFrame to profile
        minimal:  If True, runs a faster minimal profile (no correlations/interactions)
                  Recommended for large datasets or quick checks.

    Returns:
        dict with profiling stats, or None if ydata-profiling is unavailable.
    """
    if not _is_ydata_available():
        logger.info(
            "ydata-profiling not installed — skipping profile enrichment. "
            "Install with: pip install ydata-profiling"
        )
        return None

    try:
        import pandas as pd  # type: ignore
        from ydata_profiling import ProfileReport  # type: ignore

        # Sample large DataFrames to avoid memory issues
        if len(df) > PROFILE_ROW_LIMIT:
            logger.info(
                "DataFrame has %d rows > limit %d — sampling for profiling.",
                len(df), PROFILE_ROW_LIMIT,
            )
            df = df.sample(n=PROFILE_ROW_LIMIT, random_state=42)

        profile = ProfileReport(
            df,
            title="Agent Dhara — Dataset Profile",
            minimal=minimal,
            explorative=True,
            progress_bar=False,
        )

        profile_dict = profile.to_dict()

        # Extract key stats into a clean, flat structure
        variables = profile_dict.get("variables", {})
        alerts = profile_dict.get("alerts", [])
        table_stats = profile_dict.get("table", {})

        enriched = {
            "row_count":         table_stats.get("n", 0),
            "column_count":      table_stats.get("n_var", 0),
            "duplicate_rows":    table_stats.get("n_duplicates", 0),
            "missing_cells":     table_stats.get("n_cells_missing", 0),
            "missing_pct":       round(table_stats.get("p_cells_missing", 0) * 100, 2),
            "total_size_memory": table_stats.get("memory_size", 0),
            "alerts":            [str(a) for a in alerts],
            "column_profiles":   {},
        }

        for col_name, col_stats in variables.items():
            enriched["column_profiles"][col_name] = {
                "type":           col_stats.get("type", "unknown"),
                "missing_count":  col_stats.get("n_missing", 0),
                "missing_pct":    round(col_stats.get("p_missing", 0) * 100, 2),
                "unique_count":   col_stats.get("n_unique", 0),
                "is_constant":    col_stats.get("is_unique", False) and col_stats.get("n_unique", 2) == 1,
                "high_cardinality": col_stats.get("n_unique", 0) > 50,
                "zeros":          col_stats.get("n_zeros", 0),
                "infinite":       col_stats.get("n_infinite", 0),
                # Numeric stats (None for non-numeric)
                "mean":           col_stats.get("mean"),
                "std":            col_stats.get("std"),
                "min":            col_stats.get("min"),
                "max":            col_stats.get("max"),
                "skewness":       col_stats.get("skewness"),
                "kurtosis":       col_stats.get("kurtosis"),
            }

        logger.info(
            "YData Profiling complete — %d columns, %d alerts, %.1f%% missing",
            enriched["column_count"],
            len(enriched["alerts"]),
            enriched["missing_pct"],
        )
        return enriched

    except Exception as exc:
        logger.error("YData Profiling failed: %s", exc)
        return None


def enrich_assessment_with_profile(
    df,
    assessment: Dict[str, Any],
    dataset_name: str = "dataset",
    minimal: bool = False,
) -> Dict[str, Any]:
    """
    Enrich an existing assessment dict with YData Profiling stats.

    This is the main integration point. Call this inside the assessment
    specialist after your existing custom checks run.

    Args:
        df:             pandas DataFrame that was assessed
        assessment:     existing assessment result dict from intelligent_data_assessment.py
        dataset_name:   name/key for this dataset in the assessment dict
        minimal:        use minimal profiling mode (faster, fewer stats)

    Returns:
        The same assessment dict, with a new 'ydata_profile' key added.
        If profiling fails, returns the original assessment unchanged.

    Example output shape:
        {
          ...existing assessment keys...,
          "ydata_profile": {
            "row_count": 1500,
            "duplicate_rows": 12,
            "missing_pct": 4.2,
            "alerts": ["High cardinality in column 'email'", ...],
            "column_profiles": {
              "email": {"missing_count": 23, "high_cardinality": True, ...},
              ...
            }
          }
        }
    """
    profile = profile_dataframe(df, minimal=minimal)
    if profile is None:
        # ydata-profiling not available — return unchanged
        return assessment

    # Inject profile into assessment under a namespaced key
    enriched_assessment = dict(assessment)  # shallow copy — don't mutate original
    enriched_assessment["ydata_profile"] = profile

    # Cross-reference: flag any columns already in issues that also have high cardinality
    issues = enriched_assessment.get("issues", [])
    col_profiles = profile.get("column_profiles", {})
    for issue in issues:
        col = issue.get("column", "")
        if col in col_profiles:
            col_p = col_profiles[col]
            # Enrich each issue with extra ydata context
            issue["_ydata_missing_pct"]    = col_p.get("missing_pct")
            issue["_ydata_high_cardinality"] = col_p.get("high_cardinality")
            issue["_ydata_zeros"]           = col_p.get("zeros")
            issue["_ydata_skewness"]        = col_p.get("skewness")

    logger.info(
        "Assessment enriched with YData profile for dataset '%s'.",
        dataset_name,
    )
    return enriched_assessment


def generate_profile_html(df, output_path: str, minimal: bool = False) -> bool:
    """
    Generate a standalone YData Profiling HTML report and save to disk.

    Args:
        df:          pandas DataFrame to profile
        output_path: path to save the HTML file (e.g. '/tmp/profile_report.html')
        minimal:     use minimal mode for speed

    Returns:
        True if the report was saved successfully, False otherwise.
    """
    if not _is_ydata_available():
        logger.warning("ydata-profiling not installed — cannot generate HTML report.")
        return False

    try:
        from ydata_profiling import ProfileReport  # type: ignore

        if len(df) > PROFILE_ROW_LIMIT:
            df = df.sample(n=PROFILE_ROW_LIMIT, random_state=42)

        profile = ProfileReport(
            df,
            title="Agent Dhara — YData Profile Report",
            minimal=minimal,
            progress_bar=False,
        )
        profile.to_file(output_path)
        logger.info("YData Profiling HTML report saved: %s", output_path)
        return True

    except Exception as exc:
        logger.error("Failed to generate YData HTML report: %s", exc)
        return False
