"""
Agentic Rules Resolution — Uses an LLM to parse unstructured business notes and autonomously 
update structured ETL parameters and resolve manual review queue items.
"""
from __future__ import annotations

import json
import os
import logging
from typing import Any, Dict, List, Optional

try:
    from openai import AzureOpenAI, OpenAI
except ImportError:
    AzureOpenAI = OpenAI = None  # type: ignore

logger = logging.getLogger("agent.agentic_rules")

AGENTIC_SYSTEM_PROMPT = """You are Agent Dhara's core reasoning engine. 
Your job is to read unstructured business 'notes', the current structured 'business_rules', and the 'manual_review' queue, and autonomously map the user's intent to structured configurations.

You MUST return a JSON object exactly like this:
{
  "updated_business_rules": {
    "outlier_strategy": "flag", // options: flag, clip, cap, drop
    "never_drop_rows": true     // options: true, false
  },
  "manual_review_resolutions": [
    {
      "id": "item_id_from_input",
      "resolution_id": "resolution_id_from_options"
    }
  ]
}

Instructions:
1. 'updated_business_rules': Infer the best toggles based on the 'notes'. For example, if notes say "clip extreme values", set outlier_strategy to "clip". If they say "drop rows", set never_drop_rows to false. Only include keys you are overriding.
2. 'manual_review_resolutions': Look at the provided manual review items. If the user's notes imply a resolution (e.g. dropping a column, clipping, keeping as is), match it to one of the valid resolution_options provided for that item.
3. Return ONLY valid JSON. If the notes are empty or irrelevant, return empty objects/arrays.
"""

def _get_client():
    az_ep = os.getenv("AZURE_OPENAI_ENDPOINT")
    az_key = os.getenv("AZURE_OPENAI_API_KEY")
    if az_ep and az_key and AzureOpenAI:
        return AzureOpenAI(
            azure_endpoint=az_ep,
            api_key=az_key,
            api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-02-01"),
        )
    ok = os.getenv("OPENAI_API_KEY")
    if ok and OpenAI:
        return OpenAI(api_key=ok)
    return None

def analyze_agentic_intent(plan: Dict[str, Any], rules: Dict[str, Any]) -> Dict[str, Any]:
    notes = str(rules.get("notes") or "").strip()
    if not notes:
        return {"updated_business_rules": {}, "manual_review_resolutions": []}

    client = _get_client()
    if not client:
        return {"updated_business_rules": {}, "manual_review_resolutions": []}

    manual_review = plan.get("manual_review") or []
    
    payload = {
        "business_rules": {
            "never_drop_rows": rules.get("never_drop_rows"),
            "outlier_strategy": rules.get("outlier_strategy"),
            "notes": notes
        },
        "manual_review_queue": [
            {
                "id": m.get("id"),
                "column": m.get("column"),
                "issue_type": m.get("issue_type"),
                "message": m.get("message"),
                "options": [opt.get("id") for opt in (m.get("resolution_options") or [])]
            }
            for m in manual_review
        ]
    }

    try:
        resp = client.chat.completions.create(
            model=os.getenv("AZURE_OPENAI_DEPLOYMENT") or os.getenv("OPENAI_MODEL", "gpt-4o"),
            messages=[
                {"role": "system", "content": AGENTIC_SYSTEM_PROMPT},
                {"role": "user", "content": f"Analyze this ETL context and resolve based on the notes:\n{json.dumps(payload, indent=2)}"}
            ],
            temperature=0.1,
            response_format={"type": "json_object"},
        )
        raw = resp.choices[0].message.content or "{}"
        parsed = json.loads(raw)
        return parsed
    except Exception as e:
        logger.error(f"Agentic reasoning failed: {e}")
        return {"updated_business_rules": {}, "manual_review_resolutions": []}
