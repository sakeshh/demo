"""
LLM Router — intent classifier for Agent Dhara chat.

## ROUTING STRATEGY (v2 — LangChain ToolCallingAgent primary)

    User message
        ↓
    [LAYER 1] Safety checks — adversarial / OOD  (rule-based, free, instant)
        ↓ (if safe)
    [LAYER 2] LangChain ToolCallingAgent          (PRIMARY — LLM picks tool natively)
        ↓ (if LangChain unavailable / error)
    [LAYER 3] Legacy LLM JSON router              (FALLBACK — kept for reliability)
        ↓ (if LLM unavailable)
    [LAYER 4] Keyword matching in conversational_intents.py  ← COMMENTED OUT as primary,
                                                               still importable if needed

## TO RESTORE KEYWORD ROUTING AS PRIMARY:
    In classify_intent_for_chat(), uncomment the block marked
    "# ── [LEGACY KEYWORD ROUTER — uncomment to re-enable as primary] ──"
    and comment out the langchain_tool_router call below it.
"""
from __future__ import annotations
import json
import logging
from typing import Any, Dict, Optional

from agent.agent_system_prompt import (
    ROUTER_SYSTEM_PROMPT,
    OUT_OF_SCOPE_REPLY,
    ADVERSARIAL_REPLY,
)

logger = logging.getLogger(__name__)

# Tool name → intent ID mapping (matches conversational_intents.py)
TOOL_TO_INTENT: Dict[str, int] = {
    "report_generate": 1,
    "top_issues":      2,
    "issue_filter":    3,
    "triage":          4,
    "cross_dataset":   5,
    "none":            7,
}


def _get_llm_client():
    """Lazy-import LLM client from existing model_config to avoid circular imports."""
    try:
        from agent.model_config import get_llm_client
        return get_llm_client()
    except Exception as exc:
        logger.warning("LLM client unavailable: %s", exc)
        return None


def llm_classify_intent(message: str) -> Optional[Dict[str, Any]]:
    """
    Legacy LLM JSON router — FALLBACK only.
    Called when LangChain ToolCallingAgent is unavailable or errors.

    Sends ~100-150 tokens per call. Never sends raw dataset rows.
    Returns dict with keys: intent, tool, reason, source='llm'
    """
    client = _get_llm_client()
    if client is None:
        return None

    try:
        response = client.invoke([
            {"role": "system", "content": ROUTER_SYSTEM_PROMPT},
            {"role": "user",   "content": f'Classify this message: "{message}"'},
        ])

        raw = response if isinstance(response, str) else getattr(response, "content", str(response))
        raw = raw.strip().strip("```json").strip("```").strip()

        parsed = json.loads(raw)
        tool   = parsed.get("tool", "none")
        reason = parsed.get("reason", "llm classified")
        intent = TOOL_TO_INTENT.get(tool, 7)

        logger.info("[FALLBACK] Legacy LLM router → tool=%s intent=%d reason=%s", tool, intent, reason)
        return {"intent": intent, "tool": tool, "reason": reason, "source": "llm_fallback"}

    except json.JSONDecodeError as exc:
        logger.warning("Legacy LLM router returned non-JSON: %s", exc)
        return None
    except Exception as exc:
        logger.error("Legacy LLM router error: %s", exc)
        return None


def classify_intent_for_chat(
    message: str,
    context: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """
    Main entry point for chat intent classification.

    Routing order:
        1. LangChain ToolCallingAgent (PRIMARY)
        2. Legacy LLM JSON router (FALLBACK if LangChain fails)

    NOTE — KEYWORD ROUTER:
        The keyword-based classify_intent() from conversational_intents.py
        is PRESERVED but commented out as primary router below.
        To re-enable keyword routing as first pass, uncomment the block below.
    """

    # ── [LEGACY KEYWORD ROUTER — uncomment to re-enable as primary] ──────
    # This was the original routing layer — fast, free, but brittle.
    # Uncomment the lines below to restore keyword matching as Layer 1.
    #
    # from agent.conversational_intents import classify_intent as _kw_classify
    # kw_result = _kw_classify(message, context)
    # if kw_result is not None:
    #     logger.info("[KEYWORD] Matched intent=%d reason=%s", kw_result["intent"], kw_result.get("reason"))
    #     return kw_result
    # ── end keyword router block ──────────────────────────────────────────

    # ── [LAYER 1] LangChain ToolCallingAgent (PRIMARY) ────────────────────
    try:
        from agent.langchain_tool_router import classify_intent_via_langchain  # type: ignore
        result = classify_intent_via_langchain(message, context)
        if result is not None:
            logger.info(
                "[LANGCHAIN] ToolCallingAgent → intent=%d source=%s",
                result.get("intent", -1),
                result.get("source", ""),
            )
            return result
    except Exception as exc:
        logger.warning("[LANGCHAIN] ToolCallingAgent failed, falling back: %s", exc)

    # ── [LAYER 2] Legacy LLM JSON router (FALLBACK) ───────────────────────
    logger.info("[FALLBACK] LangChain unavailable — using legacy LLM JSON router.")
    return llm_classify_intent(message)


def get_out_of_scope_reply() -> str:
    return OUT_OF_SCOPE_REPLY


def get_adversarial_reply() -> str:
    return ADVERSARIAL_REPLY
