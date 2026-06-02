"""
Append-only manifest / semantic contract history (JSONL index + per-run JSON files).

Never raises to callers of save_* — returns status dict with optional warning.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

INDEX_NAME = "manifest_contract_index.jsonl"
CONTRACTS_DIR = "contracts"


def _default_root() -> Path:
    env = os.getenv("DHARA_MANIFEST_HISTORY_DIR", "").strip()
    if env:
        return Path(env)
    here = Path(__file__).resolve().parent.parent
    return here / "output" / "governance_manifest_history"


def _ensure_dirs(root: Path) -> bool:
    try:
        root.mkdir(parents=True, exist_ok=True)
        (root / CONTRACTS_DIR).mkdir(parents=True, exist_ok=True)
        return True
    except Exception as e:
        logger.warning("manifest_version_store: cannot create %s: %s", root, e)
        return False


def _contract_sha256(contract: Dict[str, Any]) -> str:
    try:
        blob = json.dumps(contract, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    except Exception:
        blob = str(contract).encode("utf-8", errors="ignore")
    return hashlib.sha256(blob).hexdigest()


def save_contract_snapshot(
    run_id: str,
    contract: Dict[str, Any],
    *,
    schema_hash: Optional[str] = None,
    storage_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Persist contract JSON and append an index line (append-only JSONL).

    Returns metadata including ``saved``, ``warning`` (if any), ``contract_sha256``, paths.
    """
    rid = str(run_id or "unknown").strip() or "unknown"
    root = Path(storage_path) if storage_path else _default_root()
    out: Dict[str, Any] = {
        "saved": False,
        "run_id": rid,
        "contract_sha256": "",
        "schema_hash": schema_hash or "",
        "index_path": str(root / INDEX_NAME),
        "contract_path": "",
        "warning": "",
    }
    if not isinstance(contract, dict):
        out["warning"] = "invalid_contract_type"
        return out
    if not _ensure_dirs(root):
        out["warning"] = "storage_unavailable"
        return out

    try:
        h = _contract_sha256(contract)
        out["contract_sha256"] = h
        short = h[:12]
        fname = f"{_safe_segment(rid)}_{short}.json"
        cpath = root / CONTRACTS_DIR / fname
        cpath.write_text(json.dumps(contract, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
        out["contract_path"] = str(cpath)
        ts = datetime.now(timezone.utc).isoformat()
        index_line = {
            "run_id": rid,
            "saved_at": ts,
            "contract_sha256": h,
            "schema_hash": schema_hash or "",
            "contract_relpath": f"{CONTRACTS_DIR}/{fname}",
        }
        with open(root / INDEX_NAME, "a", encoding="utf-8") as f:
            f.write(json.dumps(index_line, ensure_ascii=False) + "\n")
        out["saved"] = True
        out["index_line"] = index_line
    except Exception as e:
        logger.warning("save_contract_snapshot failed: %s", e)
        out["warning"] = str(e)[:500]
    return out


def _safe_segment(s: str) -> str:
    t = "".join(c if c.isalnum() or c in "._-" else "_" for c in (s or "").strip())[:120]
    return t or "run"


def load_contract_snapshot(
    run_id: str,
    storage_path: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Load the latest contract JSON for ``run_id`` from the index."""
    rid = str(run_id or "").strip()
    if not rid:
        return None
    root = Path(storage_path) if storage_path else _default_root()
    idx = root / INDEX_NAME
    if not idx.is_file():
        return None
    last_rel: Optional[str] = None
    try:
        for line in idx.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if str(rec.get("run_id") or "") == rid:
                last_rel = str(rec.get("contract_relpath") or "")
    except Exception as e:
        logger.debug("load_contract_snapshot read index: %s", e)
        return None
    if not last_rel:
        return None
    cfile = root / last_rel
    if not cfile.is_file():
        return None
    try:
        return json.loads(cfile.read_text(encoding="utf-8"))
    except Exception:
        return None


def list_contract_snapshots(storage_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """Return parsed index records in file order (oldest first)."""
    root = Path(storage_path) if storage_path else _default_root()
    idx = root / INDEX_NAME
    if not idx.is_file():
        return []
    rows: List[Dict[str, Any]] = []
    try:
        for line in idx.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    except Exception as e:
        logger.debug("list_contract_snapshots: %s", e)
    return rows


def diff_contract_snapshots(
    run_id_a: str,
    run_id_b: str,
    storage_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Shallow structural diff of two stored contracts (by dataset keys + overall confidence)."""
    ca = load_contract_snapshot(run_id_a, storage_path)
    cb = load_contract_snapshot(run_id_b, storage_path)
    if ca is None or cb is None:
        return {"ok": False, "error": "missing_snapshot", "run_id_a": run_id_a, "run_id_b": run_id_b}
    keys_a = set(ca.keys())
    keys_b = set(cb.keys())
    by_a = ca.get("by_dataset") if isinstance(ca.get("by_dataset"), dict) else {}
    by_b = cb.get("by_dataset") if isinstance(cb.get("by_dataset"), dict) else {}
    ds_a = set(by_a.keys()) if isinstance(by_a, dict) else set()
    ds_b = set(by_b.keys()) if isinstance(by_b, dict) else set()
    return {
        "ok": True,
        "top_level_keys_added": sorted(keys_b - keys_a),
        "top_level_keys_removed": sorted(keys_a - keys_b),
        "datasets_added": sorted(ds_b - ds_a),
        "datasets_removed": sorted(ds_a - ds_b),
        "overall_confidence": {
            "a": ca.get("overall_semantic_confidence"),
            "b": cb.get("overall_semantic_confidence"),
        },
    }
