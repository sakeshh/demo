from __future__ import annotations

import os
import time
import uuid
from typing import Dict, Optional, Tuple

from fastapi import HTTPException, Request


def get_request_id(req: Request) -> str:
    rid = req.headers.get("x-request-id") or req.headers.get("x-correlation-id")
    return (rid or str(uuid.uuid4())).strip()


def require_backend_token(req: Request) -> None:
    """
    Shared-secret auth between Next.js and FastAPI.
    Set BACKEND_AUTH_TOKEN in backend env.
    Send X-Backend-Token from Next.js.
    """
    expected = (os.environ.get("BACKEND_AUTH_TOKEN") or "").strip()
    if not expected:
        raise HTTPException(status_code=500, detail="BACKEND_AUTH_TOKEN is not set on backend")
    got = (req.headers.get("x-backend-token") or "").strip()
    if got != expected:
        raise HTTPException(status_code=401, detail="Unauthorized")


class InMemoryRateLimiter:
    """
    Simple in-memory per-IP rate limiter (best-effort).
    For multi-instance production, replace with Redis.
    """

    def __init__(self, *, max_requests: int = 60, window_seconds: int = 60) -> None:
        self.max_requests = int(max_requests)
        self.window_seconds = int(window_seconds)
        self._buckets: Dict[str, Tuple[int, float]] = {}

    def check(self, key: str) -> None:
        now = time.time()
        count, start = self._buckets.get(key, (0, now))
        if now - start >= self.window_seconds:
            count, start = 0, now
        count += 1
        self._buckets[key] = (count, start)
        if count > self.max_requests:
            raise HTTPException(status_code=429, detail="Rate limit exceeded")


def client_ip(req: Request) -> str:
    # If behind proxy, consider X-Forwarded-For (only if you control proxy)
    xff = (req.headers.get("x-forwarded-for") or "").split(",")[0].strip()
    if xff:
        return xff
    return req.client.host if req.client else "unknown"

