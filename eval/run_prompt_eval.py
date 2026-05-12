#!/usr/bin/env python3
"""
Batch-send Agent Dhara MCP /chat prompts from the CSV prompt bank.

Prerequisites:
  - Backend running, e.g. `python -m agent.mcp_server` (default http://127.0.0.1:8000)

Usage:
  python eval/run_prompt_eval.py --dry-run
  set BACKEND_AUTH_TOKEN=your_secret   # same as backend env
  python eval/run_prompt_eval.py --base-url http://127.0.0.1:8000 --out eval/results_run.jsonl
  python eval/run_prompt_eval.py --start 41 --end 50 --pause 3 --backend-token your_secret
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List


def read_prompt_rows(csv_path: Path) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    with csv_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for raw in reader:
            rows.append({k: (raw.get(k) or "").strip() for k in reader.fieldnames if k})
    return rows


def post_chat(
    base_url: str,
    session_id: str,
    message: str,
    timeout: float,
    *,
    backend_token: str | None,
) -> Dict[str, Any]:
    url = base_url.rstrip("/") + "/chat"
    body = json.dumps({"session_id": session_id, "message": message}).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    tok = (backend_token or "").strip()
    if tok:
        headers["X-Backend-Token"] = tok
    req = urllib.request.Request(
        url,
        data=body,
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _configure_stdout_utf8() -> None:
    """Avoid UnicodeEncodeError on Windows consoles when replies contain emoji."""
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def main() -> int:
    _configure_stdout_utf8()
    root = Path(__file__).resolve().parent.parent
    default_csv = root / "eval" / "agent_dhara_50_prompt_bank.csv"

    ap = argparse.ArgumentParser(description="Run Agent Dhara /chat prompt bank.")
    ap.add_argument("--csv", type=Path, default=default_csv, help="Prompt bank CSV path")
    ap.add_argument("--base-url", default="http://127.0.0.1:8000", help="MCP server base URL")
    ap.add_argument(
        "--backend-token",
        default="",
        help="Value for X-Backend-Token (defaults to BACKEND_AUTH_TOKEN env if set)",
    )
    ap.add_argument("--session-id", default="eval-session", help="Chat session id (shared = context carries)")
    ap.add_argument("--fresh-session-each", action="store_true", help="Use eval-session-<n> per prompt")
    ap.add_argument("--start", type=int, default=1, help="First Prompt# (inclusive)")
    ap.add_argument("--end", type=int, default=50, help="Last Prompt# (inclusive)")
    ap.add_argument("--pause", type=float, default=0.0, help="Seconds between POSTs")
    ap.add_argument("--timeout", type=float, default=120.0, help="HTTP timeout per request")
    ap.add_argument("--out", type=Path, help="Append JSON lines (prompt metadata + reply)")
    ap.add_argument("--dry-run", action="store_true", help="Print prompts only; no HTTP")
    args = ap.parse_args()

    rows = read_prompt_rows(args.csv)
    selected = [r for r in rows if r.get("Prompt#", "").isdigit() and args.start <= int(r["Prompt#"]) <= args.end]
    selected.sort(key=lambda r: int(r["Prompt#"]))

    if not selected:
        print(f"No rows in range {args.start}-{args.end} in {args.csv}", file=sys.stderr)
        return 2

    token = args.backend_token.strip() or (os.environ.get("BACKEND_AUTH_TOKEN") or "").strip()

    if args.dry_run:
        for r in selected:
            print(f"{r['Prompt#']:>2} [{r.get('Category', '')}] {r.get('Prompt', '')[:80]}...")
        print(f"--dry-run: {len(selected)} prompts")
        return 0

    out_f = args.out.open("a", encoding="utf-8") if args.out else None

    for r in selected:
        num = int(r["Prompt#"])
        prompt = r.get("Prompt", "")
        sid = args.session_id
        if args.fresh_session_each:
            sid = f"{args.session_id}-{num}"
        payload: Dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "prompt_num": num,
            "category": r.get("Category", ""),
            "prompt": prompt,
            "session_id": sid,
            "error": None,
            "reply": None,
            "raw": None,
        }
        try:
            data = post_chat(args.base_url, sid, prompt, args.timeout, backend_token=token or None)
            payload["reply"] = data.get("reply")
            payload["raw_ok"] = data.get("ok")
            payload["raw"] = data if len(json.dumps(data)) < 120_000 else {"truncated": True, "reply": data.get("reply")}
        except urllib.error.HTTPError as e:
            payload["error"] = f"HTTP {e.code}: {(e.read() or b'').decode('utf-8', errors='replace')[:2000]}"
        except urllib.error.URLError as e:
            payload["error"] = f"URL error: {e.reason}"
        except Exception as e:  # noqa: BLE001
            payload["error"] = repr(e)

        line = json.dumps(payload, ensure_ascii=False)
        print(line)
        if out_f:
            out_f.write(line + "\n")
            out_f.flush()

        if args.pause > 0:
            time.sleep(args.pause)

    if out_f:
        out_f.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
