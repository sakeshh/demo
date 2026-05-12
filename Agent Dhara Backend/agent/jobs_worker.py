from __future__ import annotations

import threading
import time
from typing import Any, Dict, Optional

from agent.jobs_store import add_event, claim_next_job, update_job_status


def _run_job(job: Dict[str, Any]) -> Dict[str, Any]:
    job_id = job.get("job_id")
    kind = job.get("kind")
    inp = job.get("input") or {}
    add_event(job_id=job_id, level="debug", message=f"JobWorker processing {kind}", data={"gx_enabled": inp.get("gx_enabled")})
    
    if kind == "assess":
        from agent.langgraph_orchestrator import run_orchestrator

        return run_orchestrator(
            user_request=str(inp.get("user_request") or ""),
            sources_path=str(inp.get("sources_path") or "config/sources.yaml"),
            selected_sources=inp.get("selected_sources") or [],
            job_id=job_id,
            gx_enabled=bool(inp.get("gx_enabled", False))
        )

    if kind == "chat":
        from agent.chat_graph import run_chat

        return run_chat(
            session_id=str(inp.get("session_id") or "default"), 
            message=str(inp.get("message") or ""),
            job_id=job_id,
            gx_enabled=bool(inp.get("gx_enabled", False))
        )

    raise ValueError(f"Unknown job kind: {kind}")


class JobWorker:
    def __init__(self) -> None:
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            job = claim_next_job()
            if not job:
                time.sleep(0.25)
                continue
            job_id = job["job_id"]
            try:
                add_event(job_id=job_id, level="info", message="started")
                result = _run_job(job)
                update_job_status(job_id, status="succeeded", result=result)
                add_event(job_id=job_id, level="info", message="succeeded")
            except Exception as e:
                update_job_status(job_id, status="failed", error=str(e))
                add_event(job_id=job_id, level="error", message="failed", data={"error": str(e)})

