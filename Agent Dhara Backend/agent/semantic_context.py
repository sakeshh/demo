"""
Stable contracts for semantic enrichment (Pydantic v2).
Used by semantic_context_builder and downstream report/codegen consumers.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ColumnBusinessTerm(BaseModel):
    column: str
    term: str
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class DatasetSemanticContextModel(BaseModel):
    """One dataset's semantic view (mirrors legacy dict shape, validated)."""

    dataset_name: str
    critical_columns: List[str] = Field(default_factory=list)
    likely_key_columns: List[str] = Field(default_factory=list)
    business_terms: Dict[str, str] = Field(default_factory=dict)
    column_importance: Dict[str, str] = Field(default_factory=dict)
    semantic_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    user_notes: str = ""
    prior_report_hints: Dict[str, Any] = Field(default_factory=dict)
    sample_row_count: int = 0
    domain_hints: Dict[str, Any] = Field(default_factory=dict)


class SemanticContextPackageModel(BaseModel):
    by_dataset: Dict[str, DatasetSemanticContextModel] = Field(default_factory=dict)
    overall_semantic_confidence: float = Field(default=0.0, ge=0.0, le=1.0)


def semantic_package_from_legacy(legacy: Dict[str, Any]) -> SemanticContextPackageModel:
    """Parse output of build_all_semantic_contexts (dict form)."""
    by_raw = legacy.get("by_dataset") or {}
    out: Dict[str, DatasetSemanticContextModel] = {}
    if not isinstance(by_raw, dict):
        return SemanticContextPackageModel(
            by_dataset={},
            overall_semantic_confidence=float(legacy.get("overall_semantic_confidence") or 0.0),
        )
    for ds, raw in by_raw.items():
        if not isinstance(raw, dict):
            continue
        out[str(ds)] = DatasetSemanticContextModel(
            dataset_name=str(raw.get("dataset_name") or ds),
            critical_columns=list(raw.get("critical_columns") or []),
            likely_key_columns=list(raw.get("likely_key_columns") or []),
            business_terms=dict(raw.get("business_terms") or {}),
            column_importance=dict(raw.get("column_importance") or {}),
            semantic_confidence=float(raw.get("semantic_confidence") or 0.0),
            user_notes=str(raw.get("user_notes") or ""),
            prior_report_hints=dict(raw.get("prior_report_hints") or {}) if isinstance(raw.get("prior_report_hints"), dict) else {},
            sample_row_count=int(raw.get("sample_row_count") or 0),
            domain_hints=dict(raw.get("domain_hints") or {}) if isinstance(raw.get("domain_hints"), dict) else {},
        )
    return SemanticContextPackageModel(
        by_dataset=out,
        overall_semantic_confidence=float(legacy.get("overall_semantic_confidence") or 0.0),
    )


def attach_contract_to_semantic_payload(legacy: Dict[str, Any]) -> Dict[str, Any]:
    """Return legacy dict with validated `contract` key (model_dump)."""
    if not isinstance(legacy, dict):
        return {}
    try:
        legacy = dict(legacy)
        legacy["contract"] = semantic_package_from_legacy(legacy).model_dump()
    except Exception:
        legacy.setdefault("contract", {})
    return legacy
