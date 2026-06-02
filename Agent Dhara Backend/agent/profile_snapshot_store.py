from __future__ import annotations

import hashlib
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def _snapshot_dir() -> Path:
    base = Path(os.getenv("DHARA_SNAPSHOT_DIR", "")) if os.getenv("DHARA_SNAPSHOT_DIR") else None
    if base and base.is_dir():
        return base
    here = Path(__file__).resolve().parent.parent / "output" / "reports" / "snapshots"
    here.mkdir(parents=True, exist_ok=True)
    return here


def _dataset_slug(name: str) -> str:
    h = hashlib.sha256(name.encode("utf-8")).hexdigest()[:12]
    safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in name)[:60]
    return f"{safe}_{h}"


def build_profile_fingerprint(ds_meta: Dict[str, Any]) -> Dict[str, Any]:
    """Compact snapshot payload for drift comparison."""
    cols = ds_meta.get("columns") or {}
    col_summary: Dict[str, Any] = {}
    if isinstance(cols, dict):
        for cname in sorted(cols.keys(), key=lambda x: str(x).lower()):
            c = cols.get(cname) or {}
            if not isinstance(c, dict):
                continue
            col_summary[str(cname)] = {
                "dtype": str(c.get("dtype") or ""),
                "null_pct": float(c.get("null_percentage") or 0),
                "unique": int(c.get("unique_count") or 0),
                "semantic_type": str(c.get("semantic_type") or ""),
            }
    return {
        "row_count": int(ds_meta.get("row_count") or 0),
        "column_count": int(ds_meta.get("column_count") or len(col_summary)),
        "columns": col_summary,
    }


def save_snapshot(
    dataset_name: str,
    fingerprint: Dict[str, Any],
    *,
    run_id: Optional[str] = None,
) -> Path:
    root = _snapshot_dir()
    slug = _dataset_slug(dataset_name)
    ds_dir = root / slug
    ds_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    rid = (run_id or "run")[:80]
    path = ds_dir / f"{ts}_{rid}.json"
    payload = {
        "dataset_name": dataset_name,
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "run_id": rid,
        "fingerprint": fingerprint,
    }
    try:
        path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    except Exception as e:
        logger.warning("snapshot write failed: %s", e)
    # also write "latest.json"
    try:
        (ds_dir / "latest.json").write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    except Exception:
        pass
    return path


def load_latest_snapshot(dataset_name: str) -> Optional[Dict[str, Any]]:
    root = _snapshot_dir()
    slug = _dataset_slug(dataset_name)
    latest = root / slug / "latest.json"
    if not latest.is_file():
        # try most recent file
        ds_dir = root / slug
        if not ds_dir.is_dir():
            return None
        files = sorted(ds_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        for p in files:
            if p.name == "latest.json":
                continue
            latest = p
            break
        else:
            return None
    try:
        return json.loads(latest.read_text(encoding="utf-8"))
    except Exception:
        return None
