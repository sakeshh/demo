from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional
from agent.model_config import load_llm_config

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """You are a data engineering expert. Analyze the dataset schema and masked sample values.
Return ONLY a JSON object. No markdown. No explanation.
Your response MUST match this structure:
{
  "table_grain": "one row per order transaction",
  "business_entity": "sales_order",
  "probable_pk_columns": ["cust_id", "ord_dt"],
  "columns": {
    "ord_dt": {
      "semantic_type": "date",
      "mixed_formats_suspected": true,
      "business_importance": "high",
      "cleaning_priority": "critical",
      "outlier_action_hint": null
    },
    "cust_id": {
      "semantic_type": "id",
      "mixed_formats_suspected": false,
      "business_importance": "high",
      "cleaning_priority": "critical",
      "outlier_action_hint": null
    }
  }
}
"""

# Regexes for PII identification
_EMAIL_RE = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")
_PHONE_RE = re.compile(r"^\+?\(?\d{1,4}\)?[-.\s]?\d{1,4}[-.\s]?\d{1,9}$")
_DATE_RE = re.compile(r"^\d{4}[-/]\d{2}[-/]\d{2}|\d{2}[-/]\d{2}[-/]\d{4}$")
_NAME_RE = re.compile(r"^[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*$")

def mask_pii_value(v: Any) -> Any:
    """Mask PII in sample values based on patterns."""
    if v is None:
        return None
    s = str(v).strip()
    if not s:
        return s
    
    # 1. Date check (keep as-is)
    if _DATE_RE.match(s) or ("-" in s and len(s) >= 8 and s.replace("-", "").replace(":", "").replace(" ", "").isdigit()):
        return s
    
    # 2. Email check
    if _EMAIL_RE.match(s) or "@" in s:
        return "user@***.***.com"
        
    # 3. Phone check
    digits = re.sub(r"\D+", "", s)
    if _PHONE_RE.match(s) or (digits.isdigit() and 7 <= len(digits) <= 15):
        if len(digits) >= 4:
            return f"***-***-{digits[-4:]}"
        return "***-***-1234"
        
    # 4. Long text check
    if len(s) > 50:
        return f"[TEXT: {len(s)} chars]"
        
    # 5. Name check (Proper Case words)
    if _NAME_RE.match(s) and len(s) < 30:
        return "[NAME]"
        
    # 6. ID/Numeric check
    try:
        float(s)
        return v # return original type
    except ValueError:
        pass
        
    return s

def _get_fallback_enrichment(dataset_name: str, ds_meta: Dict[str, Any]) -> Dict[str, Any]:
    """Provide a reliable fallback dict in case LLM is not available or fails."""
    columns_meta = ds_meta.get("columns") or {}
    probable_pks = []
    columns_hints = {}
    
    for col_name, col_info in columns_meta.items():
        if not isinstance(col_info, dict):
            continue
        sem = col_info.get("semantic_type", "unknown")
        is_pk = col_info.get("candidate_primary_key") or False
        if is_pk and sem in ("id", "numeric_id"):
            probable_pks.append(col_name)
            
        columns_hints[col_name] = {
            "semantic_type": "id" if sem == "numeric_id" else sem,
            "mixed_formats_suspected": False,
            "business_importance": "high" if is_pk else "medium",
            "cleaning_priority": "high" if is_pk else "medium",
            "outlier_action_hint": None
        }
        
    return {
        "table_grain": "one row per record",
        "business_entity": dataset_name.lower().replace("_raw", "").replace("_clean", ""),
        "probable_pk_columns": probable_pks,
        "columns": columns_hints
    }

def enrich_assessment_with_schema_llm(assessment_result: Dict[str, Any]) -> Dict[str, Any]:
    """Call the LLM to get column semantic/readiness hints and store them inside the assessment."""
    if not assessment_result or not isinstance(assessment_result, dict):
        return assessment_result or {}
        
    datasets = assessment_result.get("datasets") or {}
    if not datasets:
        return assessment_result

    cfg = load_llm_config(purpose="schema_enrichment")
    
    for ds_name, ds_meta in datasets.items():
        if not isinstance(ds_meta, dict):
            continue
            
        columns_meta = ds_meta.get("columns") or {}
        row_count = ds_meta.get("row_count") or 0
        
        # Prepare LLM payload
        llm_columns = []
        for col_name, col_info in columns_meta.items():
            if not isinstance(col_info, dict):
                continue
            
            raw_smp = col_info.get("raw_samples") or []
            masked_smp = [mask_pii_value(v) for v in raw_smp]
            
            llm_columns.append({
                "name": col_name,
                "dtype": col_info.get("dtype") or "object",
                "null_pct": col_info.get("null_percentage") or 0.0,
                "masked_samples": masked_smp[:5] # send top 5 masked samples to minimize tokens
            })
            
        payload = {
            "dataset": ds_name,
            "row_count": row_count,
            "columns": llm_columns
        }
        
        enrichment_result = None
        
        if cfg:
            try:
                if cfg.provider == "azure_openai":
                    from openai import AzureOpenAI  # type: ignore
                    client = AzureOpenAI(
                        api_key=cfg.api_key,
                        api_version=cfg.api_version or "2024-02-01",
                        azure_endpoint=cfg.endpoint,
                    )
                else:
                    from openai import OpenAI  # type: ignore
                    client = OpenAI(api_key=cfg.api_key)
                    
                resp = client.chat.completions.create(
                    model=cfg.model,
                    messages=[
                        {"role": "system", "content": _SYSTEM_PROMPT},
                        {"role": "user", "content": f"Analyze this dataset schema:\n{json.dumps(payload, ensure_ascii=False)}"}
                    ],
                    temperature=0.0,
                    response_format={"type": "json_object"},
                )
                
                raw_text = (resp.choices[0].message.content or "").strip()
                enrichment_result = json.loads(raw_text)
            except Exception as e:
                logger.error(f"LLM Schema Enrichment failed for {ds_name}: {e}. Using fallback hints.")
        else:
            logger.info(f"LLM not configured for schema enrichment purpose. Using fallback hints.")

        if not enrichment_result:
            enrichment_result = _get_fallback_enrichment(ds_name, ds_meta)
            
        # Store dataset-level enrichment hints
        ds_meta["llm_hints"] = {
            "table_grain": enrichment_result.get("table_grain", "one row per record"),
            "business_entity": enrichment_result.get("business_entity", "entity"),
            "probable_pk_columns": enrichment_result.get("probable_pk_columns") or []
        }
        
        # Merge column-level enrichment hints
        cols_enrichment = enrichment_result.get("columns") or {}
        for col_name, col_info in columns_meta.items():
            if not isinstance(col_info, dict):
                continue
            
            # Default hints
            hints = {
                "semantic_type": col_info.get("semantic_type") or "unknown",
                "mixed_formats_suspected": False,
                "business_importance": "medium",
                "cleaning_priority": "medium",
                "outlier_action_hint": None
            }
            
            # Override with LLM values if present
            if col_name in cols_enrichment:
                for k, v in cols_enrichment[col_name].items():
                    hints[k] = v
                    
            col_info["llm_hints"] = hints
            
    return assessment_result
