from __future__ import annotations

import fnmatch
import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

logger = logging.getLogger(__name__)

DEFAULT_MANIFEST = Path(__file__).resolve().parent.parent / "config" / "metadata_manifest.yaml"


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(base)
    for k, v in (override or {}).items():
        if k in out and isinstance(out[k], dict) and isinstance(v, dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_metadata_manifest(path: Optional[str] = None) -> Dict[str, Any]:
    p = Path(path or os.getenv("DHARA_METADATA_MANIFEST", str(DEFAULT_MANIFEST)))
    if not p.is_file():
        return {"version": "0", "datasets": {}}
    try:
        with open(p, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
        if not isinstance(raw, dict):
            return {"version": "0", "datasets": {}}
        raw.setdefault("datasets", {})
        return raw
    except Exception as e:
        logger.warning("metadata manifest load failed: %s", e)
        return {"version": "0", "datasets": {}, "_error": str(e)}


def manifest_hash(manifest: Dict[str, Any]) -> str:
    try:
        blob = json.dumps(manifest, sort_keys=True, default=str)
    except Exception:
        blob = str(manifest)
    return hashlib.sha256(blob.encode("utf-8", errors="ignore")).hexdigest()[:16]


def resolve_dataset_manifest(dataset_name: str, manifest: Dict[str, Any]) -> Tuple[Dict[str, Any], Optional[str]]:
    """
    Return (resolved_entry, matched_key) for a dataset name using exact and glob match.
    """
    ds = manifest.get("datasets") or {}
    if not isinstance(ds, dict):
        return {}, None
    if dataset_name in ds and isinstance(ds[dataset_name], dict):
        return ds[dataset_name], dataset_name
    lower = dataset_name.lower()
    for k, v in ds.items():
        if not isinstance(v, dict):
            continue
        pat = str(k).lower()
        if fnmatch.fnmatch(lower, pat) or pat in lower or lower in pat:
            return v, str(k)
    return {}, None


def validate_manifest_against_schema(manifest_entry: Dict[str, Any], columns: List[str]) -> List[str]:
    """Return human-readable validation errors (empty if OK)."""
    errs: List[str] = []
    colset = {c.lower() for c in columns}
    pk = manifest_entry.get("primary_key") or []
    if isinstance(pk, list):
        for c in pk:
            if str(c).lower() not in colset:
                errs.append(f"primary_key column missing from data: {c}")
    cols_meta = manifest_entry.get("columns") or {}
    if isinstance(cols_meta, dict):
        for c in cols_meta.keys():
            if str(c).lower() not in colset:
                errs.append(f"manifest column not in data: {c}")
    return errs


def glossary_from_manifest(manifest_entry: Dict[str, Any]) -> Dict[str, str]:
    """column_name -> business term / meaning."""
    out: Dict[str, str] = {}
    cols = manifest_entry.get("columns") or {}
    if not isinstance(cols, dict):
        return out
    for name, meta in cols.items():
        if isinstance(meta, dict):
            m = meta.get("meaning") or meta.get("description")
            if m:
                out[str(name)] = str(m)
    return out


def critical_columns_from_manifest(manifest_entry: Dict[str, Any]) -> List[str]:
    out: List[str] = []
    pk = manifest_entry.get("primary_key") or []
    if isinstance(pk, list):
        out.extend(str(x) for x in pk)
    cols = manifest_entry.get("columns") or {}
    if isinstance(cols, dict):
        for name, meta in cols.items():
            if isinstance(meta, dict) and str(meta.get("business_importance", "")).lower() == "high":
                if name not in out:
                    out.append(str(name))
    return out
