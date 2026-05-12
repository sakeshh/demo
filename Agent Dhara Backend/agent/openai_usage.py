"""Normalize OpenAI / Azure chat completion `usage` for UI and logging."""

from __future__ import annotations

from typing import Any, Dict, Optional


def usage_dict_from_response(resp: Any) -> Optional[Dict[str, int]]:
    usage = getattr(resp, "usage", None)
    if usage is None:
        return None
    out: Dict[str, int] = {}
    for k in ("prompt_tokens", "completion_tokens", "total_tokens"):
        v = getattr(usage, k, None)
        if v is None and isinstance(usage, dict):
            v = usage.get(k)
        if v is not None:
            try:
                out[k] = int(v)
            except (TypeError, ValueError):
                pass
    return out if out else None
