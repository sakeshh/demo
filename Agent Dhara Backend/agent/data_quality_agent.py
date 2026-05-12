"""
Data Quality Agent.

This is a thin orchestration wrapper around the existing rule-based DQ pipeline.
It is designed to be used as a LangGraph node: it consumes extraction outputs
and returns a merged, JSON-serializable structure that downstream agents (e.g.
Transformation Suggester) can consume.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple


@dataclass(frozen=True)
class DataQualityResult:
    """
    Merged DQ output across one or more extraction results.
    """

    # Per extracted source name -> DQ block (same shape as load_and_profile()["data_quality_issues"])
    sources: Dict[str, Dict[str, Any]]
    # Lightweight global summary across sources
    summary: Dict[str, Any]


class DataQualityAgent:
    """
    Merge and normalize DQ results from extraction outputs.

    Note: the extraction pipeline already returns `data_quality_issues` because each
    MCP adapter runs `agent.mcp_interface.run_assessment()` (which calls
    `load_and_profile()`).
    """

    def run_from_extractions(self, extractions: List[Dict[str, Any]]) -> DataQualityResult:
        per_source: Dict[str, Dict[str, Any]] = {}

        total_datasets = 0
        total_issues = 0
        total_high = 0
        total_medium = 0
        total_low = 0

        for ex in extractions or []:
            source = str(ex.get("source") or ex.get("source_name") or "source")
            res = ex.get("result") if isinstance(ex.get("result"), dict) else {}
            dq = res.get("data_quality_issues") if isinstance(res, dict) else None

            if not isinstance(dq, dict):
                per_source[source] = {"error": "Missing data_quality_issues in extraction result"}
                continue

            per_source[source] = dq

            ds_block = dq.get("datasets", {}) if isinstance(dq.get("datasets", {}), dict) else {}
            total_datasets += len(ds_block)
            for _, b in ds_block.items():
                if not isinstance(b, dict):
                    continue
                summary = b.get("summary") if isinstance(b.get("summary"), dict) else {}
                total_issues += int(summary.get("issue_count") or 0)
                total_high += int(summary.get("high_severity") or 0)
                total_medium += int(summary.get("medium_severity") or 0)
                total_low += int(summary.get("low_severity") or 0)

        return DataQualityResult(
            sources=per_source,
            summary={
                "source_count": len(per_source),
                "dataset_count": total_datasets,
                "issue_count": total_issues,
                "high_severity": total_high,
                "medium_severity": total_medium,
                "low_severity": total_low,
            },
        )


def dq_result_to_dict(r: DataQualityResult) -> Dict[str, Any]:
    return {"sources": r.sources, "summary": r.summary}

