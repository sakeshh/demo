from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List, Optional


def register_raw_payload(
    registry: Dict[str, Any],
    *,
    dataset: str,
    payload_id: str,
    content: Any = None,
    content_sha256: Optional[str] = None,
    note: str = "",
) -> Dict[str, Any]:
    """
    Append a registry entry for nested JSON/XML before flattening.
    Mutates registry dict under key 'raw_payloads' (list).
    """
    reg = registry.setdefault("raw_payloads", [])
    if not isinstance(reg, list):
        reg = []
        registry["raw_payloads"] = reg
    h = content_sha256
    if h is None and content is not None:
        try:
            blob = content if isinstance(content, (bytes, str)) else json.dumps(content, default=str)
            if isinstance(blob, str):
                blob = blob.encode("utf-8", errors="ignore")
            h = hashlib.sha256(blob).hexdigest()[:16]
        except Exception:
            h = None
    entry = {
        "dataset": dataset,
        "payload_id": payload_id,
        "sha256_16": h,
        "note": note[:500],
    }
    reg.append(entry)
    return entry


def empty_registry() -> Dict[str, Any]:
    return {"raw_payloads": []}
