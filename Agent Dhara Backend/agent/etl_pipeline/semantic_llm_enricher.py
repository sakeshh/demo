"""
Semantic LLM Enricher: Batch enriches low-confidence column classifications using OpenAI / Azure OpenAI.
"""
from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List, Optional, Tuple

from agent.model_config import load_llm_config

try:
    from openai import AzureOpenAI, OpenAI
except ImportError:
    AzureOpenAI = None
    OpenAI = None

def _get_llm_client() -> Tuple[Any, Optional[str]]:
    cfg = load_llm_config(purpose="etl_codegen")
    if not cfg:
        return None, None
    if cfg.provider == "azure_openai" and AzureOpenAI and cfg.endpoint:
        client = AzureOpenAI(
            azure_endpoint=cfg.endpoint,
            api_key=cfg.api_key,
            api_version=cfg.api_version or "2024-02-01",
        )
        return client, cfg.model
    if cfg.provider == "openai" and OpenAI:
        return OpenAI(api_key=cfg.api_key), cfg.model
    return None, None

def enrich_low_confidence_columns(
    low_confidence_cols: Dict[str, Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    """
    Batches low-confidence columns and calls LLM to enrich classifications.
    low_confidence_cols format: {
        "dataset.column": {
            "col_name": str,
            "col_meta": dict,
            "descriptor": dict (Layer 1 heuristic result)
        }
    }
    Returns mapping: { "dataset.column": enriched_descriptor_dict }
    """
    client, model = _get_llm_client()
    if not client or not model:
        # Gracefully return unchanged
        return {k: v["descriptor"] for k, v in low_confidence_cols.items()}

    # Format column batch info for prompt
    columns_batch = {}
    for key, item in low_confidence_cols.items():
        col_name = item["col_name"]
        col_meta = item["col_meta"]
        samples = col_meta.get("raw_samples") or []
        columns_batch[key] = {
            "column_name": col_name,
            "dtype": str(col_meta.get("dtype") or col_meta.get("inferred_type") or "unknown"),
            "raw_samples": samples[:10],
            "heuristic_sub_type": item["descriptor"].get("sub_type"),
        }

    prompt = f"""You are a senior data semantics architect.
Given a dictionary of columns and their metadata, analyze their names, data types, and sample values.
Return a single JSON object mapping each key (like 'dbo.Orders.CustomerID') to its enriched semantic descriptor.

For each key, output:
- semantic_type: one of ["id", "metric", "categorical", "date", "string"]
- sub_type: the most specific logical type, e.g., "email", "phone", "zip_code", "ssn", "uuid", "currency", "age", "percentage", "status_flag", "country", "gender", "pk", "fk", "unknown".
- pii_level: one of ["none", "low", "medium", "high"]
- allowed_domain: list of expected string values for categoricals, or null
- valid_range: {{"min": number, "max": number}} or null if not applicable
- expected_format: regex string or null
- fill_strategy: one of ["drop_row", "fill_mean", "fill_median", "fill_mode", "fill_zero", "flag", "none"]
- transform_hints: list of recommended transform actions (e.g. ["trim", "lowercase", "sanitize_email", "normalize_phone", "standardize_boolean", "parse_dates", "coerce_numeric"])

Input columns:
{json.dumps(columns_batch, indent=2)}

Return ONLY valid JSON. Do not include markdown fences, prose, or code block markers.
"""

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "You are a senior data semantics expert. Respond with raw JSON only."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.05,
            response_format={"type": "json_object"},
        )
        content = (response.choices[0].message.content or "").strip()
        
        # Clean up any potential markdown wraps
        if content.startswith("```"):
            content = re.sub(r"^```[a-zA-Z0-9_-]*\s*\n?", "", content)
            content = re.sub(r"\n?```\s*$", "", content)
            content = content.strip()

        enriched_data = json.loads(content)
        
        # Format resolved descriptors
        results = {}
        for key, item in low_confidence_cols.items():
            desc = enriched_data.get(key)
            if isinstance(desc, dict) and desc.get("semantic_type"):
                results[key] = {
                    "semantic_type": str(desc.get("semantic_type")),
                    "sub_type": str(desc.get("sub_type") or "unknown"),
                    "pii_level": str(desc.get("pii_level") or "none"),
                    "allowed_domain": desc.get("allowed_domain"),
                    "valid_range": desc.get("valid_range"),
                    "expected_format": desc.get("expected_format"),
                    "fill_strategy": str(desc.get("fill_strategy") or "fill_mode"),
                    "transform_hints": list(desc.get("transform_hints") or []),
                    "confidence": 0.95,
                    "inferred_by": "llm",
                }
            else:
                results[key] = item["descriptor"]
        return results

    except Exception:
        # Fallback to heuristic descriptors
        return {k: v["descriptor"] for k, v in low_confidence_cols.items()}
