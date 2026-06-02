from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

import pandas as pd

from agent.metadata_registry import (
    critical_columns_from_manifest,
    glossary_from_manifest,
    resolve_dataset_manifest,
)

_ID_HINTS = re.compile(
    r"(^|_)(id|key|uuid|guid|pk|fk|ref)($|_)", re.I
)


def _likely_keys(columns: Dict[str, Any]) -> List[str]:
    keys: List[str] = []
    for name, meta in (columns or {}).items():
        if not isinstance(meta, dict):
            continue
        if meta.get("candidate_primary_key"):
            keys.append(str(name))
        elif _ID_HINTS.search(str(name)):
            keys.append(str(name))
    return list(dict.fromkeys(keys))[:12]


def _importance_for_column(col: str, meta: Dict[str, Any], manifest_entry: Dict[str, Any]) -> str:
    mcols = (manifest_entry.get("columns") or {}).get(col) if isinstance(manifest_entry.get("columns"), dict) else None
    if isinstance(mcols, dict):
        imp = str(mcols.get("business_importance") or "").lower()
        if imp in ("high", "critical"):
            return "high"
        if imp == "medium":
            return "medium"
    hints = meta.get("llm_hints") or {}
    imp2 = str(hints.get("business_importance") or "low").lower()
    if imp2 in ("high", "critical"):
        return "high"
    if imp2 == "medium":
        return "medium"
    if meta.get("candidate_primary_key"):
        return "high"
    if _ID_HINTS.search(str(col)):
        return "medium"
    return "low"


def build_semantic_context_for_dataset(
    dataset_name: str,
    ds_meta: Dict[str, Any],
    *,
    sample_df: Optional[pd.DataFrame] = None,
    manifest_entry: Optional[Dict[str, Any]] = None,
    glossary: Optional[Dict[str, str]] = None,
    user_notes: str = "",
    prior_hints: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Build a JSON-serializable semantic context for one dataset.
    """
    manifest_entry = manifest_entry or {}
    glossary = dict(glossary or {})
    cols = ds_meta.get("columns") or {}
    if not isinstance(cols, dict):
        cols = {}

    business_terms: Dict[str, str] = dict(glossary)
    for cname, meta in cols.items():
        if not isinstance(meta, dict):
            continue
        llm = meta.get("llm_hints") or {}
        desc = llm.get("column_description") or llm.get("description")
        if desc and cname not in business_terms:
            business_terms[str(cname)] = str(desc)[:500]

    mcols = manifest_entry.get("columns") if isinstance(manifest_entry.get("columns"), dict) else {}
    if isinstance(mcols, dict):
        for cname, cent in mcols.items():
            if isinstance(cent, dict) and cent.get("meaning"):
                business_terms[str(cname)] = str(cent["meaning"])

    critical = list(dict.fromkeys(critical_columns_from_manifest(manifest_entry)))
    for cname, meta in cols.items():
        if isinstance(meta, dict) and _importance_for_column(cname, meta, manifest_entry) == "high":
            if cname not in critical:
                critical.append(str(cname))

    column_importance: Dict[str, str] = {}
    confidences: List[float] = []
    for cname, meta in cols.items():
        if not isinstance(meta, dict):
            continue
        imp = _importance_for_column(str(cname), meta, manifest_entry)
        column_importance[str(cname)] = imp
        st = str(meta.get("semantic_type") or "unknown")
        if st != "unknown":
            confidences.append(0.82)
        else:
            confidences.append(0.55)
        tc = meta.get("type_confidence")
        if isinstance(tc, (int, float)):
            confidences.append(float(tc))

    likely_keys = _likely_keys(cols)
    pk = manifest_entry.get("primary_key")
    if isinstance(pk, list) and pk:
        likely_keys = list(dict.fromkeys([str(x) for x in pk] + likely_keys))

    semantic_confidence = round(sum(confidences) / max(len(confidences), 1), 3)

    ctx: Dict[str, Any] = {
        "dataset_name": dataset_name,
        "critical_columns": critical[:40],
        "likely_key_columns": likely_keys,
        "business_terms": business_terms,
        "column_importance": column_importance,
        "semantic_confidence": semantic_confidence,
        "user_notes": (user_notes or "")[:4000],
        "prior_report_hints": prior_hints or {},
        "sample_row_count": int(len(sample_df)) if sample_df is not None else 0,
        "domain_hints": {
            "source_root": ds_meta.get("source_root"),
            "row_count": ds_meta.get("row_count"),
        },
    }
    return ctx


def build_all_semantic_contexts(
    assessment: Dict[str, Any],
    sample_by_dataset: Optional[Dict[str, pd.DataFrame]] = None,
    *,
    manifest: Dict[str, Any],
    user_notes: str = "",
    prior_hints: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    sample_by_dataset = sample_by_dataset or {}
    out: Dict[str, Dict[str, Any]] = {}
    datasets = assessment.get("datasets") or {}
    for ds_name, ds_meta in datasets.items():
        if not isinstance(ds_meta, dict):
            continue
        entry, _ = resolve_dataset_manifest(str(ds_name), manifest)
        gloss = glossary_from_manifest(entry)
        df = sample_by_dataset.get(ds_name)
        if df is None:
            sample = None
        else:
            sample = df.head(50)
        out[str(ds_name)] = build_semantic_context_for_dataset(
            str(ds_name),
            ds_meta,
            sample_df=sample,
            manifest_entry=entry,
            glossary=gloss,
            user_notes=user_notes,
            prior_hints=prior_hints,
        )
    agg = [v.get("semantic_confidence", 0.0) for v in out.values()]
    overall = round(sum(agg) / max(len(agg), 1), 3) if agg else 0.0
    return {"by_dataset": out, "overall_semantic_confidence": overall}
