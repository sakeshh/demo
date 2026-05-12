from __future__ import annotations

import os
import re
from typing import Any, Dict, List


_EMAIL_RE = re.compile(r"^([^@]{2})[^@]*(@.*)$")


def _mask_email(s: str) -> str:
    m = _EMAIL_RE.match(s.strip())
    if not m:
        return "***"
    return f"{m.group(1)}***{m.group(2)}"


def _mask_phone(s: str) -> str:
    digits = re.sub(r"\D+", "", s)
    if len(digits) <= 4:
        return "***"
    return f"***{digits[-4:]}"


def _mask_generic(s: str) -> str:
    if len(s) <= 4:
        return "***"
    return s[:2] + "***" + s[-2:]


def is_sensitive_column(name: str) -> bool:
    n = (name or "").lower()
    return any(
        k in n
        for k in (
            "password",
            "passwd",
            "secret",
            "token",
            "api_key",
            "apikey",
            "ssn",
            "pan",
            "credit",
            "card",
            "email",
            "phone",
            "mobile",
            "address",
        )
    )


def mask_value(col: str, v: Any) -> Any:
    if v is None:
        return None
    if isinstance(v, (int, float, bool)):
        return v
    s = str(v)
    c = (col or "").lower()
    if "email" in c:
        return _mask_email(s)
    if "phone" in c or "mobile" in c:
        return _mask_phone(s)
    if any(k in c for k in ("password", "secret", "token", "api_key", "apikey")):
        return "***"
    return _mask_generic(s)


def mask_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    # Allow callers/operators to disable masking when operating on synthetic/non-sensitive data.
    # Default remains masked to avoid accidental exposure in UI previews.
    if (os.environ.get("DISABLE_PII_MASKING") or "").strip().lower() in ("1", "true", "yes", "y", "on"):
        return rows or []
    out: List[Dict[str, Any]] = []
    for r in rows or []:
        if not isinstance(r, dict):
            continue
        rr: Dict[str, Any] = {}
        for k, v in r.items():
            if is_sensitive_column(str(k)):
                rr[str(k)] = mask_value(str(k), v)
            else:
                rr[str(k)] = v
        out.append(rr)
    return out

