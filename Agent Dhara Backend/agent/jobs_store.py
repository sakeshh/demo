from __future__ import annotations

import json
import os
import sqlite3
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple


def _db_path() -> str:
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out_dir = os.path.join(root, "output")
    os.makedirs(out_dir, exist_ok=True)
    return os.path.join(out_dir, "jobs.sqlite3")


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_db_path(), timeout=30, check_same_thread=False)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS jobs (
          job_id TEXT PRIMARY KEY,
          created_at REAL NOT NULL,
          updated_at REAL NOT NULL,
          status TEXT NOT NULL,
          kind TEXT NOT NULL,
          input_json TEXT NOT NULL,
          result_json TEXT,
          error TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS job_events (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          job_id TEXT NOT NULL,
          ts REAL NOT NULL,
          level TEXT NOT NULL,
          message TEXT NOT NULL,
          data_json TEXT,
          FOREIGN KEY(job_id) REFERENCES jobs(job_id)
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_job_events_job_id ON job_events(job_id, id)")
    return conn


def create_job(*, kind: str, input: Dict[str, Any]) -> str:
    job_id = str(uuid.uuid4())
    now = time.time()
    conn = _connect()
    try:
        conn.execute(
            "INSERT INTO jobs(job_id, created_at, updated_at, status, kind, input_json) VALUES(?,?,?,?,?,?)",
            (job_id, now, now, "queued", kind, json.dumps(input, ensure_ascii=False, default=str)),
        )
        conn.commit()
        add_event(job_id=job_id, level="info", message="queued", data={"kind": kind})
        return job_id
    finally:
        conn.close()


def add_event(*, job_id: str, level: str, message: str, data: Optional[Dict[str, Any]] = None) -> None:
    conn = _connect()
    try:
        conn.execute(
            "INSERT INTO job_events(job_id, ts, level, message, data_json) VALUES(?,?,?,?,?)",
            (
                job_id,
                time.time(),
                level,
                message,
                json.dumps(data, ensure_ascii=False, default=str) if data is not None else None,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def update_job_status(job_id: str, *, status: str, result: Optional[Dict[str, Any]] = None, error: Optional[str] = None) -> None:
    conn = _connect()
    try:
        conn.execute(
            "UPDATE jobs SET updated_at=?, status=?, result_json=?, error=? WHERE job_id=?",
            (
                time.time(),
                status,
                json.dumps(result, ensure_ascii=False, default=str) if result is not None else None,
                error,
                job_id,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def fetch_job(job_id: str) -> Optional[Dict[str, Any]]:
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT job_id, created_at, updated_at, status, kind, input_json, result_json, error FROM jobs WHERE job_id=?",
            (job_id,),
        ).fetchone()
        if not row:
            return None
        return {
            "job_id": row[0],
            "created_at": row[1],
            "updated_at": row[2],
            "status": row[3],
            "kind": row[4],
            "input": json.loads(row[5]) if row[5] else {},
            "result": json.loads(row[6]) if row[6] else None,
            "error": row[7],
        }
    finally:
        conn.close()


def claim_next_job(*, kinds: Optional[List[str]] = None) -> Optional[Dict[str, Any]]:
    """
    Best-effort claim: fetch one queued job and mark running.
    """
    conn = _connect()
    try:
        if kinds:
            q = "SELECT job_id FROM jobs WHERE status='queued' AND kind IN ({}) ORDER BY created_at LIMIT 1".format(
                ",".join(["?"] * len(kinds))
            )
            row = conn.execute(q, tuple(kinds)).fetchone()
        else:
            row = conn.execute("SELECT job_id FROM jobs WHERE status='queued' ORDER BY created_at LIMIT 1").fetchone()
        if not row:
            return None
        job_id = row[0]
        conn.execute("UPDATE jobs SET status='running', updated_at=? WHERE job_id=?", (time.time(), job_id))
        conn.commit()
    finally:
        conn.close()
    add_event(job_id=job_id, level="info", message="running")
    return fetch_job(job_id)


def fetch_events(job_id: str, *, after_id: int = 0, limit: int = 200) -> List[Dict[str, Any]]:
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT id, ts, level, message, data_json FROM job_events WHERE job_id=? AND id>? ORDER BY id LIMIT ?",
            (job_id, int(after_id), int(limit)),
        ).fetchall()
        out = []
        for r in rows:
            out.append(
                {
                    "id": r[0],
                    "ts": r[1],
                    "level": r[2],
                    "message": r[3],
                    "data": json.loads(r[4]) if r[4] else None,
                }
            )
        return out
    finally:
        conn.close()

