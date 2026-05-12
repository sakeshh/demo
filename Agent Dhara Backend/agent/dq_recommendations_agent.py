"""
LLM-assisted DQ cleaning recommendations.

Consumes merged DQ issues and produces a prioritized cleaning plan.
Designed for production: returns structured JSON; falls back to rule-based hints if LLM not configured.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from agent.model_config import load_llm_config
from agent.openai_usage import usage_dict_from_response
from agent.session_store import SessionJSONEncoder


@dataclass(frozen=True)
class DQRecommendations:
    recommendations: List[Dict[str, Any]]
    summary: Dict[str, Any]


_SYSTEM = """
You are a data quality remediation planner.
Given data quality issues across datasets, output a prioritized, actionable cleaning plan.

Return ONLY valid JSON. No markdown.

JSON schema:
{
  "recommendations": [
    {
      "priority": 1,
      "dataset": "string|null",
      "column": "string|null",
      "issue_type": "string",
      "severity": "high|medium|low",
      "why_it_matters": "string",
      "suggested_fix": "string",
      "example_sql": "string|null",
      "example_pandas": "string|null",
      "risk": "string"
    }
  ],
  "summary": {
    "top_themes": ["string", "..."],
    "notes": "string"
  }
}
""".strip()


def _fallback(dq: Dict[str, Any]) -> DQRecommendations:
    # Minimal safe fallback: promote existing per-issue recommendation fields if present.
    recs: List[Dict[str, Any]] = []
    datasets = (dq.get("datasets") or {}) if isinstance(dq.get("datasets"), dict) else {}
    for ds_name, block in datasets.items():
        issues = (block.get("issues") or []) if isinstance(block, dict) else []
        for it in issues[:60]:
            if not isinstance(it, dict):
                continue
            recs.append(
                {
                    "priority": 99,
                    "dataset": ds_name,
                    "column": it.get("column"),
                    "issue_type": it.get("type") or it.get("issue_type") or "issue",
                    "severity": it.get("severity") or "medium",
                    "why_it_matters": it.get("message") or "",
                    "suggested_fix": it.get("recommendation") or "Review and remediate based on business rules.",
                    "example_sql": None,
                    "example_pandas": None,
                    "risk": "Fallback mode (LLM not configured). Validate before applying changes.",
                }
            )
    return DQRecommendations(
        recommendations=recs[:80],
        summary={
            "top_themes": [],
            "notes": "LLM not configured; returned fallback recommendations based on existing rule hints.",
        },
    )


class DQRecommendationsAgent:
    def recommend(
        self,
        *,
        merged_dq: Dict[str, Any],
        user_intent: str = "",
    ) -> Tuple[DQRecommendations, Optional[Dict[str, int]]]:
        cfg = load_llm_config(purpose="dq_recommendations")
        if cfg is None:
            return _fallback(merged_dq), None

        payload = {
            "user_intent": user_intent,
            "data_quality_issues": merged_dq,
            "constraints": {
                "prefer_safe_fixes": True,
                "no_destructive_steps_without_warning": True,
            },
        }
        prompt = json.dumps(payload, ensure_ascii=False, cls=SessionJSONEncoder)
        try:
            if cfg.provider == "azure_openai":
                from openai import AzureOpenAI  # type: ignore

                client = AzureOpenAI(
                    api_key=cfg.api_key,
                    api_version=cfg.api_version or "2024-02-01",
                    azure_endpoint=cfg.endpoint,
                )
                resp = client.chat.completions.create(
                    model=cfg.model,
                    messages=[{"role": "system", "content": _SYSTEM}, {"role": "user", "content": prompt}],
                    temperature=0.2,
                    max_tokens=900,
                )
            else:
                from openai import OpenAI  # type: ignore

                client = OpenAI(api_key=cfg.api_key)
                resp = client.chat.completions.create(
                    model=cfg.model,
                    messages=[{"role": "system", "content": _SYSTEM}, {"role": "user", "content": prompt}],
                    temperature=0.2,
                    max_tokens=900,
                )
            raw = (resp.choices[0].message.content or "").strip()
            obj = json.loads(raw)
            recs = obj.get("recommendations")
            summ = obj.get("summary")
            if not isinstance(recs, list):
                recs = []
            if not isinstance(summ, dict):
                summ = {"notes": "LLM returned invalid summary; using empty summary."}
            # Normalize priority
            for i, r in enumerate(recs):
                if isinstance(r, dict) and "priority" not in r:
                    r["priority"] = i + 1
            usage = usage_dict_from_response(resp)
            return DQRecommendations(recommendations=recs[:120], summary=summ), usage
        except Exception:
            return _fallback(merged_dq), None


def dq_recommendations_to_dict(r: DQRecommendations) -> Dict[str, Any]:
    return {"recommendations": r.recommendations, "summary": r.summary}

