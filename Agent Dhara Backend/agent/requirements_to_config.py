"""
Requirement → sources config adapter (skeleton).

Goal:
- Accept a structured requirement object from the frontend
- Produce a minimal sources config (dict) compatible with MasterAgent.load_and_select_sources

This is intentionally conservative: it only selects locations (by id/type) and
leaves connection details in sources.yaml.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence


def requirements_to_selected_sources(requirements: Optional[Dict[str, Any]]) -> List[str]:
    """
    Extract selected source ids/types from a requirement object.

    Expected shape (flexible):
      {
        "sources": ["primary", "assessment_input"]  # ids or types
      }
    """
    if not requirements:
        return []
    src = requirements.get("sources")
    if isinstance(src, list):
        return [str(x) for x in src if str(x).strip()]
    return []


def build_user_request_text(user_request: str, requirements: Optional[Dict[str, Any]]) -> str:
    """
    Build a prompt-like text for MasterAgent.plan().
    """
    base = (user_request or "").strip()
    if not requirements:
        return base
    # Keep it readable; do NOT dump raw rows. Only metadata/constraints.
    parts: List[str] = [base] if base else []
    req = dict(requirements)
    req.pop("raw_data", None)
    parts.append("REQUIREMENTS:")
    for k, v in req.items():
        parts.append(f"- {k}: {v}")
    return "\n".join(parts).strip()

