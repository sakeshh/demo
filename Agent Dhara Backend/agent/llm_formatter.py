"""
LLM Formatter — converts raw specialist output into natural replies.

Phase 3 enhancement: the LLM reformats the structured specialist output
into conversational language guided by FORMATTER_SYSTEM_PROMPT.
The LLM CANNOT hallucinate because it only sees the specialist output.

Usage:
    from agent.llm_formatter import format_specialist_output
    reply = format_specialist_output(specialist_raw, user_message)
"""
from __future__ import annotations
import logging
from typing import Optional

from agent.agent_system_prompt import FORMATTER_SYSTEM_PROMPT

logger = logging.getLogger(__name__)

# If specialist output is shorter than this, skip LLM formatting (already concise)
_MIN_LENGTH_FOR_FORMATTING = 120


def _get_llm_client():
    try:
        from agent.model_config import get_llm_client
        return get_llm_client()
    except Exception as exc:
        logger.warning("LLM formatter client unavailable: %s", exc)
        return None


def format_specialist_output(
    specialist_output: str,
    user_message: str,
    force: bool = False,
) -> str:
    """
    Reformat specialist output using the LLM for a natural reply.

    Args:
        specialist_output: Raw text returned by any specialist.
        user_message:      The original user question.
        force:             If True, always call LLM even for short outputs.

    Returns:
        Formatted string — falls back to specialist_output if LLM fails.
    """
    if not specialist_output or not specialist_output.strip():
        return specialist_output

    # Skip LLM for very short outputs — already clean enough
    if not force and len(specialist_output.strip()) < _MIN_LENGTH_FOR_FORMATTING:
        return specialist_output

    client = _get_llm_client()
    if client is None:
        return specialist_output  # Graceful fallback

    prompt = (
        f"User question: {user_message}\n\n"
        f"Specialist data output:\n{specialist_output}\n\n"
        "Reformat the specialist output into a clean, natural reply. "
        "Do NOT add any information not present in the specialist output."
    )

    try:
        response = client.invoke([
            {"role": "system", "content": FORMATTER_SYSTEM_PROMPT},
            {"role": "user",   "content": prompt},
        ])
        result = response if isinstance(response, str) else getattr(response, "content", str(response))
        return result.strip() if result and result.strip() else specialist_output

    except Exception as exc:
        logger.warning("LLM formatter failed, using raw specialist output: %s", exc)
        return specialist_output
