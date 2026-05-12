"""
LangChain ToolCallingAgent Router for Agent Dhara.

This module replaces the manual keyword-based intent classification with a
LangChain ToolCallingAgent that natively selects the right specialist tool
based on the user's message using LLM function/tool calling.

Architecture:
    User message
        ↓
    Safety checks (adversarial / OOD) — still rule-based, no LLM cost
        ↓
    LangChain ToolCallingAgent
        ↓  (LLM picks one of 5 tools based on message)
    Tool executes → returns specialist output
        ↓
    Reply sent to user

Tools registered (map 1:1 to existing specialists):
    report_generate  → intent 1  (full DQ report)
    top_issues       → intent 2  (list/rank issues)
    issue_filter     → intent 3  (filter by null/dup/email/phone)
    triage           → intent 4  (ETL prioritization)
    cross_dataset    → intent 5  (cross-dataset comparison)

Note:
    - The dataset and assessment context is injected via the tool's run context.
    - No raw rows are sent to the LLM — only the user message and tool descriptions.
    - Adversarial/OOD safety checks run BEFORE the LLM call (zero cost).
    - If LangChain is unavailable, falls back gracefully to legacy llm_router.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tool descriptions — these are what the LLM reads to pick the right tool.
# Clear, specific descriptions = better tool selection accuracy.
# ---------------------------------------------------------------------------
TOOL_DESCRIPTIONS: Dict[str, str] = {
    "report_generate": (
        "Generate a full data quality report, executive summary, markdown report, "
        "HTML report, or narrative summary of the assessed dataset(s). "
        "Use when user asks for a complete report, summary, or overview document."
    ),
    "top_issues": (
        "List, rank, or summarise the top data quality issues found in the dataset(s). "
        "Use when user asks what problems exist, what's wrong, the worst issues, "
        "red flags, biggest problems, how clean the data is, or wants an issue overview."
    ),
    "issue_filter": (
        "Filter and show only specific types of data quality issues: "
        "null/missing values, duplicate records, email format issues, "
        "phone number issues, or identifier/primary key problems. "
        "Use when user asks to see only a specific category of issues."
    ),
    "triage": (
        "Prioritize datasets for ETL loading. Determine which datasets are "
        "production-ready, blocked, or need manual review. "
        "Use when user asks what to fix first, load order, ETL risk, "
        "which dataset is safest, urgent issues, or fix priority."
    ),
    "cross_dataset": (
        "Compare two or more datasets. Analyze schema naming differences, "
        "foreign key / join key relationships, orphan records, load ordering "
        "across datasets. Use when user asks to compare datasets or check "
        "relationships between files."
    ),
}


def _build_langchain_tools(context: Dict[str, Any]):
    """
    Build LangChain StructuredTool objects for each specialist.
    Context (assessment result etc.) is captured via closure.
    """
    try:
        from langchain_core.tools import StructuredTool  # type: ignore
    except ImportError:
        logger.warning("langchain-core not installed. Run: pip install langchain-core")
        return None

    assessment = context.get("last_assessment_result") or {}

    def _tool_fn_factory(intent_id: int, tool_name: str):
        """Factory so each tool captures its own intent_id."""
        def _fn(message: str = "") -> Dict[str, Any]:
            # Return a structured result that chat_graph can act on
            return {
                "intent": intent_id,
                "tool": tool_name,
                "reason": f"langchain_tool_selected:{tool_name}",
                "source": "langchain_tool_agent",
                "message": message,
            }
        _fn.__name__ = tool_name
        return _fn

    intent_map = {
        "report_generate": 1,
        "top_issues":      2,
        "issue_filter":    3,
        "triage":          4,
        "cross_dataset":   5,
    }

    tools = []
    for tool_name, description in TOOL_DESCRIPTIONS.items():
        fn = _tool_fn_factory(intent_map[tool_name], tool_name)
        tool = StructuredTool.from_function(
            func=fn,
            name=tool_name,
            description=description,
        )
        tools.append(tool)

    return tools


def _get_llm_client_langchain():
    """
    Return a LangChain-compatible LLM client.
    Builds from existing model_config.py to avoid duplication.
    """
    try:
        from agent.model_config import load_llm_config  # type: ignore
        cfg = load_llm_config(purpose="router")
        if cfg is None:
            return None

        if cfg.provider == "azure_openai":
            from langchain_openai import AzureChatOpenAI  # type: ignore
            return AzureChatOpenAI(
                azure_endpoint=cfg.endpoint,
                azure_deployment=cfg.model,
                api_version=cfg.api_version or "2024-02-01",
                api_key=cfg.api_key,
                temperature=0.0,
                max_tokens=200,
            )
        else:
            from langchain_openai import ChatOpenAI  # type: ignore
            return ChatOpenAI(
                api_key=cfg.api_key,
                model=cfg.model,
                temperature=0.0,
                max_tokens=200,
            )
    except Exception as exc:
        logger.warning("LangChain LLM client unavailable: %s", exc)
        return None


def classify_intent_via_langchain(
    message: str,
    context: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """
    Primary intent classifier using LangChain ToolCallingAgent.

    Flow:
        1. Safety checks (adversarial / OOD) — rule-based, no LLM cost
        2. LangChain ToolCallingAgent selects the appropriate tool
        3. Returns intent dict compatible with chat_graph expectations

    Returns:
        dict with keys: intent (int), tool (str), reason (str), source (str)
        None if LangChain is unavailable (caller should fall back to legacy router)
    """
    from agent.conversational_intents import _is_adversarial, _is_ood  # type: ignore

    raw = (message or "").strip()
    if not raw:
        return None

    low = raw.lower()

    # ── Safety checks ALWAYS run first (rule-based, no LLM cost) ──────────
    if _is_adversarial(low):
        logger.info("ToolCallingAgent: adversarial detected, blocking.")
        return {"intent": 8, "reason": "adversarial_policy", "source": "safety_check"}

    if _is_ood(low):
        logger.info("ToolCallingAgent: OOD detected, blocking.")
        return {"intent": 7, "reason": "out_of_domain", "source": "safety_check"}

    # ── Check if assessment exists (some tools need it) ─────────────────
    has_assessment = bool(context.get("last_assessment_result"))
    if not has_assessment:
        logger.info("ToolCallingAgent: no assessment in context, returning clarify.")
        return {"intent": 6, "reason": "no_assessment_yet", "source": "context_check"}

    # ── Build LangChain agent ────────────────────────────────────────────
    llm = _get_llm_client_langchain()
    if llm is None:
        logger.warning("ToolCallingAgent: LLM unavailable, returning None for fallback.")
        return None

    tools = _build_langchain_tools(context)
    if tools is None:
        return None

    try:
        from langchain_core.messages import HumanMessage, SystemMessage  # type: ignore

        # Bind tools to LLM — this enables native function/tool calling
        llm_with_tools = llm.bind_tools(tools)

        system_content = (
            "You are Agent Dhara's intent classifier. "
            "The user has already run a data quality assessment. "
            "Based on their message, call the ONE most appropriate tool. "
            "Never answer the question yourself — only call a tool. "
            "If nothing fits data quality, do not call any tool."
        )

        response = llm_with_tools.invoke([
            SystemMessage(content=system_content),
            HumanMessage(content=raw),
        ])

        # Extract tool calls from response
        tool_calls = getattr(response, "tool_calls", None) or []

        if not tool_calls:
            # LLM chose no tool — treat as out-of-scope
            logger.info("ToolCallingAgent: LLM chose no tool for: %s", raw[:80])
            return {"intent": 7, "reason": "no_tool_selected_by_llm", "source": "langchain_tool_agent"}

        # Take the first tool call (agent selects one)
        first_call = tool_calls[0]
        tool_name = first_call.get("name", "") if isinstance(first_call, dict) else getattr(first_call, "name", "")

        intent_map = {
            "report_generate": 1,
            "top_issues":      2,
            "issue_filter":    3,
            "triage":          4,
            "cross_dataset":   5,
        }

        intent_id = intent_map.get(tool_name, 7)
        logger.info("ToolCallingAgent → tool=%s intent=%d", tool_name, intent_id)

        return {
            "intent": intent_id,
            "tool": tool_name,
            "reason": f"langchain_tool_agent_selected:{tool_name}",
            "source": "langchain_tool_agent",
        }

    except Exception as exc:
        logger.error("ToolCallingAgent error: %s", exc)
        return None
