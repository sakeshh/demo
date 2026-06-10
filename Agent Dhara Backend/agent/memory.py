"""
Agent Dhara Memory Layer.

Two memory systems:
  1. Zep (knowledge/entity/preference/temporal) — requires ZEP_API_KEY
  2. SQLite pipeline_runs (operational metrics) — always available

All Zep functions degrade to no-op when ZEP_API_KEY is not set.
"""
from __future__ import annotations
import os
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

def _zep_enabled() -> bool:
    return bool(os.getenv("ZEP_API_KEY") and os.getenv("DHARA_ZEP_ENABLED"))

def get_zep_client():
    """Returns Zep client or None if not configured."""
    if not _zep_enabled():
        return None
    try:
        from zep_cloud.client import Zep
        return Zep(api_key=os.getenv("ZEP_API_KEY"),
                   base_url=os.getenv("ZEP_BASE_URL", "https://api.getzep.com"))
    except ImportError:
        logger.warning("zep-python not installed. Run: pip install zep-python>=2.0.0")
        return None

def get_zep_checkpointer():
    """Returns ZepCheckpointSaver for LangGraph or None."""
    if not _zep_enabled():
        return None
    try:
        from zep_cloud.langchain import ZepCheckpointSaver
        return ZepCheckpointSaver(api_key=os.getenv("ZEP_API_KEY"))
    except ImportError:
        return None

def remember_fact(session_id: str, fact: str, entity: str = "") -> None:
    """Store a business rule or preference as a Zep fact."""
    client = get_zep_client()
    if not client:
        return
    try:
        client.memory.add(
            session_id=session_id,
            messages=[{"role": "user", "content": fact,
                       "metadata": {"entity": entity, "type": "business_rule"}}],
        )
    except Exception as e:
        logger.debug("Zep remember_fact failed: %s", e)

def recall_dataset_facts(user_id: str, dataset_name: str) -> List[str]:
    """Retrieve all known facts/rules about a dataset."""
    client = get_zep_client()
    if not client:
        return []
    try:
        results = client.memory.search(
            session_id=user_id,
            text=f"rules and preferences for {dataset_name}",
            limit=15,
        )
        return [r.message.content for r in (results or []) if r.message]
    except Exception as e:
        logger.debug("Zep recall_dataset_facts failed: %s", e)
        return []

def add_run_episode(session_id: str, summary: str) -> None:
    """Record a pipeline run as a Zep temporal episode."""
    client = get_zep_client()
    if not client:
        return
    try:
        client.memory.add(
            session_id=session_id,
            messages=[{"role": "assistant", "content": summary,
                       "metadata": {"type": "pipeline_episode"}}],
        )
    except Exception as e:
        logger.debug("Zep add_run_episode failed: %s", e)

def get_session_context_summary(session_id: str) -> str:
    """Get Zep's AI-generated memory summary for this session."""
    client = get_zep_client()
    if not client:
        return ""
    try:
        mem = client.memory.get(session_id=session_id)
        return mem.summary.content if mem and mem.summary else ""
    except Exception:
        return ""
