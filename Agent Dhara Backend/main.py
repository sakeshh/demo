#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
main.py — SQL Runner + Intelligent Data Assessment (DB + Filesystem + Azure Blob) + Promptflow

- Loads all SQL DBs + filesystem paths + all Azure Blob assessment containers; profiles; DQ; relationships.
- Exports: JSON, Markdown, HTML; optional PF input/eval; optional upload to Azure Blob.
- Improvements: structured logging, config-driven DQ thresholds, sorted blob order (idempotent), --skip-azure.
"""







import os
import sys
import re
import time
import json
import html as html_module
import hashlib
import argparse
import logging
from collections import defaultdict
from typing import Dict, Any, Tuple, List, Optional
from pathlib import Path

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)

logger = logging.getLogger(__name__)

# Load local .env automatically (developer convenience).
# This avoids Windows `setx` quoting/truncation problems and keeps secrets out of code/config.
try:
    from dotenv import load_dotenv  # type: ignore
except Exception:
    load_dotenv = None  # type: ignore

if load_dotenv is not None:
    try:
        load_dotenv(os.path.join(PROJECT_DIR, ".env"), override=False)
    except Exception:
        pass


def _doctor_env_hint() -> None:
    """
    Print a short preflight summary of env/config that commonly breaks Azure access.
    This intentionally avoids printing secret values.
    """
    keys = [
        "AZURE_STORAGE_CONNECTION_STRING",
        "AZURE_STORAGE_ACCOUNT_NAME",
        "AZURE_STORAGE_ACCOUNT_KEY",
        "AZURE_ASSESSMENT_CONTAINER",
        "AZURE_OUTPUT_CONTAINER",
        "AZURE_SQL_SERVER",
        "AZURE_SQL_DATABASE",
        "AZURE_SQL_USERNAME",
        "AZURE_SQL_PASSWORD",
    ]
    present = {k: (True if os.environ.get(k) else False) for k in keys}
    missing = [k for k, ok in present.items() if not ok]
    if missing:
        logger.warning(
            "Azure env preflight: missing %d var(s): %s. "
            "Tip: create '%s' and set vars there (or set in current shell).",
            len(missing),
            ", ".join(missing),
            os.path.join(PROJECT_DIR, ".env"),
        )
    else:
        logger.info("Azure env preflight: all required vars appear set.")

try:
    from agent.intelligent_data_assessment import load_and_profile, load_dq_thresholds
except ImportError:
    try:
        ida_path = Path(PROJECT_DIR) / "agent" / "intelligent_data_assessment.py"
        if not ida_path.is_file():
            ida_path = Path(PROJECT_DIR) / "intelligent_data_assessment.py"
        import importlib.util
        spec = importlib.util.spec_from_file_location("ida_dyn", ida_path)
        ida = importlib.util.module_from_spec(spec)  # type: ignore
        if spec and spec.loader:
            spec.loader.exec_module(ida)  # type: ignore
        load_and_profile = ida.load_and_profile  # type: ignore
        load_dq_thresholds = getattr(ida, "load_dq_thresholds", lambda p: {})  # type: ignore
    except Exception as e:
        logger.critical("Could not import intelligent_data_assessment: %s", e)
        sys.exit(1)

try:
    import yaml  # type: ignore
except Exception:
    yaml = None

try:
    from connectors.azure_sql_pythonnet import AzureSQLPythonNetConnector
except Exception as e:
    logger.info("SQL connector not available (pythonnet/.NET required for database): %s", e)
    AzureSQLPythonNetConnector = None  # type: ignore

try:
    from connectors.azure_blob_storage import AzureBlobStorageConnector
    AZURE_BLOB_AVAILABLE = True
except Exception as e:
    logger.info("Azure Blob Storage connector not available: %s", e)
    AZURE_BLOB_AVAILABLE = False


def to_json_safe(obj):
    """Convert non-JSON-native types to safe representations."""
    try:
        import datetime as _dt
        if isinstance(obj, (_dt.datetime, _dt.date, _dt.time)):
            return obj.isoformat()
    except Exception:
        pass
    try:
        import numpy as _np
        import pandas as _pd
        if isinstance(obj, (_pd.Timestamp,)):
            return obj.isoformat()
        if isinstance(obj, (_np.integer, _np.floating, _np.bool_)):
            return obj.item()
        if isinstance(obj, _np.ndarray):
            return obj.tolist()
    except Exception:
        pass
    if isinstance(obj, (set, tuple)):
        return list(obj)
    return str(obj)


def load_config(path: str) -> Dict[str, Any]:
    """Load YAML or JSON config."""
    if not os.path.isfile(path):
        logger.critical("Config file not found: %s", path)
        sys.exit(2)

    def _expand_env(obj: Any) -> Any:
        """
        Recursively expand ${VAR} (and ${VAR:default}) in config values.
        Leaves the placeholder unchanged if VAR is unset and no default is provided.
        """
        if isinstance(obj, dict):
            return {k: _expand_env(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [_expand_env(v) for v in obj]
        if not isinstance(obj, str):
            return obj
        pattern = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::([^}]*))?\}")

        def _sub(m: "re.Match") -> str:
            var = m.group(1)
            default = m.group(2)
            val = os.environ.get(var)
            if val:
                return val
            if default is not None:
                return default
            return m.group(0)

        return pattern.sub(_sub, obj)

    ext = os.path.splitext(path)[1].lower()
    with open(path, "r", encoding="utf-8") as f:
        if ext == ".json":
            return _expand_env(json.load(f))
        if ext in (".yaml", ".yml"):
            if yaml is None:
                logger.critical("PyYAML required for YAML configs. pip install pyyaml")
                sys.exit(3)
            return _expand_env(yaml.safe_load(f) or {})
        logger.critical("Unsupported config format: %s", ext)
        sys.exit(4)


def get_db_connection_cfg(cfg: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Return the first database connection block from locations, or None."""
    for loc in cfg.get("locations", []):
        if (loc.get("type") or "").lower() == "database":
            return loc.get("connection", {}) or {}
    return None


def build_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="SQL Runner + Intelligent Data Assessment",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--sources", default="config/sources.yaml", help="Path to YAML or JSON config")
    p.add_argument("--rows", type=int, default=5, help="Preview N rows per SQL table")
    p.add_argument("--list-only", action="store_true", help="Only list SQL tables")
    p.add_argument("--schema-only", action="store_true", help="Only show SQL schema")
    p.add_argument("--with-schema", action="store_true", help="List SQL tables AND show schema")
    p.add_argument("--debug", action="store_true", help="Enable debug logging")
    p.add_argument("--stream-file", default=None, help="Path to JSON array of records to validate")
    p.add_argument("--stream-name", default="stream", help="Logical name for stream dataset")
    p.add_argument(
        "--blob-names",
        default="",
        help=(
            "Comma-separated blob filenames to assess (Azure Blob only). "
            "If set, only these blobs are loaded from the azure_blob container."
        ),
    )
    p.add_argument("--export-json", default=None, help="Write full JSON assessment (whole report)")
    p.add_argument("--export-report", default=None, help="Write Markdown report (whole report)")
    p.add_argument("--export-html", default=None, help="Write HTML report (whole report)")
    p.add_argument(
        "--reports-dir",
        default=None,
        help="Directory for overall report.* outputs (report.json/.md/.html).",
    )
    p.add_argument("--export-pf-input", default=None, help="Write Promptflow dq_profile JSON")
    p.add_argument("--export-pf-eval", default=None, help="Write PF evaluation PASS/WARN/FAIL")
    p.add_argument("--export-to-azure", action="store_true", help="Upload outputs to Azure Blob")
    p.add_argument("--azure-only", action="store_true", help="Save only to Azure (no local files)")
    p.add_argument("--azure-output-container", default="output", help="Output container name")
    p.add_argument("--skip-azure", action="store_true", help="Do not access Azure Blob (offline)")
    p.add_argument("--dq-thresholds", default=None, help="Path to dq_thresholds.yaml (default: config/dq_thresholds.yaml)")
    p.add_argument(
        "--export-manifest",
        metavar="PATH",
        default=None,
        help="Write cleaning_manifest.json to PATH "
        "(default with --reports-dir: <reports-dir>/cleaning_manifest.json unless overridden here).",
    )
    p.add_argument(
        "--llm-insights",
        action="store_true",
        help="After assessment, call Azure OpenAI for executive summary & risks (needs AZURE_OPENAI_* env).",
    )
    p.add_argument(
        "--evaluate",
        default="auto",
        choices=["auto", "interactive", "sql", "blob", "local", "stream", "all"],
        help=(
            "Which data to evaluate: sql|blob|local|stream|all, interactive menu, or auto "
            "(menu if stdin is a TTY, else all). Stream uses --stream-file or prompts for path."
        ),
    )
    return p.parse_args()


def split_schema_table(full: str) -> Tuple[str, str]:
    return full.split(".", 1) if "." in full else ("dbo", full)


def _quote_two_part_name_fallback(table: str) -> str:
    if "." in table:
        schema, name = table.split(".", 1)
    else:
        schema, name = "dbo", table
    return f"[{schema}].[{name}]"


def print_schema_info_schema(connector, table: str) -> bool:
    schema, tbl = split_schema_table(table)
    try:
        from connectors.azure_sql_pythonnet import SqlCommand
        conn = connector._connect()
        conn.Open()
        try:
            cmd = SqlCommand("""
                SELECT COLUMN_NAME, DATA_TYPE
                FROM INFORMATION_SCHEMA.COLUMNS
                WHERE TABLE_SCHEMA = @schema AND TABLE_NAME = @table
                ORDER BY ORDINAL_POSITION
            """, conn)
            cmd.Parameters.AddWithValue("@schema", schema)
            cmd.Parameters.AddWithValue("@table", tbl)
            reader = cmd.ExecuteReader()
            print("Columns:")
            any_rows = False
            while reader.Read():
                any_rows = True
                print(f"  - {reader.GetString(0)}: {reader.GetString(1)}")
            return any_rows
        finally:
            conn.Close()
    except Exception as e:
        logger.info("INFORMATION_SCHEMA failed for %s: %s", table, e)
        return False


def print_schema_top0(connector, table: str) -> bool:
    try:
        from connectors.azure_sql_pythonnet import SqlCommand
        conn = connector._connect()
        conn.Open()
        try:
            table_q = getattr(connector, "_quote_two_part_name", _quote_two_part_name_fallback)(table)
            cmd = SqlCommand(f"SELECT TOP 0 * FROM {table_q}", conn)
            reader = cmd.ExecuteReader()
            print("Columns (TOP 0):")
            for i in range(reader.FieldCount):
                col = reader.GetName(i)
                try:
                    dtype = str(reader.GetFieldType(i))
                except Exception:
                    dtype = "unknown"
                print(f"  - {col}: {dtype}")
            return reader.FieldCount > 0
        finally:
            conn.Close()
    except Exception as e:
        logger.error("TOP 0 failed for %s: %s", table, e)
        return False


# ========================= Markdown Report =========================

def _fmt_pct(x: Optional[float]) -> str:
    try:
        return f"{round(float(x) * 100, 2)}%"
    except Exception:
        return str(x)


def _endpoint_to_dataset(endpoint: str, names_by_len: List[str]) -> Optional[str]:
    """Map relationship endpoint 'dataset.column' to dataset key."""
    for ds in names_by_len:
        if endpoint == ds or (endpoint.startswith(ds + ".") and len(endpoint) > len(ds)):
            return ds
    return None


def _result_for_datasets(result: Dict[str, Any], ds_names: List[str]) -> Dict[str, Any]:
    """Subset assessment for multiple datasets (same source path / group)."""
    ns = frozenset(ds_names)
    names_sorted = sorted(ns, key=len, reverse=True)
    datasets = {k: v for k, v in (result.get("datasets") or {}).items() if k in ns}
    dq = result.get("data_quality_issues", {}) or {}
    dq_ds = {k: v for k, v in (dq.get("datasets") or {}).items() if k in ns}
    rels = []
    for r in result.get("relationships") or []:
        df = _endpoint_to_dataset(r.get("from") or "", names_sorted)
        dt = _endpoint_to_dataset(r.get("to") or "", names_sorted)
        if df in ns and dt in ns:
            rels.append(r)
    orphans = dq.get("global_issues", {}).get("orphan_foreign_keys") or []
    orphans_sub = []
    for o in orphans:
        df = _endpoint_to_dataset(o.get("from") or "", names_sorted)
        dt = _endpoint_to_dataset(o.get("to") or "", names_sorted)
        if df in ns and dt in ns:
            orphans_sub.append(o)
    xds = dq.get("global_issues", {}).get("cross_dataset_inconsistencies") or []
    xds_sub = [x for x in xds if x.get("dataset") in ns]
    rri = dq.get("global_issues", {}).get("relationship_row_issues") or []
    rri_sub = [x for x in rri if x.get("dataset") in ns]
    rw = dq.get("global_issues", {}).get("relationship_warnings") or []
    rw_sub = [
        w for w in rw
        if w.get("datasets") and all(d in ns for d in w["datasets"])
    ]
    return {
        "datasets": datasets,
        "relationships": rels,
        "data_quality_issues": {
            "datasets": dq_ds,
            "global_issues": {
                "orphan_foreign_keys": orphans_sub,
                "cross_dataset_inconsistencies": xds_sub,
                "relationship_row_issues": rri_sub,
                "relationship_warnings": rw_sub,
            },
        },
    }


def _per_dataset_dir_name(ds_name: str, assigned: set) -> str:
    """Filesystem-safe unique folder name under per_dataset/."""
    raw = re.sub(r"[^\w\-.]+", "_", (ds_name or "dataset").replace("\\", "__").replace("/", "__"))
    raw = raw.strip("._")[:72] or "dataset"
    base = raw or "dataset"
    name = base
    n = 2
    while name in assigned:
        name = f"{base}_{n}"
        n += 1
    assigned.add(name)
    return name


def _source_root_to_folder_name(source_root: str) -> str:
    """Stable folder name under reports/by_path/ for a source location."""
    if not source_root:
        return "unknown_source"
    if source_root == "__database__":
        return "database"
    if source_root.startswith("azure_blob:"):
        tail = source_root.split(":", 1)[1] or "root"
        h = hashlib.sha256(source_root.encode("utf-8")).hexdigest()[:10]
        safe = re.sub(r"[^\w\-]+", "_", tail.replace("/", "__"))[:48]
        return f"azure_{safe}_{h}"
    h = hashlib.sha256(source_root.encode("utf-8")).hexdigest()[:10]
    base = os.path.basename(source_root.rstrip(os.sep)) or "source"
    safe = re.sub(r"[^\w\-]+", "_", base)[:48]
    return f"{safe}_{h}"


def _attach_run_metadata_and_suggestions(
    result: Dict[str, Any],
    t0_perf: float,
    started_at_iso: str,
    sources_path: str,
) -> None:
    """Add run timing, DQ rollups, and report suggestion metadata."""
    from datetime import datetime, timezone

    dq = result.get("data_quality_issues") or {}
    h = m = l = 0
    for ds in (dq.get("datasets") or {}).values():
        s = ds.get("summary") or {}
        h += int(s.get("high_severity") or 0)
        m += int(s.get("medium_severity") or 0)
        l += int(s.get("low_severity") or 0)
    for ri in (dq.get("global_issues") or {}).get("relationship_row_issues") or []:
        sev = (ri.get("severity") or "medium").lower()
        if sev == "high":
            h += 1
        elif sev == "low":
            l += 1
        else:
            m += 1
    result["run_metadata"] = {
        "started_at": started_at_iso,
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "duration_seconds": round(time.perf_counter() - t0_perf, 2),
        "dq_issue_totals": {"high": h, "medium": m, "low": l},
        "sources_config": os.path.basename(sources_path) if sources_path else None,
    }
    try:
        from agent.transformation_suggester import suggest_transformations

        result["transformation_suggestions"] = suggest_transformations(result)
    except Exception as e:
        logger.warning("Report suggestions skipped: %s", e)
        result["transformation_suggestions"] = {
            "suggested_transformations": [],
            "summary": {
                "total_suggestions": 0,
                "by_action": {},
                "auto_fixable_count": 0,
                "manual_review_count": 0,
            },
            "_error": str(e),
        }


def _brief_issue_line(i: Dict[str, Any]) -> str:
    col = f" [{i['column']}]" if i.get("column") else ""
    cnt = f" x{i['count']}" if i.get("count") is not None else ""
    rows = i.get("row_indexes") or []
    row_part = f" | rows: {rows[:15]}{'…' if len(rows) > 15 else ''}" if rows else ""
    rec = i.get("recommendation") or ""
    rec_part = f" | → {rec[:200]}{'…' if len(rec) > 200 else ''}" if rec else ""
    return f"- ({i['severity']}) {i['type']}{col}{cnt}: {i['message']}{row_part}{rec_part}"


def _dtype_with_inference(cmeta: Dict[str, Any]) -> str:
    d = cmeta.get("dtype")
    inf = cmeta.get("dtype_inference")
    return f"{d} ({inf})" if d == "object" and inf else str(d)


def build_dq_scorecard(result: Dict[str, Any]) -> Dict[str, Any]:
    """
    Top-level readiness verdict and per-dataset score summary for banners
    (HTML + Markdown reports).
    """
    datasets = result.get("datasets", {}) or {}
    dq = result.get("data_quality_issues", {}) or {}
    dq_ds = dq.get("datasets", {}) or {}

    per_dataset: List[Dict[str, Any]] = []
    total_rows = 0
    total_high = total_medium = total_low = 0
    total_affected_by_high = 0

    for ds_name, ds_meta in datasets.items():
        row_count = int(ds_meta.get("row_count", 0) or 0)
        total_rows += row_count

        summ = (dq_ds.get(ds_name) or {}).get("summary") or {}
        raw_score = summ.get("dq_score_0_100")
        try:
            score = float(raw_score) if raw_score is not None else 0.0
        except Exception:
            score = 0.0

        issues = (dq_ds.get(ds_name) or {}).get("issues") or []
        if not isinstance(issues, list):
            issues = []
        high = sum(1 for i in issues if (i.get("severity") or "").lower() == "high")
        medium = sum(1 for i in issues if (i.get("severity") or "").lower() == "medium")
        low = sum(1 for i in issues if (i.get("severity") or "").lower() == "low")
        affected_high = 0
        for i in issues:
            if (i.get("severity") or "").lower() == "high":
                try:
                    affected_high += int(i.get("count") or 0)
                except Exception:
                    pass

        total_high += high
        total_medium += medium
        total_low += low
        total_affected_by_high += affected_high

        if score >= 70:
            readiness = "READY"
        elif score >= 35:
            readiness = "NEEDS_WORK"
        else:
            readiness = "BLOCKED"

        per_dataset.append(
            {
                "name": ds_name,
                "dq_score": round(score, 1),
                "readiness": readiness,
                "row_count": row_count,
                "high": high,
                "medium": medium,
                "low": low,
                "rows_affected_by_high": affected_high,
            }
        )

    order = {"BLOCKED": 0, "NEEDS_WORK": 1, "READY": 2}
    per_dataset.sort(key=lambda x: (order[x["readiness"]], x["dq_score"]))

    overall_score = (
        sum(d["dq_score"] for d in per_dataset) / len(per_dataset) if per_dataset else 0.0
    )

    if any(d["readiness"] == "BLOCKED" for d in per_dataset):
        verdict = "BLOCKED"
    elif any(d["readiness"] == "NEEDS_WORK" for d in per_dataset):
        verdict = "NEEDS_WORK"
    else:
        verdict = "READY"

    # Sum of HIGH `count` can exceed row count (multiple issues touch the same row). Clamp UI % to [0, 100].
    if total_rows > 0:
        raw_pct = ((total_rows - total_affected_by_high) / total_rows) * 100.0
        clean_rows_est = round(max(0.0, min(100.0, raw_pct)), 1)
    else:
        clean_rows_est = 100.0

    return {
        "verdict": verdict,
        "overall_dq_score": round(overall_score, 1),
        "total_issues": {"high": total_high, "medium": total_medium, "low": total_low},
        "total_rows": total_rows,
        "rows_affected_by_high": total_affected_by_high,
        "estimated_clean_rows_pct": clean_rows_est,
        "per_dataset": per_dataset,
        "datasets_blocked": [d["name"] for d in per_dataset if d["readiness"] == "BLOCKED"],
        "datasets_at_risk": [d["name"] for d in per_dataset if d["readiness"] == "NEEDS_WORK"],
        "datasets_clean": [d["name"] for d in per_dataset if d["readiness"] == "READY"],
    }


def build_cleaning_manifest(
    result: Dict[str, Any],
    suggestions: Dict[str, Any],
    scorecard: Dict[str, Any],
) -> Dict[str, Any]:
    """Machine-readable per-column issue reference for ETL development."""
    from datetime import datetime, timezone

    datasets_out: Dict[str, Any] = {}
    dq = result.get("data_quality_issues", {}) or {}
    datasets_meta = result.get("datasets", {}) or {}
    dq_ds = dq.get("datasets", {}) or {}

    sug_by_key: Dict[str, Dict[str, Any]] = {}
    for s in (suggestions or {}).get("suggested_transformations") or []:
        if not isinstance(s, dict):
            continue
        ds = s.get("dataset") or ""
        col = s.get("column")
        it = s.get("issue_type")
        sug_by_key[f"{ds}|{col}|{it}"] = s

    for ds_name, ds_meta in datasets_meta.items():
        issues_raw = (dq_ds.get(ds_name) or {}).get("issues", []) or []
        ds_score_rows = [d for d in scorecard["per_dataset"] if d["name"] == ds_name]
        readiness = ds_score_rows[0]["readiness"] if ds_score_rows else "UNKNOWN"
        dq_score = ds_score_rows[0]["dq_score"] if ds_score_rows else 0.0

        issues_out: List[Dict[str, Any]] = []
        for issue in issues_raw:
            if not isinstance(issue, dict):
                continue
            key = f"{ds_name}|{issue.get('column')}|{issue.get('type')}"
            sug = sug_by_key.get(key, {})
            manual_g = issue.get("manual_guidance") or sug.get("manual_guidance") or ""
            issues_out.append(
                {
                    "column": issue.get("column"),
                    "issue_type": issue.get("type"),
                    "severity": issue.get("severity"),
                    "rows_affected": issue.get("count"),
                    "row_indexes": (issue.get("row_indexes") or [])[:100],
                    "sample_bad_values": [str(v)[:80] for v in (issue.get("sample_values") or [])[:10]],
                    "message": issue.get("message"),
                    "recommended_action": issue.get("recommended_action")
                    or sug.get("suggested_action")
                    or "review_manually",
                    "auto_fixable": bool(sug.get("auto_fixable"))
                    if sug
                    else bool(issue.get("auto_fixable", False)),
                    "manual_guidance": manual_g,
                }
            )

        severity_order = {"high": 0, "medium": 1, "low": 2}
        issues_out.sort(key=lambda x: severity_order.get((x["severity"] or "low").lower(), 3))

        datasets_out[ds_name] = {
            "source_file": ds_name,
            "row_count": ds_meta.get("row_count", 0),
            "column_count": ds_meta.get("column_count", 0),
            "dq_score": dq_score,
            "readiness": readiness,
            "total_issues": len(issues_out),
            "issues_by_severity": {
                "high": sum(1 for i in issues_out if (i["severity"] or "").lower() == "high"),
                "medium": sum(1 for i in issues_out if (i["severity"] or "").lower() == "medium"),
                "low": sum(1 for i in issues_out if (i["severity"] or "").lower() == "low"),
            },
            "issues": issues_out,
        }

    global_issues = dq.get("global_issues", {}) or {}
    global_out: List[Dict[str, Any]] = []

    for orphan in global_issues.get("orphan_foreign_keys", []) or []:
        if not isinstance(orphan, dict):
            continue
        global_out.append(
            {
                "type": "orphan_foreign_key",
                "from": orphan.get("from"),
                "to": orphan.get("to"),
                "orphan_count": orphan.get("orphan_count"),
                "severity": "high",
                "message": f"Orphan FKs: {orphan.get('from')} → {orphan.get('to')}",
                "recommended_action": "validate_referential_integrity_or_stage",
            }
        )

    for inc in global_issues.get("cross_dataset_inconsistencies", []) or []:
        if not isinstance(inc, dict):
            continue
        global_out.append(
            {
                "type": "cross_dataset_inconsistency",
                "dataset": inc.get("dataset"),
                "column": inc.get("column"),
                "datasets": inc.get("datasets"),
                "severity": "medium",
                "message": inc.get("message", ""),
                "recommended_action": "review_manually",
            }
        )

    return {
        "manifest_version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "verdict": scorecard["verdict"],
        "overall_dq_score": scorecard["overall_dq_score"],
        "total_datasets": len(datasets_out),
        "summary": scorecard["total_issues"],
        "datasets": datasets_out,
        "global_issues": global_out,
    }


def build_markdown_report(result: Dict[str, Any]) -> str:
    """Build Markdown report from assessment result."""
    md: List[str] = []
    md.append("**Intelligent Data Assessment Report**\n")

    sc = build_dq_scorecard(result)
    v = sc["verdict"]
    v_icon = "🔴" if v == "BLOCKED" else ("⚠️" if v == "NEEDS_WORK" else "✅")
    v_label = v.replace("_", " ")
    ti = sc["total_issues"]
    md.append(f"## {v_icon} Data Quality Verdict: {v_label}")
    md.append("")
    md.append("| Metric | Value |")
    md.append("|--------|-------|")
    md.append(f"| Overall DQ Score | {sc['overall_dq_score']} / 100 |")
    md.append(f"| High severity issues | {ti.get('high', 0)} |")
    md.append(f"| Rows affected by HIGH issues | {sc['rows_affected_by_high']} |")
    md.append(
        f"| Approx. unaffected row share (HIGH; counts may overlap) | {sc['estimated_clean_rows_pct']}% |"
    )
    md.append("")
    md.append("| Dataset | DQ Score | Readiness |")
    md.append("|---------|----------|-----------|")
    for d in sc["per_dataset"]:
        r = d["readiness"]
        ri = "🔴 BLOCKED" if r == "BLOCKED" else ("⚠️ NEEDS WORK" if r == "NEEDS_WORK" else "✅ READY")
        md.append(f"| `{d['name']}` | {d['dq_score']} | {ri} |")
    md.append("")

    datasets = result.get("datasets", {})
    rels = result.get("relationships", [])
    dq = result.get("data_quality_issues", {})
    dq_ds = dq.get("datasets", {})
    dq_global = dq.get("global_issues", {})
    exec_items = result.get("executive_summary_items") or []

    md.append("**Overview**")
    md.append(f"- Total datasets: {len(datasets)}")
    total_rows = sum(d.get("row_count", 0) for d in datasets.values())
    total_cols = sum(d.get("column_count", 0) for d in datasets.values())
    total_bytes = sum(d.get("data_volume_bytes", 0) for d in datasets.values())
    md.append(f"- Total rows (approx.): {total_rows}")
    md.append(f"- Total columns (sum): {total_cols}")
    md.append(f"- Total memory (bytes): {total_bytes}\n")

    if exec_items:
        md.append("**Executive summary (prioritized)**")
        for it in exec_items[:10]:
            if not isinstance(it, dict):
                continue
            md.append(
                f"- ({it.get('severity')}) **{it.get('title')}** — "
                f"datasets={it.get('datasets_affected')}, rows≈{it.get('estimated_rows_affected')}. "
                f"→ {str(it.get('recommendation') or '')[:220]}"
            )
        md.append("")

    try:
        from agent.report_governance_sections import render_governance_markdown

        _gm = render_governance_markdown(result)
        if _gm.strip():
            md.append(_gm)
    except Exception:
        pass

    rm = result.get("run_metadata") or {}
    if rm:
        md.append("**Run metadata**")
        md.append(f"- Assessment duration: **{rm.get('duration_seconds')}s**")
        dqt = rm.get("dq_issue_totals") or {}
        md.append(
            f"- DQ issues (rollup): high={dqt.get('high', 0)}, medium={dqt.get('medium', 0)}, low={dqt.get('low', 0)}"
        )
        if rm.get("sources_config"):
            md.append(f"- Config: `{rm['sources_config']}`")
        md.append("")

    ts = result.get("transformation_suggestions") or {}
    sug = ts.get("suggested_transformations") or []
    if sug and not ts.get("_error"):
        md.append("**Suggested fixes (rule-based)**")
        md.append(
            f"*{ts.get('summary', {}).get('total_suggestions', len(sug))} suggestions based on current DQ signals.*"
        )
        _rank = {"high": 0, "medium": 1, "low": 2}
        for s in sorted(sug, key=lambda x: (_rank.get((x.get("severity") or "low").lower(), 3), str(x.get("dataset"))))[
            :20
        ]:
            ds = s.get("dataset") or "—"
            col = s.get("column") or "—"
            md.append(
                f"- **{s.get('suggested_action', '?')}** · `{ds}` · `{col}` ({s.get('severity')}) — {str(s.get('message', ''))[:120]}"
            )
        md.append("")

    llm = result.get("llm_insights") or {}
    if llm.get("success") and llm.get("parsed"):
        p = llm["parsed"]
        md.append("**AI-assisted insights** *(verify against detailed tables; model may err)*\n")
        md.append(p.get("executive_summary") or "")
        md.append("")
        md.append("*Top risks:*")
        for r in (p.get("top_risks") or [])[:5]:
            if isinstance(r, dict):
                md.append(f"- **{r.get('title', '')}** — {r.get('detail', '')}")
        md.append("")
        md.append("*Recommended next steps:*")
        for s in (p.get("recommended_next_steps") or [])[:7]:
            if s:
                md.append(f"- {s}")
        if p.get("data_lineage_comment"):
            md.append("")
            md.append(f"*Relationships note:* {p['data_lineage_comment']}")
        md.append("")
    elif llm.get("error") and "llm_insights" in result:
        md.append(f"**AI insights:** (not generated — {llm.get('error')})\n")

    md.append("**Datasets**")
    for name, meta in datasets.items():
        md.append(f"- **{name}**")
        md.append(f"  - rows: {meta.get('row_count')}, cols: {meta.get('column_count')}, bytes: {meta.get('data_volume_bytes')}")
        dq_block = (dq_ds.get(name) or {})
        summ = (dq_block.get("summary") or {})
        if summ:
            if summ.get("dq_score_0_100") is not None:
                md.append(f"  - dq_score: **{round(float(summ.get('dq_score_0_100')), 1)} / 100**")
            if summ.get("estimated_clean_rows_after_high") is not None:
                md.append(f"  - est_clean_rows_after_high: **{summ.get('estimated_clean_rows_after_high')}**")
            if summ.get("estimated_clean_rows_after_high_and_medium") is not None:
                md.append(f"  - est_clean_rows_after_high+medium: **{summ.get('estimated_clean_rows_after_high_and_medium')}**")
        cols = meta.get("columns", {})
        if cols:
            md.append("  - columns:")
            for idx, (col, cmeta) in enumerate(cols.items()):
                if idx >= 12:
                    md.append(f"    - ... (+{len(cols)-12} more columns)")
                    break
                md.append(
                    f"    - **{col}**: dtype={_dtype_with_inference(cmeta)}, "
                    f"null%={_fmt_pct(cmeta.get('null_percentage'))}, "
                    f"unique={cmeta.get('unique_count')}, type={cmeta.get('semantic_type')}, candidate_pk={cmeta.get('candidate_primary_key')}"
                )
        md.append("")

    md.append("**Relationships (cardinality on shared keys)**")
    if rels:
        for rel in rels:
            card = rel.get("cardinality") or "?"
            md.append(
                f"- **{rel['from']}** ↔ **{rel['to']}**  |  overlap: {rel.get('overlap_count')}  |  "
                f"**{card}** (max/keys: A={rel.get('max_rows_per_key_a')}, B={rel.get('max_rows_per_key_b')})"
            )
            if rel.get("summary"):
                md.append(f"  - {rel['summary']}")
    else:
        md.append("- (none found)")
    md.append("")

    md.append("**Cross-table row issues (orphan keys)**")
    rri = dq_global.get("relationship_row_issues") or []
    if rri:
        for x in rri[:30]:
            rows = x.get("row_indexes") or []
            md.append(
                f"- **{x.get('dataset')}**.{x.get('column')} → missing in **{x.get('related_dataset')}.{x.get('related_column')}** "
                f"— {x.get('count')} rows; e.g. row indexes {rows[:12]}{'…' if len(rows) > 12 else ''}"
            )
            md.append(f"  - {x.get('message', '')}")
            if x.get("recommendation"):
                md.append(f"  - *Recommendation:* {x['recommendation']}")
    else:
        md.append("- (none)")
    md.append("")

    md.append("**Relationship warnings (M:N / model)**")
    rw = dq_global.get("relationship_warnings") or []
    if rw:
        for w in rw[:20]:
            md.append(f"- ({w.get('severity')}) {w.get('message')}")
            if w.get("recommendation"):
                md.append(f"  - *Recommendation:* {w['recommendation']}")
    else:
        md.append("- (none)")
    md.append("")

    md.append("**Data Quality Issues**")
    for ds_name, dq_block in dq_ds.items():
        md.append(f"- **{ds_name}**")
        issues = dq_block.get("issues", [])
        if not issues:
            md.append("  - (no issues)")
        else:
            for i in issues[:25]:
                fx = i.get("fixability") or ""
                fx_part = f" [{fx}]" if fx else ""
                md.append("  " + _brief_issue_line({**i, "type": f"{i.get('type')}{fx_part}"}))
            if len(issues) > 25:
                md.append(f"  - ... (+{len(issues)-25} more)")
        md.append("")

    md.append("- **Global Issues (value-level orphans)**")
    orphans = dq_global.get("orphan_foreign_keys", [])
    if orphans:
        for o in orphans[:20]:
            md.append(f"  - Orphan values: {o['from']} → {o['to']} (count: {o['orphan_count']})")
            if o.get("recommendation"):
                md.append(f"    → {o['recommendation'][:180]}")
    else:
        md.append("  - (none)")
    xds = dq_global.get("cross_dataset_inconsistencies", [])
    if xds:
        for x in xds[:20]:
            md.append(f"  - {x['dataset']}.{x['column']}: {x['message']}")
            if x.get("recommendation"):
                md.append(f"    → {x['recommendation'][:160]}")
    else:
        md.append("  - Cross-dataset inconsistencies: (none)")

    xcons = dq_global.get("cross_dataset_consistency", [])
    if xcons:
        md.append("  - Cross-dataset consistency insights:")
        for x in xcons[:20]:
            md.append(f"    - ({x.get('severity')}) {x.get('type')}: {x.get('message')}")
            if x.get("recommendation"):
                md.append(f"      → {str(x.get('recommendation'))[:180]}")
    md.append("")
    return "\n".join(md)


# ========================= HTML Report =========================

def build_html_report(result: Dict[str, Any]) -> str:
    """Build HTML assessment report (Theme 2 executive UI)."""
    from agent.report_html_themes import get_report_html_css
    from datetime import datetime
    from collections import defaultdict

    # Ensure dq_recommendations is populated in result
    if isinstance(result, dict) and "dq_recommendations" not in result:
        try:
            from agent.dq_recommendations_agent import DQRecommendationsAgent, dq_recommendations_to_dict
            agent = DQRecommendationsAgent()
            merged_dq = result.get("data_quality_issues") or {}
            rec, _ = agent.recommend(merged_dq=merged_dq)
            result["dq_recommendations"] = dq_recommendations_to_dict(rec)
        except Exception:
            pass

    datasets = result.get("datasets", {})
    rels = result.get("relationships", [])
    dq = result.get("data_quality_issues", {})
    dq_ds = dq.get("datasets", {})
    dq_global = dq.get("global_issues", {})
    exec_items = result.get("executive_summary_items") or []
    scorecard = build_dq_scorecard(result)
    total_rows = sum(d.get("row_count", 0) for d in datasets.values())
    total_cols = sum(d.get("column_count", 0) for d in datasets.values())
    total_bytes = sum(d.get("data_volume_bytes", 0) for d in datasets.values())

    llm = result.get("llm_insights") or {}
    nav_llm_link = ""
    llm_section_html = ""
    if llm.get("success") and llm.get("parsed"):
        nav_llm_link = '\n  <a href="#llm-insights" class="nav-jump">AI insights</a>'
        _p = llm["parsed"]
        _risks = []
        for _r in (_p.get("top_risks") or [])[:5]:
            if isinstance(_r, dict):
                _risks.append(
                    "<li><strong>"
                    + html_module.escape(str(_r.get("title") or ""))
                    + "</strong> — "
                    + html_module.escape(str(_r.get("detail") or ""))
                    + "</li>"
                )
        _steps = [
            "<li>" + html_module.escape(str(_s)) + "</li>"
            for _s in (_p.get("recommended_next_steps") or [])[:7]
            if _s
        ]
        _lin = _p.get("data_lineage_comment")
        _lin_html = (
            "<p class=\"llm-lineage\"><strong>Relationships note:</strong> "
            + html_module.escape(str(_lin))
            + "</p>"
            if _lin
            else ""
        )
        llm_section_html = (
            '<section id="llm-insights" class="llm-insights-section">'
            '<div class="llm-panel">'
            '<div class="llm-banner">AI-assisted narrative — confirm against detailed DQ tables below</div>'
            "<h2>AI insights</h2>"
            '<p class="llm-exec">'
            + html_module.escape(str(_p.get("executive_summary") or ""))
            + "</p>"
            '<h3 class="llm-subh">Top risks</h3><ul class="llm-ul">'
            + ("".join(_risks) if _risks else '<li class="muted">(none listed)</li>')
            + "</ul>"
            '<h3 class="llm-subh">Recommended next steps</h3><ol class="llm-ol">'
            + ("".join(_steps) if _steps else '<li class="muted">(none listed)</li>')
            + "</ol>"
            + _lin_html
            + "</div></section>"
        )
    elif llm.get("error") is not None and "llm_insights" in result:
        nav_llm_link = '\n  <a href="#llm-insights" class="nav-jump">AI insights</a>'
        llm_section_html = (
            '<section id="llm-insights" class="llm-insights-section"><div class="llm-panel llm-panel-err">'
            "<h2>AI insights</h2>"
            "<p>Could not generate insights: <code>"
            + html_module.escape(str(llm.get("error") or ""))
            + "</code></p><p class=\"muted\">Check Azure OpenAI env vars and deployment.</p></div></section>"
        )

    exec_summary_html = ""
    if exec_items:
        _lis = []
        for it in exec_items[:10]:
            if not isinstance(it, dict):
                continue
            _lis.append(
                "<li><span class=\"pill sev-"
                + html_module.escape(str(it.get("severity") or "low"))
                + "\">"
                + html_module.escape(str(it.get("severity") or "low").upper())
                + "</span> <strong>"
                + html_module.escape(str(it.get("title") or ""))
                + "</strong> <span class=\"muted\">(datasets="
                + html_module.escape(str(it.get("datasets_affected") or "—"))
                + ", rows≈"
                + html_module.escape(str(it.get("estimated_rows_affected") or "—"))
                + ")</span><br/><span class=\"muted\">"
                + html_module.escape(str(it.get("recommendation") or ""))
                + "</span></li>"
            )
        exec_summary_html = (
            "<div class=\"exec-summary\"><h3>Executive summary (prioritized)</h3>"
            "<ul class=\"exec-ul\">" + ("".join(_lis) if _lis else "<li class=\"muted\">(none)</li>") + "</ul></div>"
        )

    def esc(x: Any) -> str:
        return html_module.escape(str(x) if x is not None else "")

    def esc_attr(x: Any) -> str:
        return html_module.escape(str(x) if x is not None else "", quote=True)

    def path_label(sr: str) -> str:
        if sr == "__database__":
            return "SQL database"
        if sr.startswith("azure_blob:"):
            sub = sr.split(":", 1)[1] or "/"
            return f"Azure Blob — {sub}"
        if sr:
            return sr
        return "Unknown source"

    def path_raw_for_copy(sr: str) -> str:
        if sr == "__database__":
            return "SQL database (tables)"
        if sr.startswith("azure_blob:"):
            return sr
        return sr or ""

    def is_filesystem_source(sr: str) -> bool:
        if not sr or sr == "__database__":
            return False
        if sr.startswith("azure_blob:"):
            return False
        return True

    def pct(x):
        try:
            return f"{round(float(x)*100, 2)}%"
        except Exception:
            return esc(x)

    def dtype_with_inference(cmeta: Dict[str, Any]) -> str:
        d = cmeta.get("dtype")
        inf = cmeta.get("dtype_inference")
        s = f"{d} ({inf})" if d == "object" and inf else str(d)
        return esc(s)

    def render_profile_table(cols_meta: Dict[str, Any]) -> str:
        rows_html = []
        for col, cmeta in cols_meta.items():
            rows_html.append(
                "<tr>"
                f"<td><strong>{esc(col)}</strong></td>"
                f"<td>{dtype_with_inference(cmeta)}</td>"
                f"<td>{pct(cmeta.get('null_percentage'))}</td>"
                f"<td>{esc(cmeta.get('unique_count'))}</td>"
                f"<td>{esc(cmeta.get('semantic_type'))}</td>"
                f"<td>{esc(str(cmeta.get('candidate_primary_key')).lower())}</td>"
                "</tr>"
            )
        if not rows_html:
            rows_html.append("<tr><td colspan='6' class='muted'>(no columns)</td></tr>")
        return (
            "<div class='table-wrap'><table class='data-table'><thead><tr>"
            "<th>Column</th><th>Type</th><th>Null %</th><th>Unique</th><th>Semantic</th><th>PK candidate</th>"
            "</tr></thead><tbody>" + "".join(rows_html) + "</tbody></table></div>"
        )

    def split_by_sev(issues: List[Dict]) -> Dict[str, List]:
        buckets = {"high": [], "medium": [], "low": []}
        for i in issues or []:
            sev = (i.get("severity") or "low").lower()
            if sev not in buckets:
                sev = "low"
            buckets[sev].append(i)
        return buckets

    def fmt_rows(indexes: List[int]) -> str:
        if not indexes:
            return "<span class='muted'>(none)</span>"
        if len(indexes) <= 40:
            return esc(", ".join(str(x) for x in indexes))
        return f"<div class='scrollcell'>{esc(', '.join(str(x) for x in indexes))}</div>"

    def fmt_samples(samples: List[Any]) -> str:
        if not samples:
            return "<span class='muted'>(none)</span>"
        return ", ".join(f"<code>{esc(x)}</code>" for x in samples)

    def render_dq_table(title: str, rows: List[Dict]) -> str:
        body = []
        if not rows:
            body.append("<tr><td colspan='9' class='muted'>(no issues)</td></tr>")
        else:
            for i in rows:
                sev = (i.get("severity") or "low").lower()
                msg = (i.get("message") or "").strip()
                rec = (i.get("recommendation") or "").strip()
                fx = (i.get("fixability") or "").strip()
                msg_td = f"<td class='msg-cell'>{esc(msg)}</td>" if msg else "<td class='msg-cell'><span class='muted'>—</span></td>"
                rec_td = f"<td class='rec-cell'>{esc(rec)}</td>" if rec else "<td class='rec-cell'><span class='muted'>—</span></td>"
                body.append(
                    "<tr>"
                    f"<td>{esc(i.get('column') or '-')}</td>"
                    f"<td><code>{esc(i.get('type'))}</code></td>"
                    f"<td><span class='badge sev-{esc(sev)}'>{esc(sev.upper())}</span></td>"
                    f"<td><span class='badge fx-{esc(fx.lower() or 'complex')}'>{esc(fx or '—')}</span></td>"
                    f"<td>{esc(i.get('count')) if i.get('count') is not None else '-'}</td>"
                    f"<td>{fmt_rows(i.get('row_indexes') or [])}</td>"
                    f"<td>{fmt_samples(i.get('sample_values') or [])}</td>"
                    f"{msg_td}{rec_td}</tr>"
                )
        return (
            f"<h4 class='block-title'>{esc(title)}</h4>"
            "<div class='table-wrap'><table class='data-table'><thead><tr>"
            "<th>Column</th><th>Issue</th><th>Sev</th><th>Fixability</th><th>Count</th><th>Rows</th><th>Samples</th>"
            "<th>Problem</th><th>Recommendation</th>"
            "</tr></thead><tbody>" + "".join(body) + "</tbody></table></div>"
        )

    path_groups: Dict[str, List[str]] = defaultdict(list)
    for name, meta in datasets.items():
        path_groups[meta.get("source_root") or ""].append(name)
    ordered_paths = sorted(path_groups.keys(), key=lambda x: (x == "", str(x).lower()))

    ds_idx = [0]

    def _fmt_id(s: str) -> str:
        return re.sub(r"[^a-zA-Z0-9_-]", "_", str(s))[:44] or "fmt"

    def render_dataset_block(name: str, meta: Dict[str, Any], pi: int) -> str:
        rows, cols, bytes_ = meta.get("row_count", 0), meta.get("column_count", 0), meta.get("data_volume_bytes", 0)
        profile_tbl = render_profile_table(meta.get("columns", {}) or {})
        ds_issues = dq_ds.get(name, {}).get("issues", []) or []
        buckets = split_by_sev(ds_issues)
        ds_summary = (dq_ds.get(name, {}).get("summary") or {}) if isinstance(dq_ds.get(name, {}), dict) else {}
        src = meta.get("source_root") or ""
        raw = path_raw_for_copy(src)
        if src == "__database__":
            path_html = "<div class='path-inset'><span class='path-inset-label'>Loaded from</span><span class='path-inset-value'>SQL database tables</span></div>"
        elif src.startswith("azure_blob:"):
            path_html = f"<div class='path-inset azure'><span class='path-inset-label'>Azure Blob prefix</span><span class='path-inset-value'>{esc(raw)}</span><button type='button' class='btn-mini btn-copy-path' data-path=\"{esc_attr(raw)}\">Copy</button></div>"
        elif src:
            path_html = f"<div class='path-inset disk'><span class='path-inset-label'>Filesystem path</span><span class='path-inset-value'>{esc(raw)}</span><button type='button' class='btn-mini btn-copy-path' data-path=\"{esc_attr(raw)}\">Copy</button></div>"
        else:
            path_html = "<div class='path-inset'><span class='path-inset-label'>Source</span><span class='path-inset-value muted'>Not specified</span></div>"
        i = ds_idx[0]
        ds_idx[0] += 1
        score = ds_summary.get("dq_score_0_100")
        clean_h = ds_summary.get("estimated_clean_rows_after_high")
        clean_hm = ds_summary.get("estimated_clean_rows_after_high_and_medium")
        score_html = ""
        if score is not None:
            try:
                sv = float(score)
                sev_class = "sev-high" if sv < 35 else ("sev-medium" if sv < 70 else "sev-low")
                score_html = f"<span class='badge {sev_class}'>DQ {round(sv,1)}/100</span>"
            except Exception:
                score_html = f"<span class='badge sev-low'>DQ {esc(str(score))}/100</span>"
        clean_html = ""
        try:
            tr_i = int(rows) if rows is not None else 0
        except Exception:
            tr_i = 0
        if clean_h is not None or clean_hm is not None:
            rows_bits: List[str] = []
            tail = ""
            if tr_i > 0:
                tail = f" <span class=\"muted\">(of {rows:,} sampled rows)</span>"
            if clean_h is not None:
                pct_h = None
                if tr_i > 0:
                    try:
                        pct_h = round(100.0 * float(clean_h) / float(tr_i), 1)
                    except Exception:
                        pct_h = None
                pct_part = (
                    f" <span class=\"muted\">≈ {esc(pct_h)}% unaffected by HIGH severity</span>"
                    if pct_h is not None
                    else ""
                )
                rows_bits.append(
                    "<div class=\"clean-est-row\">"
                    "<span class=\"clean-est-label\">Rows with <strong>no HIGH</strong>-severity finding</span>"
                    f"<span class=\"clean-est-value\">{esc(str(clean_h))}</span>"
                    f"<span class=\"clean-est-tail\">{tail}{pct_part}</span>"
                    "</div>"
                )
            if clean_hm is not None:
                pct_hm = None
                if tr_i > 0:
                    try:
                        pct_hm = round(100.0 * float(clean_hm) / float(tr_i), 1)
                    except Exception:
                        pct_hm = None
                pct_part = (
                    f" <span class=\"muted\">≈ {esc(pct_hm)}% unaffected after HIGH+MEDIUM remediation</span>"
                    if pct_hm is not None
                    else ""
                )
                rows_bits.append(
                    "<div class=\"clean-est-row\">"
                    "<span class=\"clean-est-label\">Rows with <strong>no HIGH nor MEDIUM</strong> finding</span>"
                    f"<span class=\"clean-est-value\">{esc(str(clean_hm))}</span>"
                    f"<span class=\"clean-est-tail\">{tail}{pct_part}</span>"
                    "</div>"
                )
            clean_html = (
                '<aside class="dataset-clean-summary" aria-label="Remediation row estimates">'
                "<p class=\"clean-summary-intro\">These counts are computed from overlapping HIGH/MEDIUM rows in this scan "
                '(see <a href="#dq-scorecard">DQ verdict</a> for context).</p>'
                + "".join(rows_bits)
                + "</aside>"
            )
        n_high = len(buckets["high"])
        n_med = len(buckets["medium"])
        n_low = len(buckets["low"])
        dq_details_open_attr = " open" if n_high > 0 else ""
        return f"""
        <div class="nest-file-card dataset-card depth-card" id="ds-{i}" data-path-group="{pi}">
          <button type="button" class="nest-toggle nest-level-3" aria-expanded="true" aria-controls="dbc-{i}">
            <span class="chevron" aria-hidden="true"></span>
            <div class="toggle-main">
              <h3>{esc(name)}</h3>
              <div class="toggle-sub">Profile &amp; data quality</div>
            </div>
            <div class="dataset-stats-inline"><span>{rows:,} rows</span><span>{cols} cols</span>{score_html}</div>
          </button>
          <div class="dataset-body" id="dbc-{i}">
            {path_html}
            {clean_html}
            <h4 class="block-title">Profile</h4>
            {profile_tbl}
            <h4 class="block-title">Data quality</h4>
            <details class="dq-issue-details"{dq_details_open_attr}>
              <summary class="dq-issue-summary">{esc(name)} — {n_high + n_med + n_low} issues ({n_high} HIGH · {n_med} MEDIUM · {n_low} LOW)</summary>
              <div class="dq-issue-body">
            {render_dq_table('High severity', buckets['high'])}
            {render_dq_table('Medium severity', buckets['medium'])}
            {render_dq_table('Low severity', buckets['low'])}
              </div>
            </details>
          </div>
        </div>"""

    n_files = sum(len(path_groups[p]) for p in ordered_paths)
    nest_chunks: List[str] = [
        f"""<div class="datasets-nest-root">
<button type="button" class="nest-toggle nest-level-0" aria-expanded="true" aria-controls="nest-root-body" id="nest-root-toggle">
  <span class="chevron" aria-hidden="true"></span>
  <span class="nest-toggle-main"><strong>All locations</strong>
  <span class="nest-meta-inline">{len(ordered_paths)} location(s) · {n_files} file(s)</span></span>
</button>
<div class="nest-body" id="nest-root-body">"""
    ]
    for pi, sr in enumerate(ordered_paths):
        names = sorted(path_groups[sr])
        lbl = path_label(sr)
        raw = path_raw_for_copy(sr)
        loc_body_id = f"nest-loc-body-{pi}"
        if is_filesystem_source(sr):
            loc_title = (
                '<span class="nest-loc-heading-row"><strong>File system</strong>'
                '<span class="btn-mini btn-copy-path nest-loc-copy-path" role="button" tabindex="0" '
                f'data-path="{esc_attr(raw)}">Copy path</span></span>'
            )
            loc_meta = esc(raw if len(raw) < 120 else raw[:117] + "…")
            loc_toolbar = ""
        else:
            loc_title = f"<strong>{esc(lbl)}</strong>"
            loc_meta = esc(raw if len(raw) < 80 else raw[:77] + "…")
            loc_toolbar = (
                f'<div class="nest-loc-toolbar">'
                f'<button type="button" class="btn-mini btn-copy-path" data-path="{esc_attr(raw)}">'
                f"Copy full path</button></div>"
            )
        nest_chunks.append(
            f"""<div class="nest-loc-wrap" id="src-{pi}" data-path-filter="{pi}">
<button type="button" class="nest-toggle nest-level-1" aria-expanded="true" aria-controls="{loc_body_id}">
  <span class="chevron" aria-hidden="true"></span>
  <span class="nest-toggle-main">{loc_title}
  <span class="nest-meta-inline">{loc_meta}</span></span>
</button>
<div class="nest-body nest-loc-inner" id="{loc_body_id}">
{loc_toolbar}"""
        )
        by_ext: Dict[str, List[str]] = defaultdict(list)
        for n in names:
            if "." in n:
                ext = n.rsplit(".", 1)[-1].lower()
            else:
                ext = "no-extension"
            by_ext[ext].append(n)
        for ext_key in sorted(by_ext.keys(), key=lambda x: (x == "no-extension", x)):
            files = sorted(by_ext[ext_key])
            fmt_body_id = f"nest-fmt-{pi}-{_fmt_id(ext_key)}"
            ext_label = f".{ext_key}" if ext_key != "no-extension" else "(no extension)"
            nest_chunks.append(
                f"""<button type="button" class="nest-toggle nest-level-2" aria-expanded="true" aria-controls="{fmt_body_id}">
  <span class="chevron" aria-hidden="true"></span>
  <span class="nest-toggle-main"><strong>{esc(ext_label)}</strong>
  <span class="nest-meta-inline">{len(files)} file(s)</span></span>
</button>
<div class="nest-body nest-fmt-inner" id="{fmt_body_id}">"""
            )
            for n in files:
                nest_chunks.append(render_dataset_block(n, datasets[n], pi))
            nest_chunks.append("</div>")
        nest_chunks.append("</div></div>")
    nest_chunks.append("</div></div>")
    datasets_html = "".join(nest_chunks) if ordered_paths else "<p class='muted'>(no datasets)</p>"

    def render_rels() -> str:
        if not rels:
            return "<p class='muted'>No cross-dataset column overlaps detected (same column name, case-insensitive).</p>"
        card_labels = {
            "one_to_one": "1:1",
            "one_to_many": "1:N (A→B)",
            "many_to_one": "N:1 (A→B)",
            "many_to_many": "M:N",
        }
        rows = []
        for r in rels:
            card = r.get("cardinality") or "?"
            cl = card_labels.get(card, esc(card))
            rows.append(
                "<tr>"
                f"<td><code>{esc(r.get('dataset_a'))}</code></td>"
                f"<td><code>{esc(r.get('column_a'))}</code></td>"
                f"<td><code>{esc(r.get('dataset_b'))}</code></td>"
                f"<td><code>{esc(r.get('column_b'))}</code></td>"
                f"<td><strong>{cl}</strong><br/><span class='muted tiny'>{esc(r.get('from_a_to_b', ''))}</span></td>"
                f"<td>{esc(r.get('overlap_count'))}</td>"
                f"<td>{esc(r.get('max_rows_per_key_a'))} / {esc(r.get('max_rows_per_key_b'))}</td>"
                f"<td class='msg-cell'>{esc(r.get('summary') or '')}</td>"
                "</tr>"
            )
        return (
            "<p class='section-lead'>Cardinality is inferred from how often each <em>shared key value</em> appears "
            "in each table (max rows per key on overlap). 1:N means the A-side key is unique per row at most; "
            "B-side can repeat.</p>"
            "<div class='table-wrap'><table class='data-table'><thead><tr>"
            "<th>Table A</th><th>Col A</th><th>Table B</th><th>Col B</th>"
            "<th>Cardinality</th><th>Shared keys</th><th>Max rows/key (A|B)</th><th>Interpretation</th>"
            "</tr></thead><tbody>" + "".join(rows) + "</tbody></table></div>"
        )

    def render_global() -> str:
        orphans = dq_global.get("orphan_foreign_keys", []) or []
        xds = dq_global.get("cross_dataset_inconsistencies", []) or []
        rri = dq_global.get("relationship_row_issues", []) or []
        rw = dq_global.get("relationship_warnings", []) or []

        def tbl(rows, headers, row_fn):
            if not rows:
                return "<p class='muted'>(none)</p>"
            head = "".join(f"<th>{esc(h)}</th>" for h in headers)
            return (
                "<div class='table-wrap'><table class='data-table'><thead><tr>"
                + head + "</tr></thead><tbody>" + "".join(row_fn(r) for r in rows) + "</tbody></table></div>"
            )

        o_tbl = tbl(
            orphans,
            ["From", "To", "Orphan values", "Samples", "Recommendation"],
            lambda o: f"<tr><td><code>{esc(o.get('from'))}</code></td><td><code>{esc(o.get('to'))}</code></td>"
            f"<td>{esc(o.get('orphan_count'))}</td><td>{fmt_samples(o.get('sample_values') or [])}</td>"
            f"<td class='rec-cell'>{esc(o.get('recommendation') or '')}</td></tr>",
        )
        x_tbl = tbl(
            xds,
            ["Dataset", "Column", "Problem", "Recommendation"],
            lambda x: f"<tr><td>{esc(x.get('dataset'))}</td><td>{esc(x.get('column'))}</td>"
            f"<td class='msg-cell'>{esc(x.get('message'))}</td>"
            f"<td class='rec-cell'>{esc(x.get('recommendation') or '')}</td></tr>",
        )
        rri_tbl = tbl(
            rri,
            ["Child dataset", "FK column", "Parent table.col", "Rows affected", "Row indexes (sample)", "Bad values", "Recommendation"],
            lambda z: f"<tr><td><code>{esc(z.get('dataset'))}</code></td><td><code>{esc(z.get('column'))}</code></td>"
            f"<td><code>{esc(z.get('related_dataset'))}.{esc(z.get('related_column'))}</code></td>"
            f"<td>{esc(z.get('count'))}</td><td>{fmt_rows(z.get('row_indexes') or [])}</td>"
            f"<td>{fmt_samples(z.get('sample_values') or [])}</td>"
            f"<td class='rec-cell'>{esc(z.get('recommendation') or '')}</td></tr>",
        )
        rw_html = ""
        if rw:
            rw_html = "<h4 class='block-title'>Relationship model warnings (M:N)</h4><ul class='rel-list'>"
            for w in rw:
                rw_html += (
                    f"<li><span class='badge sev-{esc((w.get('severity') or 'low').lower())}'>{esc(w.get('severity'))}</span> "
                    f"{esc(w.get('message'))}<br/><em>Recommendation:</em> {esc(w.get('recommendation') or '')}</li>"
                )
            rw_html += "</ul>"
        else:
            rw_html = "<h4 class='block-title'>Relationship model warnings</h4><p class='muted'>(none)</p>"

        return f"""<h4 class="block-title">Orphan key rows (which dataset / column / rows)</h4>{rri_tbl}
            {rw_html}
            <h4 class="block-title">Orphan values (set difference, no row index)</h4>{o_tbl}
            <h4 class="block-title">Cross-dataset inconsistencies</h4>{x_tbl}"""

    dt = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rel_html = render_rels()
    glob_html = render_global()

    ts_block = result.get("transformation_suggestions") or {}
    raw_sug = list(ts_block.get("suggested_transformations") or [])
    _sev_rank = {"high": 0, "medium": 1, "low": 2}
    auto_sug = [s for s in raw_sug if s.get("suggested_action") != "review_manually"]
    man_sug = [s for s in raw_sug if s.get("suggested_action") == "review_manually"]
    auto_sug.sort(
        key=lambda x: (
            _sev_rank.get((x.get("severity") or "low").lower(), 3),
            str(x.get("dataset") or ""),
        )
    )
    man_sug.sort(
        key=lambda x: (
            _sev_rank.get((x.get("severity") or "low").lower(), 3),
            str(x.get("dataset") or ""),
        )
    )
    nav_fix_link = ""
    suggestions_section_html = ""
    if raw_sug and not ts_block.get("_error"):
        nav_fix_link = (
            '\n  <a href="#suggested-fixes" class="nav-jump" data-expand-suggestions="1">Fix suggestions</a>'
        )
        total_ct = int(ts_block.get("summary", {}).get("total_suggestions") or len(raw_sug))
        auto_ct = int(ts_block.get("summary", {}).get("auto_fixable_count") or len(auto_sug))
        man_ct = int(ts_block.get("summary", {}).get("manual_review_count") or len(man_sug))
        _auto_rows = []
        for s in auto_sug:
            _auto_rows.append(
                "<tr>"
                f'<td><span class="badge sug-act">{esc(s.get("suggested_action", ""))}</span></td>'
                f'<td><code>{esc(s.get("dataset") or "—")}</code></td>'
                f'<td><code>{esc(s.get("column") or "—")}</code></td>'
                f'<td><span class="badge sev-{esc((s.get("severity") or "low").lower())}">{esc(s.get("severity"))}</span></td>'
                f'<td class="msg-cell">{esc((s.get("message") or "")[:400])}</td>'
                "</tr>"
            )
        _man_rows = []
        for s in man_sug:
            _man_rows.append(
                "<tr>"
                f'<td><code>{esc(s.get("dataset") or "—")}</code></td>'
                f'<td><code>{esc(s.get("column") or "—")}</code></td>'
                f'<td><code>{esc(s.get("issue_type") or "—")}</code></td>'
                f'<td><span class="badge sev-{esc((s.get("severity") or "low").lower())}">{esc(s.get("severity"))}</span></td>'
                f"<td>{esc(s.get('row_count_affected')) if s.get('row_count_affected') is not None else '—'}</td>"
                f'<td class="msg-cell manual-guidance-cell">{esc(s.get("manual_guidance") or "")}</td>'
                "</tr>"
            )
        _auto_tbl = (
            "<h3 class=\"sug-subtitle sug-auto\">Auto-fixable issues</h3>"
            "<p class=\"section-lead\">Rule-based actions from DQ signals. "
            f"Showing all <strong>{len(auto_sug)}</strong> auto-fixable suggestion(s) "
            f"(of <strong>{total_ct}</strong> total).</p>"
            '<div class="table-wrap"><table class="data-table suggestions-table suggestions-auto"><thead><tr>'
            "<th>Action</th><th>Dataset</th><th>Column</th><th>Severity</th><th>Context</th>"
            "</tr></thead><tbody>"
            + ("".join(_auto_rows) if _auto_rows else "<tr><td colspan='5' class='muted'>(none)</td></tr>")
            + "</tbody></table></div>"
        )
        _man_tbl = (
            '<h3 class="sug-subtitle sug-manual">⚠️ Manual review required (ETL design decisions)</h3>'
            f"<p class=\"section-lead\">{man_ct} item(s) need human decisions before coding ETL logic.</p>"
            '<div class="table-wrap"><table class="data-table suggestions-table suggestions-manual"><thead><tr>'
            "<th>Dataset</th><th>Column</th><th>Issue type</th><th>Severity</th><th>Rows affected</th><th>ETL guidance</th>"
            "</tr></thead><tbody>"
            + ("".join(_man_rows) if _man_rows else "<tr><td colspan='6' class='muted'>(none)</td></tr>")
            + "</tbody></table></div>"
        )
        _sug_inner = (
            f"<p class=\"sug-summary-inline muted\">Summary: total={total_ct}, auto-fixable={auto_ct}, manual review={man_ct}</p>"
            + _auto_tbl
            + _man_tbl
        )
        suggestions_section_html = (
            '<section id="suggested-fixes" class="suggestions-section-wrap">'
            '<div class="collapsible-panel">'
            '<button type="button" class="collapsible-head" aria-expanded="true" aria-controls="sug-body">'
            '<h2>Suggested fixes</h2><span class="coll-h" aria-hidden="true"></span></button>'
            f'<div class="collapsible-body" id="sug-body">{_sug_inner}</div>'
            "</div></section>"
        )
    elif ts_block.get("_error"):
        nav_fix_link = (
            '\n  <a href="#suggested-fixes" class="nav-jump" data-expand-suggestions="1">Fix suggestions</a>'
        )
        suggestions_section_html = (
            '<section id="suggested-fixes" class="suggestions-section-wrap">'
            '<div class="collapsible-panel">'
            '<button type="button" class="collapsible-head" aria-expanded="true" aria-controls="sug-body-err">'
            '<h2>Suggested fixes</h2><span class="coll-h" aria-hidden="true"></span></button>'
            f'<div class="collapsible-body" id="sug-body-err"><p class="muted">Could not build suggestions: '
            f"{esc(ts_block.get('_error'))}</p></div>"
            "</div></section>"
        )

    v_vc = scorecard["verdict"]
    v_human = v_vc.replace("_", " ")
    ban_cls = {
        "BLOCKED": "scorecard-banner scorecard-blocked",
        "NEEDS_WORK": "scorecard-banner scorecard-needs",
        "READY": "scorecard-banner scorecard-ready",
    }.get(v_vc, "scorecard-banner scorecard-ready")
    ti_sc = scorecard["total_issues"]
    ds_score_bits = []
    for d in scorecard["per_dataset"]:
        try:
            pct = float(d["dq_score"])
        except Exception:
            pct = 0.0
        w = max(0.0, min(100.0, pct))
        fc = "score-fill-low" if pct < 35 else ("score-fill-med" if pct < 70 else "score-fill-high")
        br = d["readiness"]
        rb = "badge-ready" if br == "READY" else ("badge-needs" if br == "NEEDS_WORK" else "badge-blocked")
        icon = "✅" if br == "READY" else ("⚠️" if br == "NEEDS_WORK" else "🔴")
        ds_score_bits.append(
            f'<div class="ds-score-row"><span class="ds-name">{esc(d["name"])}</span>'
            f'<div class="score-bar"><div class="score-fill {fc}" style="width:{w}%"></div></div>'
            f'<span class="score-value">{esc(d["dq_score"])}/100</span>'
            f'<span class="badge {rb}">{icon} {esc(br)}</span></div>'
        )
    verdict_title_icon = "🔴" if v_vc == "BLOCKED" else ("⚠️" if v_vc == "NEEDS_WORK" else "✅")
    scorecard_banner_html = (
        '<section id="dq-scorecard" class="dq-scorecard-section">'
        f'<div class="{ban_cls}">'
        f'<div class="scorecard-verdict-row"><span class="v-ico">{verdict_title_icon}</span> '
        f'<span class="v-text">Data quality verdict: <strong>{esc(v_human)}</strong></span></div>'
        "<div class=\"scorecard-metrics\">Overall DQ score: "
        f"<strong>{esc(scorecard['overall_dq_score'])}</strong> / 100 · "
        f"High severity issues: <strong>{ti_sc.get('high', 0)}</strong> · "
        f"Rows affected by HIGH: <strong>{esc(scorecard['rows_affected_by_high'])}</strong> · "
        "<span title=\"Based on summed HIGH issue counts; same row may be counted multiple times — value is clamped 0–100%.\">"
        f'Approx. row share unaffected by HIGH (UI estimate): <strong>{esc(scorecard["estimated_clean_rows_pct"])}%</strong>'
        "</span></div>"
        f'<div class="scorecard-bar-list">{"".join(ds_score_bits)}</div>'
        "</div>"
        '<div class="manifest-callout">'
        "<strong>Machine-readable manifest</strong> — export run writes <code>cleaning_manifest.json</code> next to "
        "<code>report.html</code>. Use it when implementing ETL: issues, row indexes, samples, and recommended actions." 
        "</div>"
        "</section>"
    )

    _report_extra_css = """
.dq-scorecard-section { margin: 0 0 1.25rem 0; max-width: 1100px; margin-left: auto; margin-right: auto; padding: 0 1rem; }
.scorecard-banner { border-radius: 12px; padding: 1rem 1.25rem 1.1rem; border: 2px solid #cbd5e1; }
.scorecard-blocked { background: #fee2e2; border-color: #b91c1c; }
.scorecard-needs { background: #fef3c7; border-color: #b45309; }
.scorecard-ready { background: #dcfce7; border-color: #15803d; }
.scorecard-verdict-row { font-size: 1.25rem; font-weight: 700; margin-bottom: 0.5rem; display: flex; align-items: center; gap: 0.35rem; }
.scorecard-metrics { font-size: 0.95rem; margin-bottom: 0.75rem; color: #1f2937; }
.scorecard-bar-list { margin-top: 0.5rem; }
.ds-score-row { display: flex; align-items: center; gap: 0.6rem; margin: 0.45rem 0; flex-wrap: wrap; }
.ds-name { min-width: 140px; font-weight: 600; font-size: 0.88rem; }
.score-bar { flex: 1; min-width: 120px; height: 10px; background: rgba(255,255,255,0.65); border-radius: 999px; overflow: hidden; border: 1px solid rgba(0,0,0,0.08); }
.score-fill { height: 100%; border-radius: 999px; }
.score-fill-low { background: linear-gradient(90deg, #ef4444, #f87171); }
.score-fill-med { background: linear-gradient(90deg, #f59e0b, #fbbf24); }
.score-fill-high { background: linear-gradient(90deg, #22c55e, #4ade80); }
.score-value { font-size: 0.85rem; font-weight: 600; min-width: 52px; text-align: right; }
.badge-blocked { background: #fecaca; color: #7f1d1d; }
.badge-needs { background: #fde68a; color: #78350f; }
.badge-ready { background: #bbf7d0; color: #14532d; }
.manifest-callout { margin-top: 0.75rem; padding: 0.65rem 0.85rem; border-radius: 8px; border: 1px dashed #64748b; background: #f8fafc; font-size: 0.88rem; }
.dq-issue-details { border: 1px solid #e2e8f0; border-radius: 8px; padding: 0.25rem 0.5rem; margin-top: 0.35rem; background: rgba(248,250,252,0.9); }
.dq-issue-summary { cursor: pointer; font-weight: 600; padding: 0.35rem 0.25rem; }
.dq-issue-body { padding: 0.35rem 0.15rem 0.6rem; }
.suggestions-manual .manual-guidance-cell { font-size: 0.82rem; }
.suggestions-manual thead { background: #fef9c3; }
.suggestions-auto thead { background: #ccfbf1; }
.sug-subtitle { margin: 1rem 0 0.35rem; font-size: 1rem; }
.sug-summary-inline { margin: 0 0 0.5rem 0; }
.dataset-clean-summary {
  margin: 0.6rem 0 1rem;
  padding: 0.65rem 0.85rem;
  border-radius: 8px;
  border-left: 4px solid #0070ad;
  background: rgba(0, 112, 173, 0.06);
  font-size: 0.9rem;
}
.clean-summary-intro { margin: 0 0 0.55rem 0; font-size: 0.84rem; color: #334155; line-height: 1.4; }
.clean-est-row {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  column-gap: 0.85rem;
  row-gap: 0.25rem;
  padding: 0.5rem 0;
  border-bottom: 1px solid rgba(15, 23, 42, 0.07);
}
.clean-est-row:last-child { border-bottom: none; }
.clean-est-label { flex: 1 1 50%; min-width: min(100%, 280px); line-height: 1.35; }
.clean-est-value { font-weight: 700; font-size: 1.12rem; flex: 0 0 auto; }
.clean-est-tail { flex: 1 1 100%; margin: 0; line-height: 1.35; }
.llm-recs-section { margin: 2rem 0; padding: 0 1rem; max-width: 1100px; margin-left: auto; margin-right: auto; }
.rec-cards-grid { display: grid; grid-template-columns: 1fr; gap: 1rem; margin-top: 1rem; }
@media (min-width: 768px) {
  .rec-cards-grid { grid-template-columns: repeat(auto-fill, minmax(48%, 1fr)); }
}
.rec-card { background: #ffffff; border: 1px solid #e2e8f0; border-left-width: 4px; border-radius: 8px; padding: 1rem; box-shadow: 0 1px 3px rgba(0,0,0,0.05); text-align: left; }
.border-sev-high { border-left-color: #ef4444; }
.border-sev-medium { border-left-color: #f59e0b; }
.border-sev-low { border-left-color: #3b82f6; }
.rec-header { display: flex; align-items: center; gap: 0.5rem; margin-bottom: 0.75rem; flex-wrap: wrap; }
.pill-priority { background: #f1f5f9; color: #475569; font-size: 0.75rem; font-weight: 600; padding: 0.15rem 0.4rem; border-radius: 4px; }
.pill-dataset { color: #1e293b; font-size: 0.85rem; font-weight: 700; }
.pill-sev { font-size: 0.75rem; font-weight: 600; }
.rec-issue-type { font-size: 0.95rem; font-weight: 700; margin: 0 0 0.5rem 0; color: #334155; }
.rec-fix-text, .rec-why-text, .rec-risk-text { font-size: 0.88rem; margin: 0.35rem 0; color: #475569; }
.code-wrap { background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 6px; padding: 0.5rem; margin: 0.50rem 0; }
.code-title { display: block; font-size: 0.75rem; font-weight: 600; color: #64748b; margin-bottom: 0.25rem; text-transform: uppercase; }
.code-wrap pre { margin: 0; padding: 0; overflow-x: auto; }
.code-wrap code { font-family: monospace; font-size: 0.8rem; color: #0f172a; }
"""

    _report_css = get_report_html_css()
    governance_html = ""
    try:
        from agent.report_governance_sections import render_governance_html

        governance_html = render_governance_html(result) or ""
    except Exception:
        governance_html = ""

    # Generate LLM Recommendations html block
    dq_recs = result.get("dq_recommendations") or {}
    recs_list = dq_recs.get("recommendations") or []
    nav_llm_rec_link = ""
    llm_recs_section_html = ""
    if recs_list:
        nav_llm_rec_link = '\n  <a href="#llm-recs" class="nav-jump">LLM recommendations</a>'
        cards = []
        for r in recs_list:
            priority = r.get("priority") or "—"
            ds = esc(r.get("dataset") or "")
            col = esc(r.get("column") or "")
            issue = esc(r.get("issue_type") or "")
            sev = esc((r.get("severity") or "medium").lower())
            suggested_fix = esc(r.get("suggested_fix") or "")
            why = esc(r.get("why_it_matters") or "")
            risk = esc(r.get("risk") or "")
            
            sql_code = r.get("example_sql")
            pandas_code = r.get("example_pandas")
            
            sql_html = ""
            if sql_code:
                sql_html = f"""<div class="code-wrap">
                    <span class="code-title">SQL suggestion</span>
                    <pre><code class="language-sql">{esc(sql_code)}</code></pre>
                </div>"""
                
            pandas_html = ""
            if pandas_code:
                pandas_html = f"""<div class="code-wrap">
                    <span class="code-title">Pandas suggestion</span>
                    <pre><code class="language-python">{esc(pandas_code)}</code></pre>
                </div>"""
            
            cards.append(f"""
            <div class="rec-card border-sev-{sev}">
              <div class="rec-header">
                <span class="pill-priority">Priority {priority}</span>
                <span class="pill-dataset">{ds}{f'.{col}' if col else ''}</span>
                <span class="pill-sev badge sev-{sev}">{sev.upper()}</span>
              </div>
              <div class="rec-body">
                <h4 class="rec-issue-type">Issue: <code>{issue}</code></h4>
                <p class="rec-fix-text"><strong>Suggested Fix:</strong> {suggested_fix}</p>
                <p class="rec-why-text"><strong>Why it matters:</strong> {why}</p>
                {sql_html}
                {pandas_html}
                <p class="rec-risk-text"><strong>Risk:</strong> ⚠️ {risk}</p>
              </div>
            </div>
            """)
            
        llm_recs_section_html = f"""
        <section id="llm-recs" class="llm-recs-section">
          <h2>LLM Cleaning Recommendations</h2>
          <p class="section-lead">AI-assisted recommendations mapped from data quality findings.</p>
          <div class="rec-cards-grid">
            {"".join(cards)}
          </div>
        </section>
        """

    return (
        "<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n"
        "<meta charset=\"utf-8\"/>\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\"/>\n"
        "<title>Data assessment report</title>\n"
        "<style>\n"
        + _report_css
        + "\n"
        + _report_extra_css
        + "\n</style>\n"
        "</head>\n<body>\n"
        + f"""<div id="toast" class="toast" role="status">Copied to clipboard</div>
<div class="wrap">
<nav class="nav-rail" aria-label="Quick navigation">
  <span class="nav-brand">AGENT DHARA</span>
  <a href="#dq-scorecard" class="nav-jump">DQ verdict</a>
  <a href="#overview" class="nav-jump">Overview</a>
  <a href="#datasets" class="nav-jump" data-expand-datasets="1">Datasets</a>
  <a href="#relations" class="nav-jump" data-expand-relations="1">Relations</a>
  <a href="#globalq" class="nav-jump" data-expand-global="1">Global DQ</a>
  <a href="#governance" class="nav-jump">Governance</a>{nav_llm_link}{nav_llm_rec_link}{nav_fix_link}
  <button type="button" class="tool-btn secondary" id="btn-collapse-all">Collapse all</button>
  <button type="button" class="tool-btn" id="btn-expand-all">Expand all</button>
</nav>
<div class="scene-hero">
<header class="masthead">
  <div class="tagline">Intelligent data assessment</div>
  <h1>Assessment report</h1>
  <div class="sub">Generated {esc(dt)}</div>
</header>
</div>
{scorecard_banner_html}
<section id="overview">
<h2>Overview</h2>
<p class="section-lead">Aggregate view of assessed datasets: volume, shape, and footprint.</p>
<div class="kpi-grid">
  <div class="kpi"><div class="label">Datasets</div><div class="val">{len(datasets)}</div></div>
  <div class="kpi"><div class="label">Approx. rows</div><div class="val">{total_rows:,}</div></div>
  <div class="kpi"><div class="label">Total columns</div><div class="val">{total_cols:,}</div></div>
  <div class="kpi"><div class="label">Memory (bytes)</div><div class="val">{total_bytes:,}</div></div>
</div>
{exec_summary_html}
</section>
{governance_html}
{llm_section_html}
{llm_recs_section_html}
<section id="datasets" class="datasets-section">
{datasets_html}
</section>
<section id="relations">
<div class="collapsible-panel">
<button type="button" class="collapsible-head" aria-expanded="true" aria-controls="rel-body"><h2>Relationships</h2><span class="coll-h" aria-hidden="true"></span></button>
<div class="collapsible-body" id="rel-body">{rel_html}</div>
</div>
</section>
<section id="globalq">
<div class="collapsible-panel">
<button type="button" class="collapsible-head" aria-expanded="true" aria-controls="glob-body"><h2>Global quality</h2><span class="coll-h" aria-hidden="true"></span></button>
<div class="collapsible-body" id="glob-body">{glob_html}</div>
</div>
</section>
{suggestions_section_html}
</div>
<footer class="report-watermark-footer" aria-label="Attribution">
  <span class="report-watermark-oval">Agent Dhara</span>
</footer>
<script>
(function() {{
  function showToast() {{
    var t = document.getElementById('toast');
    t.classList.add('show');
    setTimeout(function() {{ t.classList.remove('show'); }}, 2000);
  }}
  function runCopy(btn) {{
    var p = btn.getAttribute('data-path') || '';
    if (navigator.clipboard && navigator.clipboard.writeText) {{
      navigator.clipboard.writeText(p).then(showToast);
    }} else {{
      var ta = document.createElement('textarea'); ta.value = p; document.body.appendChild(ta); ta.select();
      try {{ document.execCommand('copy'); showToast(); }} catch(e) {{}}
      document.body.removeChild(ta);
    }}
  }}
  document.querySelectorAll('.btn-copy-path').forEach(function(btn) {{
    btn.addEventListener('click', function(e) {{
      e.stopPropagation();
      e.preventDefault();
      runCopy(btn);
    }});
    btn.addEventListener('keydown', function(e) {{
      if (e.key === 'Enter' || e.key === ' ') {{ e.preventDefault(); e.stopPropagation(); runCopy(btn); }}
    }});
  }});
  document.querySelectorAll('.nest-toggle').forEach(function(btn) {{
    btn.addEventListener('click', function() {{
      var ex = btn.getAttribute('aria-expanded') === 'true';
      btn.setAttribute('aria-expanded', ex ? 'false' : 'true');
    }});
  }});
  function expandCollapseAll(expanded) {{
    document.querySelectorAll('.collapsible-head').forEach(function(b) {{
      b.setAttribute('aria-expanded', expanded ? 'true' : 'false');
    }});
    document.querySelectorAll('.nest-toggle').forEach(function(b) {{
      b.setAttribute('aria-expanded', expanded ? 'true' : 'false');
    }});
  }}
  document.getElementById('btn-expand-all').addEventListener('click', function() {{ expandCollapseAll(true); }});
  document.getElementById('btn-collapse-all').addEventListener('click', function() {{ expandCollapseAll(false); }});
  document.querySelectorAll('a.nav-jump').forEach(function(a) {{
    a.addEventListener('click', function(e) {{
      var href = a.getAttribute('href') || '';
      if (href.charAt(0) !== '#') return;
      var id = href.slice(1);
      var section = document.getElementById(id);
      e.preventDefault();
      if (a.getAttribute('data-expand-datasets') && section) {{
        var t = section.querySelectorAll('.nest-toggle');
        var allOpen = t.length > 0;
        for (var i = 0; i < t.length; i++) {{
          if (t[i].getAttribute('aria-expanded') !== 'true') {{ allOpen = false; break; }}
        }}
        for (var j = 0; j < t.length; j++) {{
          t[j].setAttribute('aria-expanded', allOpen ? 'false' : 'true');
        }}
      }}
      if (a.getAttribute('data-expand-relations') && section) {{
        var rh = section.querySelector('.collapsible-head');
        if (rh) {{
          var rex = rh.getAttribute('aria-expanded') === 'true';
          rh.setAttribute('aria-expanded', rex ? 'false' : 'true');
        }}
      }}
      if (a.getAttribute('data-expand-global') && section) {{
        var gh = section.querySelector('.collapsible-head');
        if (gh) {{
          var gex = gh.getAttribute('aria-expanded') === 'true';
          gh.setAttribute('aria-expanded', gex ? 'false' : 'true');
        }}
      }}
      if (a.getAttribute('data-expand-suggestions') && section) {{
        var sh = section.querySelector('.collapsible-head');
        if (sh) {{
          var sx = sh.getAttribute('aria-expanded') === 'true';
          sh.setAttribute('aria-expanded', sx ? 'false' : 'true');
        }}
      }}
      if (section) section.scrollIntoView({{ behavior: 'smooth', block: 'start' }});
    }});
  }});
  document.querySelectorAll('.collapsible-head').forEach(function(btn) {{
    btn.addEventListener('click', function() {{
      var ex = btn.getAttribute('aria-expanded') === 'true';
      btn.setAttribute('aria-expanded', ex ? 'false' : 'true');
    }});
  }});
}})();
</script>
</body>
</html>"""
    )


# ========================= Promptflow adapter & evaluator =========================

def engine_to_pf_dq(engine_result: dict) -> dict:
    """Convert engine result to Promptflow dq_profile structure."""
    pf_profiles = []
    datasets = engine_result.get("datasets", {})
    dq_ds = engine_result.get("data_quality_issues", {}).get("datasets", {})
    issue_to_dimension = {
        "nulls": "completeness", "whitespace": "consistency", "invalid_email": "validity",
        "invalid_phone": "validity", "invalid_date_format": "validity", "invalid_numeric": "validity",
        "negative_values": "validity", "suspicious_zero": "validity", "mixed_types": "consistency",
        "nested_structure": "anomalies", "duplicate_rows": "consistency", "duplicate_primary_key": "consistency",
        "potential_primary_key": "consistency",
    }
    for ds_name, meta in datasets.items():
        row_count = int(meta.get("row_count", 0))
        col_count = int(meta.get("column_count", 0))
        cols_meta = meta.get("columns", {})
        issues = dq_ds.get(ds_name, {}).get("issues", [])
        col_dims = {}
        for col_name, cmeta in cols_meta.items():
            null_rate = float(cmeta.get("null_percentage", 0.0))
            uniq = cmeta.get("unique_count")
            uniq_rate = (float(uniq) / row_count) if (uniq is not None and row_count) else None
            completeness = {"null_rate": null_rate, "completeness_score": (1.0 - null_rate) if null_rate is not None else None, "missing_pattern": None}
            consistency = {"data_type": cmeta.get("dtype"), "duplicate_count": None, "duplicate_rate": None, "distinct_count": uniq, "unique_rate": uniq_rate, "cardinality_category": "high" if uniq == row_count else ("low" if (uniq_rate is not None and uniq_rate < 0.01) else "medium") if (uniq is not None and row_count) else None, "type_consistency_rate": None}
            validity = {"pattern_conformance": {}, "numeric_stats": {}}
            anomalies = {"outlier_rate": None, "top_values": None, "entropy": None}
            semantic_validity = {"semantic_type": cmeta.get("semantic_type"), "type_inferred": bool(cmeta.get("semantic_type")), "business_rule_checks": None}
            col_dims[col_name] = {"column_name": col_name, "data_type": cmeta.get("dtype"), "sample_values": [], "completeness": completeness, "consistency": consistency, "validity": validity, "anomalies": anomalies, "semantic_validity": semantic_validity}
        for it in issues:
            col = it.get("column")
            i_typ = it.get("type")
            dim = issue_to_dimension.get(i_typ)
            if dim and col in col_dims:
                if i_typ == "duplicate_primary_key" and row_count:
                    cnt = int(it.get("count") or 0)
                    col_dims[col]["consistency"]["duplicate_count"] = cnt
                    col_dims[col]["consistency"]["duplicate_rate"] = cnt / row_count
                if i_typ == "mixed_types" and col_dims[col]["consistency"]["type_consistency_rate"] is None:
                    col_dims[col]["consistency"]["type_consistency_rate"] = 0.7
        pf_profiles.append({"file_name": ds_name, "sheet_name": None, "total_rows": row_count, "total_columns": col_count, "column_quality": dict(col_dims)})
    return {"dq_profile": pf_profiles}


def _eval_completeness(m):
    s = m.get("completeness_score")
    if s is None: return "UNKNOWN"
    if s >= 0.95: return "PASS"
    if s >= 0.80: return "WARN"
    return "FAIL"

def _eval_consistency(m):
    tcr, dup_rate = m.get("type_consistency_rate"), m.get("duplicate_rate")
    issues = 0
    if tcr is not None and tcr < 0.95: issues += 1
    if dup_rate is not None and dup_rate > 0.10: issues += 1
    return "PASS" if issues == 0 else ("WARN" if issues == 1 else "FAIL")

def _eval_validity(m):
    pc = m.get("pattern_conformance", {}) or {}
    if not pc: return "UNKNOWN"
    for _, rate in pc.items():
        if rate is not None and rate < 0.80: return "FAIL"
    if any(v is not None and v < 0.95 for v in pc.values()): return "WARN"
    return "PASS"

def _eval_anomalies(m):
    orate, ent = m.get("outlier_rate"), m.get("entropy")
    issues = 0
    if orate is not None and orate > 0.15: issues += 1
    if ent is not None and ent < 1.0: issues += 1
    return "PASS" if issues == 0 else ("WARN" if issues == 1 else "FAIL")

def _eval_semantic(m):
    st, br = m.get("semantic_type"), m.get("business_rule_checks")
    if st is None or st == "unknown": return "UNKNOWN"
    if not br: return "PASS"
    fails = sum(1 for _, r in (br or {}).items() if r is not None and r < 0.85)
    if fails == 0: return "PASS"
    if fails == 1: return "WARN"
    return "FAIL"


def evaluate_dq_rules_inline(pf_input: dict) -> dict:
    """Evaluate dq_profile into PASS/WARN/FAIL (file & column level)."""
    dq_profiles = pf_input.get("dq_profile", [])
    evaluations = []
    for fp in dq_profiles:
        file_name = fp.get("file_name")
        cq = fp.get("column_quality", {}) or {}
        dim_counts = {d: {"PASS": 0, "WARN": 0, "FAIL": 0, "UNKNOWN": 0} for d in ["completeness", "consistency", "validity", "anomalies", "semantic_validity"]}
        file_eval = {"file_name": file_name, "sheet_name": fp.get("sheet_name"), "total_rows": fp.get("total_rows"), "total_columns": fp.get("total_columns"), "column_evaluations": {}, "dimension_summary": {}, "overall_quality": "PASS"}
        for col_name, metrics in cq.items():
            comp = _eval_completeness(metrics.get("completeness", {}))
            cons = _eval_consistency(metrics.get("consistency", {}))
            vali = _eval_validity(metrics.get("validity", {}))
            anom = _eval_anomalies(metrics.get("anomalies", {}))
            sema = _eval_semantic(metrics.get("semantic_validity", {}))
            for d, s in (("completeness", comp), ("consistency", cons), ("validity", vali), ("anomalies", anom), ("semantic_validity", sema)):
                dim_counts[d][s] += 1
            statuses = [comp, cons, vali, anom, sema]
            overall = "FAIL" if "FAIL" in statuses else ("WARN" if "WARN" in statuses else "PASS")
            file_eval["column_evaluations"][col_name] = {"column_name": col_name, "data_type": metrics.get("data_type"), "dimensions": {"completeness": comp, "consistency": cons, "validity": vali, "anomalies": anom, "semantic_validity": sema}, "overall_status": overall}
        for dim, counts in dim_counts.items():
            total = sum(counts.values())
            file_eval["dimension_summary"][dim] = {"pass": counts["PASS"], "warn": counts["WARN"], "fail": counts["FAIL"], "unknown": counts["UNKNOWN"], "total": total, "pass_rate": (counts["PASS"] / total) if total else 0}
        failed_dims = sum(1 for d in dim_counts.values() if d["FAIL"] > 0)
        warned_dims = sum(1 for d in dim_counts.values() if d["WARN"] > 0 and d["FAIL"] == 0)
        file_eval["overall_quality"] = "FAIL" if failed_dims > 0 else ("WARN" if warned_dims > 0 else "PASS")
        evaluations.append(file_eval)
    summary = {"total_files_evaluated": len(evaluations), "passed_files": sum(1 for e in evaluations if e["overall_quality"] == "PASS"), "warned_files": sum(1 for e in evaluations if e["overall_quality"] == "WARN"), "failed_files": sum(1 for e in evaluations if e["overall_quality"] == "FAIL"), "dimension_overview": {dim: {"total_pass": sum(e["dimension_summary"][dim]["pass"] for e in evaluations), "total_warn": sum(e["dimension_summary"][dim]["warn"] for e in evaluations), "total_fail": sum(e["dimension_summary"][dim]["fail"] for e in evaluations)} for dim in ["completeness", "consistency", "validity", "anomalies", "semantic_validity"]}}
    return {"evaluations": evaluations, "summary": summary}


# ========================= Azure Blob helpers =========================

def get_azure_blob_connector_for_output(source_cfg: Dict[str, Any]) -> Optional[Tuple[Any, str]]:
    if not AZURE_BLOB_AVAILABLE:
        return None
    try:
        for loc in source_cfg.get("locations", []):
            if (loc.get("type") or "").lower() == "azure_blob_output":
                conn_cfg = loc.get("connection", {})
                connector = AzureBlobStorageConnector(conn_cfg)
                container_name = conn_cfg.get("container", "output")
                return connector, container_name
    except Exception as e:
        logger.warning("Could not init Azure Blob connector for uploads: %s", e)
    return None


def get_azure_blob_connector_for_assessment(source_cfg: Dict[str, Any]) -> Optional[Tuple[Any, str]]:
    """First assessment container only (legacy); prefer load_all_assessment_blob_datasets for all."""
    if not AZURE_BLOB_AVAILABLE:
        return None
    try:
        for loc in source_cfg.get("locations", []):
            if (loc.get("type") or "").lower() == "azure_blob":
                conn_cfg = loc.get("connection", {})
                connector = AzureBlobStorageConnector(conn_cfg)
                container_name = conn_cfg.get("container", "assessment")
                return connector, container_name
    except Exception as e:
        logger.warning("Could not init Azure Blob connector for assessment: %s", e)
    return None


def _azure_blob_location_label(loc: Dict[str, Any], conn_cfg: Dict[str, Any], idx: int) -> str:
    for k in ("id", "label", "name"):
        v = loc.get(k)
        if v and str(v).strip():
            s = re.sub(r"[^\w\-]+", "_", str(v).strip())[:48].strip("_")
            if s:
                return s
    c = conn_cfg.get("container") or "blob"
    s = re.sub(r"[^\w\-]+", "_", str(c))[:32].strip("_") or f"blob_{idx}"
    return s


def load_all_assessment_blob_datasets(source_cfg: Dict[str, Any], *, only_blobs: Optional[List[str]] = None) -> Dict[str, Any]:
    """
    Load every type=azure_blob location. Single container: keys are blob paths (unchanged).
    Multiple containers: keys are \"{label}__{blob_path}\" to avoid collisions.
    """
    if not AZURE_BLOB_AVAILABLE:
        return {}
    blob_locs = [
        loc
        for loc in source_cfg.get("locations", [])
        if (loc.get("type") or "").lower() == "azure_blob"
    ]
    if not blob_locs:
        return {}
    out: Dict[str, Any] = {}
    multi = len(blob_locs) > 1
    only_set = {str(x).strip() for x in (only_blobs or []) if str(x).strip()}
    for idx, loc in enumerate(blob_locs):
        conn_cfg = loc.get("connection", {}) or {}
        container_name = conn_cfg.get("container", "assessment")
        try:
            connector = AzureBlobStorageConnector(conn_cfg)
        except Exception as e:
            logger.warning("Azure Blob container %s skipped: %s", container_name, e)
            continue
        blobs = sorted(connector.list_blobs())
        if only_set:
            blobs = [b for b in blobs if b in only_set]
        loaded = connector.load_all_blobs(folder_prefix="", blobs=blobs)
        if not multi:
            out.update(loaded)
            continue
        label = _azure_blob_location_label(loc, conn_cfg, idx)
        for bname, df in loaded.items():
            key = f"{label}__{bname}"
            if key in out:
                key = f"{label}__{idx}__{bname}"
            out[key] = df
    return out


def upload_output_to_azure(file_path: str, blob_name: str, source_cfg: Dict[str, Any], output_container: str) -> bool:
    if not AZURE_BLOB_AVAILABLE:
        return False
    result = get_azure_blob_connector_for_output(source_cfg)
    if result is None:
        return False
    connector, _ = result
    return connector.upload_file(file_path, blob_name=blob_name, container=output_container)


def upload_data_to_azure(data: bytes, blob_name: str, source_cfg: Dict[str, Any], output_container: str) -> bool:
    if not AZURE_BLOB_AVAILABLE:
        return False
    result = get_azure_blob_connector_for_output(source_cfg)
    if result is None:
        return False
    connector, _ = result
    return connector.upload_blob(blob_name, data, container=output_container)


# ========================= MAIN =========================

def main():
    args = build_args()
    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    _doctor_env_hint()

    # Legacy: --stream-file always runs stream batch and exits (no scope menu).
    if args.stream_file:
        try:
            from agent.mcp_interface import process_stream_chunk
            with open(args.stream_file, "r", encoding="utf-8") as f:
                records = json.load(f)
            if not isinstance(records, list):
                logger.error("Stream file must contain a JSON array of objects")
                sys.exit(5)
            report = process_stream_chunk(records, name=args.stream_name)
            print("=== STREAM BATCH REPORT ===")
            print(json.dumps(report, indent=2, default=to_json_safe))
            print("=== DONE ===")
            return
        except Exception as e:
            logger.exception("Could not process stream file: %s", e)
            sys.exit(6)

    from agent.evaluation_scope import (
        MODE_ALL,
        MODE_BLOB,
        MODE_INTERACTIVE,
        MODE_LOCAL,
        MODE_SQL,
        MODE_STREAM,
        default_evaluate_mode as _default_eval_mode,
        interactive_select_mode,
        location_types_for_mode,
        prompt_stream_file_path,
    )

    eval_mode = (args.evaluate or "auto").lower()
    if eval_mode == "auto":
        eval_mode = _default_eval_mode()
    if eval_mode == MODE_INTERACTIVE:
        eval_mode = interactive_select_mode()

    if eval_mode == MODE_STREAM:
        stream_path = prompt_stream_file_path()
        if not stream_path:
            logger.error("Stream mode requires a JSON array file path.")
            sys.exit(6)
        try:
            from agent.mcp_interface import process_stream_chunk
            with open(stream_path, "r", encoding="utf-8") as f:
                records = json.load(f)
            if not isinstance(records, list):
                logger.error("Stream file must contain a JSON array of objects")
                sys.exit(5)
            report = process_stream_chunk(records, name=args.stream_name)
            print("=== STREAM BATCH REPORT ===")
            print(json.dumps(report, indent=2, default=to_json_safe))
            print("=== DONE ===")
            return
        except Exception as e:
            logger.exception("Could not process stream file: %s", e)
            sys.exit(6)

    cfg_root = load_config(args.sources)
    source_cfg = cfg_root.get("source", cfg_root)
    has_azure_blob = any((loc.get("type") or "").lower() == "azure_blob" for loc in source_cfg.get("locations", []))
    has_filesystem = any((loc.get("type") or "").lower() == "filesystem" for loc in source_cfg.get("locations", []))
    db_locs = [
        loc for loc in source_cfg.get("locations", [])
        if (loc.get("type") or "").lower() == "database"
    ]
    has_sql = bool(db_locs) and AzureSQLPythonNetConnector is not None

    if eval_mode == MODE_SQL:
        if not has_sql:
            logger.critical("SQL-only evaluation requires a database location and SQL connector (pythonnet).")
            sys.exit(6)
    elif eval_mode == MODE_BLOB:
        if not has_azure_blob:
            logger.critical("Blob-only evaluation requires at least one azure_blob location in sources.yaml.")
            sys.exit(6)
        if args.skip_azure:
            logger.critical("Blob-only evaluation cannot use --skip-azure.")
            sys.exit(6)
    elif eval_mode == MODE_LOCAL:
        if not has_filesystem:
            logger.critical("Local-only evaluation requires a filesystem location in sources.yaml.")
            sys.exit(6)
    elif eval_mode == MODE_ALL:
        if not has_azure_blob and not has_filesystem and not has_sql:
            logger.critical(
                "Need at least one data source: azure_blob, filesystem, or database (with SQL connector available)"
            )
            sys.exit(6)
    else:
        logger.critical("Unknown evaluation mode: %s", eval_mode)
        sys.exit(6)

    multi_sql = len(db_locs) > 1

    if has_sql and eval_mode in (MODE_SQL, MODE_ALL):
        if args.list_only:
            for db_idx, db_loc in enumerate(db_locs):
                conn_cfg = db_loc.get("connection", {}) or {}
                lbl = (db_loc.get("id") or db_loc.get("label") or "").strip() or conn_cfg.get(
                    "database", f"database_{db_idx}"
                )
                print(f"\n=== Azure SQL [{lbl}] ===")
                print("Server   :", conn_cfg.get("server"))
                print("Database :", conn_cfg.get("database"))
                try:
                    connector = AzureSQLPythonNetConnector(conn_cfg)
                    tables = connector.discover_tables()
                except Exception as e:
                    logger.info("Table discovery failed [%s]: %s", lbl, str(e)[:200])
                    tables = []
                if not tables:
                    logger.info("No tables found for [%s]", lbl)
                else:
                    for t in tables:
                        print(" -", t if not multi_sql else f"{lbl} :: {t}")
            print("\n=== DONE (listed only) ===")
            return

        for db_idx, db_loc in enumerate(db_locs):
            conn_cfg = db_loc.get("connection", {}) or {}
            lbl = (db_loc.get("id") or db_loc.get("label") or "").strip() or conn_cfg.get(
                "database", f"database_{db_idx}"
            )
            logger.debug("DB [%s] connection keys: %s", lbl, list(conn_cfg.keys()))
            print(f"\n=== Connecting to Azure SQL [{lbl}] ===")
            print("Server   :", conn_cfg.get("server"))
            print("Database :", conn_cfg.get("database"))
            try:
                connector = AzureSQLPythonNetConnector(conn_cfg)
                tables = connector.discover_tables()
            except Exception as e:
                logger.info("Table discovery failed [%s]: %s", lbl, str(e)[:200])
                tables = []
                connector = None
            if not tables:
                logger.info("No tables found for [%s]", lbl)
            else:
                for t in tables:
                    print(" -", t if not multi_sql else f"{lbl} :: {t}")

            if args.schema_only or args.with_schema:
                print(f"\n=== Table Schemas [{lbl}] ===")
                if connector and tables:
                    for table in tables:
                        disp = table if not multi_sql else f"{lbl} / {table}"
                        print(f"\n--- {disp} ---")
                        ok = print_schema_info_schema(connector, table)
                        if not ok:
                            print_schema_top0(connector, table)

            if not args.schema_only and connector and tables:
                print(f"\n=== Table Previews [{lbl}] ===")
                for table in tables:
                    disp = table if not multi_sql else f"{lbl} / {table}"
                    print(f"\n--- {disp} ---")
                    try:
                        n = args.rows if args.rows > 0 else 5
                        df = connector.preview_table(table, n)
                        if df is None or df.empty:
                            print("[INFO] (empty table)")
                        else:
                            print(df.head(n))
                    except Exception as e:
                        logger.error("Preview failed for %s: %s", table, e)

        if args.schema_only:
            print("\n=== DONE ===")
            return
        if args.with_schema and args.rows <= 0:
            print("\n=== DONE ===")
            return
    else:
        if eval_mode in (MODE_SQL, MODE_ALL):
            print("\n[INFO] Skipping SQL Runner (no database configured)")
        else:
            print("\n[INFO] Skipping SQL (evaluation scope excludes SQL)")

    print("\n=== Running Intelligent Data Assessment ===")
    print(f"=== Scope: {eval_mode} ===")
    _run_t0 = time.perf_counter()
    from datetime import datetime as _dt_utc, timezone as _tz

    _run_started = _dt_utc.now(_tz.utc).isoformat()
    blob_data = {}
    load_blob = eval_mode in (MODE_BLOB, MODE_ALL) and not args.skip_azure
    if load_blob:
        blob_locs = [
            loc
            for loc in source_cfg.get("locations", [])
            if (loc.get("type") or "").lower() == "azure_blob"
        ]
        if blob_locs:
            only_blobs: List[str] = []
            if (args.blob_names or "").strip():
                only_blobs = [x.strip() for x in (args.blob_names or "").split(",") if x.strip()]
            blob_data = load_all_assessment_blob_datasets(source_cfg, only_blobs=only_blobs or None)
            logger.info(
                "Loaded %d datasets from %d Azure Blob container(s)",
                len(blob_data),
                len(blob_locs),
            )
            for blob_name, df in sorted(blob_data.items()):
                print(f"  - {blob_name}: {len(df)} rows x {len(df.columns)} columns")
        else:
            logger.info("No azure_blob locations in config")
    elif args.skip_azure:
        logger.info("Skipping Azure Blob (--skip-azure)")
    else:
        logger.info("Skipping Azure Blob (evaluation scope excludes blob)")

    dq_thresholds_path = args.dq_thresholds or os.environ.get("DQ_THRESHOLDS_PATH")
    if not dq_thresholds_path and os.path.isfile(os.path.join("config", "dq_thresholds.yaml")):
        dq_thresholds_path = os.path.join("config", "dq_thresholds.yaml")
    location_filter = location_types_for_mode(eval_mode)
    result = load_and_profile(
        source_cfg,
        additional_data=blob_data,
        dq_thresholds_path=dq_thresholds_path,
        return_datasets=False,
        location_types=location_filter,
    )
    _attach_run_metadata_and_suggestions(result, _run_t0, _run_started, args.sources or "")
    result.setdefault("run_metadata", {})["evaluation_scope"] = eval_mode
    logger.info(
        "Assessment finished in %.2fs | DQ rollup high/medium/low: %s",
        result.get("run_metadata", {}).get("duration_seconds", 0),
        result.get("run_metadata", {}).get("dq_issue_totals"),
    )

    if getattr(args, "llm_insights", False):
        try:
            from agent.llm_assessment_enhancer import generate_llm_insights

            result["llm_insights"] = generate_llm_insights(result)
            li = result["llm_insights"]
            if li.get("success"):
                logger.info("LLM insights generated (Azure OpenAI)")
            else:
                logger.warning("LLM insights not generated: %s", li.get("error"))
        except Exception as e:
            logger.exception("LLM insights failed: %s", e)
            result["llm_insights"] = {"success": False, "error": str(e), "parsed": None}

    def _ensure_parent(path: Optional[str]):
        if not path:
            return
        parent = os.path.dirname(path)
        if parent and not os.path.isdir(parent):
            os.makedirs(parent, exist_ok=True)

    def _export(path_opt: Optional[str], content_bytes: bytes, content_str: Optional[str], blob_basename: str, desc: str):
        if not path_opt:
            return
        try:
            if args.azure_only and args.export_to_azure:
                if upload_data_to_azure(content_bytes, blob_basename, source_cfg, args.azure_output_container):
                    logger.info("Uploaded %s to Azure container '%s'", desc, args.azure_output_container)
                else:
                    logger.error("Failed to upload %s to Azure", desc)
            else:
                _ensure_parent(path_opt)
                if content_str is not None:
                    with open(path_opt, "w", encoding="utf-8") as f:
                        f.write(content_str)
                else:
                    with open(path_opt, "wb") as f:
                        f.write(content_bytes)
                logger.info("Wrote %s to: %s", desc, path_opt)
                if args.export_to_azure:
                    if upload_output_to_azure(path_opt, blob_basename, source_cfg, args.azure_output_container):
                        logger.info("Uploaded %s to Azure container '%s'", desc, args.azure_output_container)
        except Exception as e:
            logger.exception("Could not write/upload %s: %s", desc, e)

    if args.export_json:
        json_bytes = json.dumps(result, ensure_ascii=False, indent=2, default=to_json_safe).encode("utf-8")
        _export(args.export_json, json_bytes, None, os.path.basename(args.export_json), "JSON report")

    if args.export_report:
        md = build_markdown_report(result)
        md_bytes = md.encode("utf-8")
        _export(args.export_report, md_bytes, md, os.path.basename(args.export_report), "Markdown report")

    if args.export_html:
        html = build_html_report(result)
        html_bytes = html.encode("utf-8")
        _export(args.export_html, html_bytes, html, os.path.basename(args.export_html), "HTML report")

    # Consolidated reports: report.* at root + by_path/<folder>/report.* per source location
    if args.reports_dir:
        reports_dir = args.reports_dir
        os.makedirs(reports_dir, exist_ok=True)
        datasets = result.get("datasets", {})
        json_bytes = json.dumps(result, ensure_ascii=False, indent=2, default=to_json_safe).encode("utf-8")
        with open(os.path.join(reports_dir, "report.json"), "wb") as f:
            f.write(json_bytes)
        logger.info("Wrote %s", os.path.join(reports_dir, "report.json"))
        md_full = build_markdown_report(result)
        with open(os.path.join(reports_dir, "report.md"), "w", encoding="utf-8") as f:
            f.write(md_full)
        logger.info("Wrote %s", os.path.join(reports_dir, "report.md"))
        html_full = build_html_report(result)
        with open(os.path.join(reports_dir, "report.html"), "w", encoding="utf-8") as f:
            f.write(html_full)
        logger.info("Wrote %s", os.path.join(reports_dir, "report.html"))
        if args.export_manifest:
            manifest_path = args.export_manifest
        else:
            manifest_path = os.path.join(reports_dir, "cleaning_manifest.json")
        try:
            sc_m = build_dq_scorecard(result)
            mf = build_cleaning_manifest(result, result.get("transformation_suggestions") or {}, sc_m)
            _ensure_parent(manifest_path)
            with open(manifest_path, "w", encoding="utf-8") as mf_h:
                json.dump(mf, mf_h, indent=2, default=to_json_safe)
            logger.info("Cleaning manifest written: %s", manifest_path)
            print(f"✅ Cleaning manifest written: {manifest_path}")
        except Exception as e:
            logger.warning("Cleaning manifest skipped: %s", e)

    elif getattr(args, "export_manifest", None):
        try:
            sc_m = build_dq_scorecard(result)
            mf = build_cleaning_manifest(result, result.get("transformation_suggestions") or {}, sc_m)
            manifest_path = args.export_manifest
            _ensure_parent(manifest_path)
            with open(manifest_path, "w", encoding="utf-8") as mf_h:
                json.dump(mf, mf_h, indent=2, default=to_json_safe)
            logger.info("Cleaning manifest written: %s", manifest_path)
            print(f"✅ Cleaning manifest written: {manifest_path}")
        except Exception as e:
            logger.warning("Cleaning manifest failed: %s", e)

    pf_input = None
    try:
        pf_input = engine_to_pf_dq(result)
    except Exception as e:
        logger.exception("Could not build Promptflow input: %s", e)

    if args.export_pf_input and pf_input:
        pf_bytes = json.dumps(pf_input, ensure_ascii=False, indent=2, default=to_json_safe).encode("utf-8")
        _export(args.export_pf_input, pf_bytes, None, os.path.basename(args.export_pf_input), "PF input")

    if args.export_pf_eval and pf_input:
        try:
            pf_eval = evaluate_dq_rules_inline(pf_input)
            pf_eval_bytes = json.dumps(pf_eval, ensure_ascii=False, indent=2, default=to_json_safe).encode("utf-8")
            _export(args.export_pf_eval, pf_eval_bytes, None, os.path.basename(args.export_pf_eval), "PF evaluation")
        except Exception as e:
            logger.exception("Inline evaluation failed: %s", e)

    print("\n=== FULL RESULT (JSON) ===")
    print(json.dumps(result, indent=2, default=to_json_safe))
    _rm = result.get("run_metadata") or {}
    _tsn = (result.get("transformation_suggestions") or {}).get("summary") or {}
    print(
        f"\n=== DONE ===  ({_rm.get('duration_seconds')}s | "
        f"DQ high/med/low: {_rm.get('dq_issue_totals')} | "
        f"suggested fixes: {_tsn.get('total_suggestions', 0)})"
    )


if __name__ == "__main__":
    main()
