"""
LangSmith tracing setup for Agent Dhara.

Usage:
    Call `init_langsmith()` once at app startup (e.g. in main.py).
    Set these env vars to enable tracing:

        LANGCHAIN_TRACING_V2=true
        LANGCHAIN_API_KEY=<your-langsmith-api-key>
        LANGCHAIN_PROJECT=agent-dhara          # optional, defaults to "agent-dhara"
        LANGCHAIN_ENDPOINT=https://api.smith.langchain.com  # optional

    If LANGCHAIN_API_KEY is missing or tracing is disabled, this module is a no-op.
    No crash, no side effects — tracing is fully optional.

What gets traced automatically once enabled:
    - Every LLM call (prompt, response, token usage, latency)
    - Every LangChain tool call (tool name, input, output)
    - LangGraph node transitions
    - The full ToolCallingAgent ReAct loop
"""
from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

_TRACING_INITIALIZED = False


def init_langsmith() -> bool:
    """
    Initialize LangSmith tracing if env vars are configured.

    Returns:
        True  — tracing is active
        False — tracing is disabled (no API key or LANGCHAIN_TRACING_V2 != 'true')
    """
    global _TRACING_INITIALIZED
    if _TRACING_INITIALIZED:
        return os.getenv("LANGCHAIN_TRACING_V2", "").lower() == "true"

    api_key = os.getenv("LANGCHAIN_API_KEY", "")
    tracing_enabled = os.getenv("LANGCHAIN_TRACING_V2", "").lower() == "true"

    if not tracing_enabled or not api_key:
        logger.info(
            "LangSmith tracing disabled. "
            "Set LANGCHAIN_TRACING_V2=true and LANGCHAIN_API_KEY to enable."
        )
        _TRACING_INITIALIZED = True
        return False

    # Set project name (defaults to 'agent-dhara')
    if not os.getenv("LANGCHAIN_PROJECT"):
        os.environ["LANGCHAIN_PROJECT"] = "agent-dhara"

    try:
        # LangSmith client validates connection on first use.
        # We do a lightweight check here to log status clearly.
        from langsmith import Client  # type: ignore

        client = Client(api_key=api_key)
        project = os.getenv("LANGCHAIN_PROJECT", "agent-dhara")
        logger.info(
            "LangSmith tracing ACTIVE — project: '%s' | endpoint: %s",
            project,
            os.getenv("LANGCHAIN_ENDPOINT", "https://api.smith.langchain.com"),
        )
        _TRACING_INITIALIZED = True
        return True

    except ImportError:
        logger.warning(
            "langsmith package not installed. Run: pip install langsmith"
        )
        _TRACING_INITIALIZED = True
        return False
    except Exception as exc:
        logger.warning("LangSmith init failed (tracing disabled): %s", exc)
        _TRACING_INITIALIZED = True
        return False


def get_tracer_or_none():
    """
    Return a LangSmith RunTree tracer if tracing is active, else None.
    Use this to manually wrap non-LangChain code in a trace span.

    Example:
        tracer = get_tracer_or_none()
        if tracer:
            with tracer.trace("my_custom_step", inputs={"key": value}) as run:
                result = do_something()
                run.end(outputs={"result": result})
    """
    if os.getenv("LANGCHAIN_TRACING_V2", "").lower() != "true":
        return None
    try:
        from langsmith import Client  # type: ignore
        return Client()
    except Exception:
        return None
