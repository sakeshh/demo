"""
LLM-assisted narrative on top of deterministic assessment (Azure OpenAI).

Uses only aggregated metadata (counts, issue types) — no raw cell values — to reduce PII exposure.
Set AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_API_KEY, AZURE_OPENAI_DEPLOYMENT.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from typing import Any, Dict, List, Optional

try:
    from openai import AzureOpenAI
    _OPENAI_OK = True
except ImportError:
    AzureOpenAI = None  # type: ignore
    _OPENAI_OK = False


def _azure_cfg() -> Optional[Dict[str, str]]:
    import os
    endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT") or os.environ.get("OPENAI_API_BASE")
    key = os.environ.get("AZURE_OPENAI_API_KEY") or os.environ.get("OPENAI_API_KEY")
    deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT") or os.environ.get("AZURE_OPENAI_CHAT_DEPLOYMENT")
    api_version = os.environ.get("AZURE_OPENAI_API_VERSION", "2024-02-01")
    if not endpoint or not key or not deployment:
        return None
    return {"endpoint": endpoint.rstrip("/"), "key": key, "deployment": deployment, "api_version": api_version}


def build_compact_assessment_payload(assessment_result: Dict[str, Any], max_chars: int = 14000) -> str:
    """Structured summary for the model (no raw data values)."""
    datasets = assessment_result.get("datasets") or {}
    dq = assessment_result.get("data_quality_issues") or {}
    dq_ds = dq.get("datasets") or {}
    glob = dq.get("global_issues") or {}

    ds_list: List[Dict[str, Any]] = []
    for name, meta in datasets.items():
        issues = (dq_ds.get(name) or {}).get("issues") or []
        by_type: Dict[str, int] = defaultdict(int)
        for it in issues:
            by_type[str(it.get("type") or "?")] += 1
        top_types = sorted(by_type.items(), key=lambda x: -x[1])[:12]
        cols = meta.get("columns") or {}
        sem = defaultdict(int)
        for c in cols.values():
            sem[str(c.get("semantic_type") or "unknown")] += 1
        ds_list.append({
            "dataset": name,
            "rows": meta.get("row_count"),
            "columns": meta.get("column_count"),
            "issues_total": len(issues),
            "high_severity": sum(1 for x in issues if x.get("severity") == "high"),
            "medium_severity": sum(1 for x in issues if x.get("severity") == "medium"),
            "issue_types": dict(top_types),
            "semantic_mix": dict(sem),
        })

    rels = assessment_result.get("relationships") or []
    rel_compact = []
    for r in rels[:12]:
        rel_compact.append({
            "pair": f"{r.get('dataset_a')}.{r.get('column_a')} ↔ {r.get('dataset_b')}.{r.get('column_b')}",
            "cardinality": r.get("cardinality"),
            "shared_keys": r.get("overlap_count"),
        })

    payload = {
        "instruction": "Analyze this assessment metadata only. Do not invent row-level facts.",
        "datasets": ds_list,
        "relationships": rel_compact,
        "global": {
            "orphan_value_sets": len(glob.get("orphan_foreign_keys") or []),
            "orphan_key_rows": len(glob.get("relationship_row_issues") or []),
            "cross_dataset_mixed_type": len(glob.get("cross_dataset_inconsistencies") or []),
            "relationship_warnings": len(glob.get("relationship_warnings") or []),
        },
    }
    s = json.dumps(payload, ensure_ascii=False, indent=2)
    if len(s) > max_chars:
        s = s[: max_chars - 20] + "\n…(truncated)"
    return s


_SYSTEM = """You are a senior data quality analyst. You receive ONLY aggregated metadata from an automated data assessment (no raw values).
Respond with a single JSON object (no markdown fences) using exactly these keys:
{
  "executive_summary": "string, 2-4 sentences for business stakeholders",
  "top_risks": [ {"title": "short", "detail": "one sentence"}, ... ],
  "recommended_next_steps": [ "actionable step", ... ],
  "data_lineage_comment": "string or null — one sentence on cross-table relationships if relevant"
}
Rules: max 5 items in top_risks, max 7 in recommended_next_steps. Do not claim specific cell values. If metadata is thin, say so."""


def _parse_llm_json(text: str) -> Optional[Dict[str, Any]]:
    if not text:
        return None
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{[\s\S]*\}", text)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass
    return None


def generate_llm_insights(assessment_result: Dict[str, Any]) -> Dict[str, Any]:
    """
    Call Azure OpenAI to produce narrative insights. Merged into assessment under llm_insights.

    Returns:
      success, parsed (dict with executive_summary, top_risks, ...), error, model, raw_preview
    """
    out: Dict[str, Any] = {
        "success": False,
        "parsed": None,
        "error": None,
        "model": None,
        "raw_preview": "",
    }
    if not _OPENAI_OK:
        out["error"] = "openai package not installed (pip install openai)"
        return out
    cfg = _azure_cfg()
    if not cfg:
        out["error"] = (
            "Azure OpenAI not configured. Set AZURE_OPENAI_ENDPOINT, "
            "AZURE_OPENAI_API_KEY, AZURE_OPENAI_DEPLOYMENT"
        )
        return out

    user_content = build_compact_assessment_payload(assessment_result)
    client = AzureOpenAI(
        api_key=cfg["key"],
        api_version=cfg["api_version"],
        azure_endpoint=cfg["endpoint"],
    )
    kwargs = {
        "model": cfg["deployment"],
        "messages": [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": user_content},
        ],
        "max_tokens": 2500,
        "temperature": 0.25,
    }
    text = ""
    try:
        try:
            response = client.chat.completions.create(
                **kwargs,
                response_format={"type": "json_object"},
            )
        except Exception:
            response = client.chat.completions.create(**kwargs)
        text = (response.choices[0].message.content or "").strip()
        out["model"] = cfg["deployment"]
        out["raw_preview"] = text[:1500]
        parsed = _parse_llm_json(text)
        if not parsed:
            out["error"] = "Model response was not valid JSON"
            return out
        # Normalize keys
        out["parsed"] = {
            "executive_summary": str(parsed.get("executive_summary") or "").strip(),
            "top_risks": parsed.get("top_risks") if isinstance(parsed.get("top_risks"), list) else [],
            "recommended_next_steps": (
                parsed.get("recommended_next_steps")
                if isinstance(parsed.get("recommended_next_steps"), list)
                else []
            ),
            "data_lineage_comment": parsed.get("data_lineage_comment"),
        }
        out["success"] = True
        return out
    except Exception as e:
        out["error"] = str(e)
        out["raw_preview"] = text[:2000] if text else ""
        return out
