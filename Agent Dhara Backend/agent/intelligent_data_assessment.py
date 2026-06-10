"""Intelligent Data Assessment Engine.

This module profiles datasets, detects data quality issues, relationships, and generates reports.
Supported data sources: Azure SQL, filesystem (CSV/TSV/JSON/JSONL/XML/Parquet/XLSX), Azure Blob Storage
"""
from __future__ import annotations

import hashlib
import json
import os
import re

import concurrent.futures
import numpy as np
import xml.etree.ElementTree as ET
import pandas as pd
from typing import Any, Collection, Dict, List, Optional, Tuple

# Import connectors

# ============================================================
# PERFORMANCE CONFIG
# ============================================================
SAMPLING_THRESHOLD = 10_000_000
DEFAULT_SAMPLE_SIZE = 100_000
HEAVY_OPERATION_THRESHOLD = 10_000_000
try:
    from connectors.azure_sql_pythonnet import AzureSQLPythonNetConnector
except ImportError:
    AzureSQLPythonNetConnector = None


# ============================================================
# DQ THRESHOLDS (config-driven)
# ============================================================

def load_dq_thresholds(config_path: Optional[str] = None) -> Dict[str, Any]:
    """Load DQ thresholds from YAML. If path is None, use env DQ_THRESHOLDS_PATH or config/dq_thresholds.yaml."""
    path = config_path or os.environ.get("DQ_THRESHOLDS_PATH")
    if not path and os.path.isdir("config"):
        path = os.path.join("config", "dq_thresholds.yaml")
    if not path or not os.path.isfile(path):
        return {}
    try:
        import yaml
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


def _get_threshold(thresholds: Dict[str, Any], *keys: str, default: Any = None) -> Any:
    """Get nested key from thresholds, e.g. _get_threshold(t, 'severity', 'null_pct_high', default=0.25)."""
    d = thresholds
    for k in keys:
        d = (d or {}).get(k)
        if d is None:
            return default
    return d if d is not None else default


# ============================================================
# SAFE HELPERS (prevent "unhashable type: 'list'" in pandas)
# ============================================================

def _to_key(x: Any) -> Any:
    """Convert list/dict/unhashable objects into stable strings for hashing."""
    try:
        hash(x)
        return x
    except Exception:
        try:
            return json.dumps(x, sort_keys=True, ensure_ascii=False, default=str)
        except Exception:
            return repr(x)


def safe_nunique(series: pd.Series) -> int:
    """Safe nunique even when values are lists/dicts/objects."""
    try:
        if len(series) > SAMPLING_THRESHOLD:
            # For very large datasets, we estimate or use a sample to avoid OOM/freeze.
            sample = series.dropna()
            if len(sample) > DEFAULT_SAMPLE_SIZE:
                sample = sample.sample(DEFAULT_SAMPLE_SIZE, random_state=42)
            return int(sample.map(_to_key).nunique(dropna=True))
        return int(series.nunique(dropna=True))
    except Exception:
        # Fallback for unhashable types (list, dict).
        if len(series) > SAMPLING_THRESHOLD:
            sample = series.dropna().sample(DEFAULT_SAMPLE_SIZE, random_state=42)
            return int(sample.map(_to_key).nunique(dropna=True))
        return int(series.dropna().map(_to_key).nunique(dropna=True))


def safe_is_unique(series: pd.Series) -> bool:
    """Safe uniqueness check on unhashables."""
    try:
        if len(series) > SAMPLING_THRESHOLD:
            # Check if nulls exist first (fast)
            if series.isna().any():
                return False
            sample = series.sample(DEFAULT_SAMPLE_SIZE, random_state=42)
            return bool(sample.map(_to_key).is_unique)
        return bool(series.is_unique and series.notna().all())
    except Exception:
        # Fallback for unhashable
        if len(series) > SAMPLING_THRESHOLD:
            # If it's a large unhashable column, it's very unlikely to be a PK candidate 
            # if it contains complex objects. We'll check a sample.
            sample = series.dropna().sample(DEFAULT_SAMPLE_SIZE, random_state=42)
            coerced = sample.map(_to_key)
            return bool(coerced.is_unique and series.notna().all())
        coerced = series.map(_to_key)
        return bool(coerced.is_unique and series.notna().all())


# ============================================================
# SEMANTIC & DTYPE INFERENCE
# ============================================================

def _strip(x: Any) -> Any:
    return x.strip() if isinstance(x, str) else x


def _is_text_dtype(dtype) -> bool:
    ds = str(dtype).lower()
    return "object" in ds or "string" in ds or "str" in ds or "category" in ds


def _is_actual_numeric_column(col_name: str, approved_semantic_tag: Optional[str] = None) -> bool:
    """
    Check if a column is semantically numeric, filtering out identifiers,
    phones, emails, zipcodes, dates, etc.
    If approved_semantic_tag is provided, it overrides the default heuristics.
    """
    if approved_semantic_tag is not None:
        tag_lower = approved_semantic_tag.lower()
        if tag_lower == "metric":
            return True
        if tag_lower in ("id", "categorical", "date", "text"):
            return False

    c_lower = str(col_name).lower()
    if any(x in c_lower for x in ("phone", "email", "ssn", "zip", "postal", "date", "time", "dob", "stamp")) or c_lower.endswith("_at"):
        return False
    if c_lower.endswith("id") or c_lower.endswith("key") or c_lower.endswith("code"):
        return False
    if any(x in c_lower for x in ("student_id", "course_id", "instructor_id", "batch_id", "run_id")):
        return False
    return True


def scalar_type_distribution(series: pd.Series, max_sample: int = 2000) -> Dict[str, Any]:
    """
    Summarize Python scalar types present in a column.
    Useful for JSON-loaded datasets where pandas dtype is 'object' but values mix int/str/etc.
    """
    try:
        s = series.dropna()
    except Exception:
        s = series
    if len(s) > max_sample:
        try:
            s = s.sample(max_sample, random_state=42)
        except Exception:
            s = s.head(max_sample)

    counts: Dict[str, int] = {
        "str": 0,
        "int": 0,
        "float": 0,
        "bool": 0,
        "dict": 0,
        "list": 0,
        "other": 0,
    }
    total = 0
    for v in s.tolist():
        if v is None:
            continue
        total += 1
        if isinstance(v, bool):
            counts["bool"] += 1
        elif isinstance(v, int):
            counts["int"] += 1
        elif isinstance(v, float):
            counts["float"] += 1
        elif isinstance(v, str):
            counts["str"] += 1
        elif isinstance(v, dict):
            counts["dict"] += 1
        elif isinstance(v, list):
            counts["list"] += 1
        else:
            counts["other"] += 1

    pct = {k: (counts[k] / total if total else 0.0) for k in counts}
    return {"counts": counts, "pct": pct, "sample_size": int(total)}


def detect_semantic_type(values: pd.Series, col_name: str = "") -> str:
    """
    Detect semantic type from values + column name.
    Returns one of:
    date | email | uuid | url | ip_address | boolean_like |
    numeric_id | phone | free_text | categorical | unknown
    """
    col_lower = col_name.lower() if col_name else ""
    # Column-name hint (fastest — no value scan needed)
    if any(hint in col_lower for hint in _PHONE_NAME_HINTS):
        return "phone"

    non_null_vals = values.dropna()
    if len(non_null_vals) > 200:
        sample = non_null_vals.sample(n=200, random_state=42).astype(str)
    else:
        sample = non_null_vals.astype(str)

    if sample.empty:
        return "unknown"

    total = len(sample)

    # UUID — check before numeric_id (UUIDs contain digits)
    if (sample.str.match(_UUID_RE).sum() / total) >= 0.7:
        return "uuid"

    # IP address
    if (sample.str.match(_IP4_RE).sum() / total) >= 0.6:
        return "ip_address"

    # URL
    if (sample.str.match(_URL_RE).sum() / total) >= 0.5:
        return "url"

    # Email
    if sample.str.contains("@", na=False).sum() / total >= 0.5:
        return "email"

    # Boolean-like
    if (sample.str.strip().str.lower().isin(_BOOL_VALS).sum() / total) >= 0.8:
        return "boolean_like"

    # Date (ISO-8601 first, then broader)
    if sample.str.match(r'^\d{4}-\d{2}-\d{2}').sum() / total >= 0.5:
        return "date"

    # Broader date detection using dateutil
    try:
        from dateutil import parser as du_parser
        parsed_ok = 0
        is_date_hint = bool(re.search(r'(?:\b|_)(date|time|dt|created|updated|dob|birth|bday|birthday)(?:\b|_)|(_at\b|\bat\b)', col_lower))
        for v in sample.head(30):
            # If it's a simple numeric value, don't parse as date unless column name hints date or len is 8 (YYYYMMDD)
            val_strip = v.strip()
            if val_strip.replace(".", "", 1).isdigit():
                val_clean = val_strip.split(".")[0]
                if not (is_date_hint or len(val_clean) == 8):
                    continue
            try:
                du_parser.parse(v, fuzzy=False)
                parsed_ok += 1
            except Exception:
                pass
        if parsed_ok / min(30, total) >= 0.7:
            return "date"
    except ImportError:
        pass

    # Numeric ID
    if sample.str.fullmatch(r'\d+').sum() / total >= 0.9:
        return "numeric_id"

    # Free text vs categorical: use mean length
    mean_len = sample.str.len().mean()
    if mean_len > 50:
        return "free_text"

    return "categorical"


def _validate_phone_phonenumbers(val: str, default_region: str = "IN") -> bool:
    """
    Validate phone using Google's libphonenumber.
    Falls back to regex if library not available.
    default_region: ISO 3166-1 alpha-2 (e.g. "IN", "US", "GB").
    Used when number has no + prefix.
    """
    val = str(val).strip()
    if val.endswith(".0"):
        val = val[:-2]
    elif "." in val:
        try:
            parts = val.split(".")
            if len(parts) == 2 and all(c == '0' for c in parts[1]):
                val = parts[0]
        except Exception:
            pass
    try:
        import phonenumbers
        # Try parsing with + prefix (international) first
        try:
            pn = phonenumbers.parse(val, None)
        except Exception:
            # Try with default region fallback
            try:
                pn = phonenumbers.parse(val, default_region)
            except Exception:
                return False
        return phonenumbers.is_valid_number(pn)
    except ImportError:
        # Graceful fallback to existing regex
        return bool(PHONE_RE.match(val))


def _detect_phone_formats(series: pd.Series) -> Dict[str, int]:
    """
    Categorize phone values into format buckets.
    Returns counts per format type.
    """
    try:
        import phonenumbers
        buckets = {"e164": 0, "national": 0, "invalid": 0, "empty": 0}
        for val in series.dropna().astype(str).head(500):
            v = val.strip()
            if v.endswith(".0"):
                v = v[:-2]
            elif "." in v:
                try:
                    parts = v.split(".")
                    if len(parts) == 2 and all(c == '0' for c in parts[1]):
                        v = parts[0]
                except Exception:
                    pass
            if not v:
                buckets["empty"] += 1
                continue
            try:
                pn = phonenumbers.parse(v, "IN")
                fmt = phonenumbers.format_number(pn, phonenumbers.PhoneNumberFormat.E164)
                if v == fmt:
                    buckets["e164"] += 1
                else:
                    buckets["national"] += 1
            except Exception:
                buckets["invalid"] += 1
        return buckets
    except ImportError:
        return {}


def _detect_date_formats(series: pd.Series) -> Dict[str, Any]:
    """
    Analyzes date patterns using regex-based buckets to flag inconsistencies.
    """
    formats = {
        "YYYY-MM-DD": r"^\d{4}-\d{2}-\d{2}$",
        "MM/DD/YYYY": r"^\d{1,2}/\d{1,2}/\d{4}$",
        "DD-MM-YYYY": r"^\d{2}-\d{2}-\d{4}$",
        "YYYY/MM/DD": r"^\d{4}/\d{2}/\d{2}$",
        "other/timestamp": r".+"
    }
    counts = {k: 0 for k in formats}
    unparsed_cnt = 0
    total_non_null = 0
    
    # We run dateutil parser to confirm it is actually parseable as date
    from dateutil import parser as du_parser
    for val in series.dropna().astype(str).head(1000):
        v = val.strip()
        if not v: continue
        total_non_null += 1
        try:
            du_parser.parse(v, fuzzy=False)
            matched = False
            for fmt_name, regex in formats.items():
                if fmt_name != "other/timestamp" and re.match(regex, v):
                    counts[fmt_name] += 1
                    matched = True
                    break
            if not matched:
                counts["other/timestamp"] += 1
        except Exception:
            unparsed_cnt += 1
            
    return {
        "counts": counts,
        "unparsed_count": unparsed_cnt,
        "total_non_null": total_non_null
    }


def _dtype_inference_for_object(series: pd.Series) -> Optional[str]:
    """
    For object dtype, give a human hint for UI:
    - "string" | "numeric_like" | "datetime_like" | "boolean_like" | "nested" | "mixed" | "unknown"
    """
    s = series.dropna().map(_strip)
    if len(s) > 10000:
        s = s.sample(10000, random_state=42)

    # nested?
    try:
        if s.apply(lambda v: isinstance(v, (list, dict))).any():
            return "nested"
    except Exception:
        pass

    # boolean-like
    booleans = {"true", "false", "yes", "no", "0", "1"}
    try:
        if (s.astype(str).str.lower().isin(booleans).mean() > 0.8):
            return "boolean_like"
    except Exception:
        pass

    # numeric-like
    try:
        num = pd.to_numeric(s, errors="coerce")
        if (1.0 - float(num.isna().mean())) > 0.8:
            return "numeric_like"
    except Exception:
        pass

    # datetime-like (guarded: require date-ish separators; avoid numeric IDs being miscast)
    try:
        as_str = s.astype(str)
        # Require at least some obvious date delimiters in the sample.
        # This prevents numeric IDs like 1/2/3... from being interpreted as datetimes by pandas.
        if (as_str.str.contains(r"[-/:T]", regex=True).mean() >= 0.20):
            import warnings
            with warnings.catch_warnings():
                warnings.filterwarnings(
                    "ignore",
                    message="Could not infer format, so each element will be parsed individually",
                )
                dt_coerced = pd.to_datetime(s, errors="coerce")
            if (1.0 - float(dt_coerced.isna().mean())) > 0.8:
                return "datetime_like"
    except Exception:
        pass

    # plain strings?
    try:
        if s.apply(lambda v: isinstance(v, str)).mean() > 0.8:
            return "string"
    except Exception:
        pass

    try:
        if not s.empty:
            return "mixed"
    except Exception:
        pass
    return "unknown"


# ============================================================
# ACCURACY UPGRADE HELPERS
# ============================================================

def count_file_lines(fp: str) -> int:
    try:
        with open(fp, "rb") as f:
            lines = 0
            buf_size = 1024 * 1024
            read_f = f.raw.read
            buf = read_f(buf_size)
            while buf:
                lines += buf.count(b"\n")
                buf = read_f(buf_size)
            return lines
    except Exception:
        return 0


def load_csv_sampled(fp: str, sep: str = ",", max_rows: Optional[int] = None) -> pd.DataFrame:
    if not max_rows:
        return pd.read_csv(fp, sep=sep, low_memory=False)
    
    total_lines = count_file_lines(fp)
    if total_lines <= max_rows:
        return pd.read_csv(fp, sep=sep, low_memory=False)
        
    chunk_size = 50000
    sample_rate = max_rows / max(1, total_lines)
    chunks = []
    
    try:
        for chunk in pd.read_csv(fp, sep=sep, chunksize=chunk_size, low_memory=False):
            target_n = int(round(len(chunk) * sample_rate))
            if target_n > 0:
                sampled_chunk = chunk.sample(n=min(len(chunk), target_n), random_state=42)
                chunks.append(sampled_chunk)
        if chunks:
            df = pd.concat(chunks, ignore_index=True)
            if len(df) > max_rows:
                df = df.sample(n=max_rows, random_state=42).reset_index(drop=True)
            return df
        else:
            return pd.read_csv(fp, sep=sep, nrows=max_rows)
    except Exception:
        try:
            return pd.read_csv(fp, sep=sep, nrows=max_rows)
        except Exception:
            return pd.DataFrame()


def match_column_key(col_key: str, dataset_name: str, column_name: str) -> bool:
    col_key_parts = [p.strip().lower() for p in col_key.split(".")]
    ds_parts = [p.strip().lower() for p in dataset_name.split(".")]
    col_name = column_name.strip().lower()
    
    if not col_key_parts or not col_name:
        return False
        
    if col_key_parts[-1] != col_name:
        return False
        
    if len(col_key_parts) == 1:
        return True
        
    prefix_parts = col_key_parts[:-1]
    min_len = min(len(ds_parts), len(prefix_parts))
    for idx in range(1, min_len + 1):
        if ds_parts[-idx] != prefix_parts[-idx]:
            return False
            
    return True


def get_valid_values_for_column(
    business_rules: Optional[Dict[str, Any]],
    dataset_name: str,
    column_name: str
) -> Optional[List[str]]:
    if not business_rules:
        return None
    vv = business_rules.get("valid_values")
    if not vv or not isinstance(vv, dict):
        return None
    for col_key, vals in vv.items():
        if match_column_key(col_key, dataset_name, column_name):
            if isinstance(vals, list):
                return vals
            return [str(vals)]
    return None


def evaluate_custom_assertion(df: pd.DataFrame, assertion: str) -> Tuple[pd.Series, List[str]]:
    """
    Evaluates a custom assertion expression on the DataFrame.
    Returns a tuple of (boolean Series, list of referenced columns).
    """
    # 1. First attempt: standard pandas eval (very fast if it works)
    try:
        res = df.eval(assertion, engine='python')
        if isinstance(res, pd.Series):
            ref_cols = []
            for col in df.columns:
                pattern = r'\b' + re.escape(col) + r'\b'
                if re.search(pattern, assertion):
                    ref_cols.append(col)
            return res, ref_cols
    except Exception:
        pass

    # 2. Second attempt: fallback namespace evaluation
    RESERVED_WORDS = {
        "and", "or", "not", "in", "is", "if", "else", "for", "while", "def", "class",
        "import", "from", "as", "try", "except", "finally", "with", "assert", "pd", "np",
        "str", "int", "float", "bool", "list", "dict", "set", "tuple", "len", "sum", "min",
        "max", "any", "all", "true", "false", "none", "nan", "isna", "isnull", "notna", "notnull"
    }

    namespace = {
        'pd': pd,
        'np': np,
        'true': True,
        'false': False,
        'none': None,
        'True': True,
        'False': False,
        'None': None
    }
    
    sorted_cols = sorted(df.columns, key=len, reverse=True)
    sanitized_assertion = assertion
    ref_cols = []

    # First, handle backticked column references (e.g. `Email ID`)
    for col in sorted_cols:
        backticked = f"`{col}`"
        if backticked in sanitized_assertion:
            safe_var = re.sub(r'[^a-zA-Z0-9_]', '_', col)
            if not safe_var or safe_var[0].isdigit():
                safe_var = "_" + safe_var
            
            sanitized_assertion = sanitized_assertion.replace(backticked, safe_var)
            namespace[safe_var] = df[col]
            if col not in ref_cols:
                ref_cols.append(col)

    # Second, handle non-backticked column references (case-insensitive word boundary matching)
    for col in sorted_cols:
        if col.lower() in RESERVED_WORDS:
            pattern = r'\b' + re.escape(col) + r'\b'
        else:
            pattern = r'\b' + re.escape(col) + r'\b'

        if re.search(pattern, sanitized_assertion, re.IGNORECASE):
            safe_var = re.sub(r'[^a-zA-Z0-9_]', '_', col)
            if not safe_var or safe_var[0].isdigit():
                safe_var = "_" + safe_var
            
            sanitized_assertion = re.sub(pattern, safe_var, sanitized_assertion, flags=re.IGNORECASE)
            namespace[safe_var] = df[col]
            if col not in ref_cols:
                ref_cols.append(col)

    # Add any remaining columns that weren't explicitly replaced but might be in the expression
    for col in df.columns:
        safe_var = re.sub(r'[^a-zA-Z0-9_]', '_', col)
        if not safe_var or safe_var[0].isdigit():
            safe_var = "_" + safe_var
        if safe_var not in namespace:
            namespace[safe_var] = df[col]
        if re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', col):
            namespace[col] = df[col]
            namespace[col.lower()] = df[col]

    try:
        res = eval(sanitized_assertion, namespace)
        if isinstance(res, pd.Series):
            return res, ref_cols
        else:
            if isinstance(res, (bool, np.bool_)):
                return pd.Series([res] * len(df), index=df.index), ref_cols
            raise ValueError(f"Custom assertion did not return a boolean series or value (returned type {type(res)})")
    except Exception as e_inner:
        raise Exception(f"Failed to evaluate custom assertion '{assertion}' (parsed as '{sanitized_assertion}'): {str(e_inner)}")


def check_custom_assertions(df: pd.DataFrame, rules: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Evaluates custom/formula cross-column assertions.
    Unlike check_formula_rules, this does not coerce columns to numeric automatically
    unless they are already numeric, supporting string evaluations (e.g. col == 'IT').
    """
    issues = []
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        assertion = rule.get("assertion")
        if not assertion:
            continue
        severity = str(rule.get("severity", "medium")).lower()
        custom_msg = rule.get("message")
        
        try:
            res, ref_cols = evaluate_custom_assertion(df, assertion)
            viol_mask = ~res.fillna(False)
            viol_cnt = int(viol_mask.sum())
            if viol_cnt > 0:
                rows = df.index[viol_mask].tolist()
                msg = custom_msg or f"Custom rule violation: '{assertion}' ({viol_cnt} violations)"
                issues.append(dq_issue(
                    severity,
                    "custom_rule_violation",
                    msg,
                    column=",".join(ref_cols),
                    count=viol_cnt,
                    rows=rows,
                    sample=df.loc[viol_mask, ref_cols].head(5).to_dict(orient="records")
                ))
        except Exception as e:
            issues.append(dq_issue(
                "low",
                "custom_rule_error",
                f"Failed to evaluate custom assertion '{assertion}': {str(e)}"
            ))
    return issues



def profile_database_table_full(
    connector: Any,
    table: str,
    df_sample: pd.DataFrame,
    job_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Run aggregate SELECT query in-place to profile 100% of database rows instead of downloading them.
    Exclude text/blob columns. Cast bit to int.
    """
    from agent.jobs_store import add_event
    if job_id:
        add_event(job_id=job_id, level="info", message=f"Performing in-database profiling for table: {table}")
        
    try:
        schema = connector.get_table_schema(table)
    except Exception as e:
        if job_id:
            add_event(job_id=job_id, level="warning", message=f"Failed to get table schema for database profiling: {e}")
        schema = [{"name": c, "type": "varchar", "nullable": "YES"} for c in df_sample.columns]

    if not schema:
        return {}

    unsafe_types = {"text", "ntext", "image", "xml", "geography", "geometry", "varbinary", "binary"}
    select_items = ["COUNT(*) AS [__total_rows__]"]
    profiled_cols = []
    
    for col in schema:
        col_name = col["name"]
        col_type = str(col.get("type", "varchar")).lower()
        if col_type in unsafe_types:
            continue
            
        profiled_cols.append((col_name, col_type))
        col_quoted = f"[{col_name}]"
        
        select_items.append(f"SUM(CASE WHEN {col_quoted} IS NULL THEN 1 ELSE 0 END) AS [{col_name}__null_cnt]")
        select_items.append(f"COUNT(DISTINCT {col_quoted}) AS [{col_name}__distinct_cnt]")
        
        if col_type == "bit":
            select_items.append(f"MIN(CAST({col_quoted} AS INT)) AS [{col_name}__min_val]")
            select_items.append(f"MAX(CAST({col_quoted} AS INT)) AS [{col_name}__max_val]")
        else:
            select_items.append(f"MIN({col_quoted}) AS [{col_name}__min_val]")
            select_items.append(f"MAX({col_quoted}) AS [{col_name}__max_val]")
            
    table_quoted = connector._quote_two_part_name(table)
    sql = f"SELECT {', '.join(select_items)} FROM {table_quoted}"
    
    try:
        res_df = connector.execute_select(sql)
        if res_df.empty:
            return {}
        row_data = res_df.iloc[0].to_dict()
    except Exception as e:
        if job_id:
            add_event(job_id=job_id, level="warning", message=f"In-database profiling SQL failed: {e}")
        return {}
        
    total_rows = int(row_data.get("__total_rows__", 0))
    schema_map = {col["name"].lower(): col for col in schema if "name" in col}
    db_profile = {
        "row_count": total_rows,
        "columns": {}
    }
    
    for col_name, col_type in profiled_cols:
        null_cnt = row_data.get(f"{col_name}__null_cnt")
        distinct_cnt = row_data.get(f"{col_name}__distinct_cnt")
        min_val = row_data.get(f"{col_name}__min_val")
        max_val = row_data.get(f"{col_name}__max_val")
        col_schema = schema_map.get(col_name.lower()) or {}
        
        try:
            null_cnt = int(null_cnt) if null_cnt is not None else 0
        except (ValueError, TypeError):
            null_cnt = 0
            
        try:
            distinct_cnt = int(distinct_cnt) if distinct_cnt is not None else 0
        except (ValueError, TypeError):
            distinct_cnt = 0
            
        null_pct = null_cnt / max(1, total_rows)
        is_cpk = (null_cnt == 0 and distinct_cnt == total_rows and total_rows > 0)
        
        db_profile["columns"][col_name] = {
            "null_count": null_cnt,
            "null_percentage": null_pct,
            "unique_count": distinct_cnt,
            "min": min_val,
            "max": max_val,
            "candidate_primary_key": is_cpk,
            "nullable": col_schema.get("nullable", "YES")
        }
        
    return db_profile


def merge_in_db_profile(sample_profile: Dict[str, Any], db_profile: Dict[str, Any]) -> Dict[str, Any]:
    """
    Overwrites statistical counts, bounds, and PK flags in the sample profile with full DB stats.
    """
    if not db_profile:
        return sample_profile
        
    sample_profile["row_count"] = db_profile.get("row_count", sample_profile.get("row_count", 0))
    sample_profile["sampling_info"] = f"Full dataset has {sample_profile['row_count']:,} rows. Statistics (nulls, min/max, uniqueness) profiled in-database on 100% of rows."
    
    db_cols = db_profile.get("columns") or {}
    sample_cols = sample_profile.setdefault("columns", {})
    
    for col_name, db_col_info in db_cols.items():
        if col_name not in sample_cols:
            sample_cols[col_name] = {}
        col_prof = sample_cols[col_name]
        
        col_prof["null_percentage"] = db_col_info.get("null_percentage", col_prof.get("null_percentage", 0.0))
        col_prof["unique_count"] = db_col_info.get("unique_count", col_prof.get("unique_count", 0))
        col_prof["candidate_primary_key"] = db_col_info.get("candidate_primary_key", col_prof.get("candidate_primary_key", False))
        
        if "min" in db_col_info:
            col_prof["min"] = db_col_info["min"]
        if "max" in db_col_info:
            col_prof["max"] = db_col_info["max"]
            
        if "null_count" in db_col_info:
            col_prof["null_count"] = db_col_info["null_count"]
            
    return sample_profile


# ============================================================
# DATA PROFILING (pandas dtypes + inference hint for object)
# ============================================================

def select_top_priority_columns(df: pd.DataFrame, approved_semantics: Optional[Dict[str, str]] = None, top_n: int = 15) -> List[str]:
    """
    Select the top-N priority columns for deep profiling based on heuristics:
    1. Key identifiers (ID, Key, Code, Ref, PK in name)
    2. Date/Datetime columns
    3. Email/Phone/UUID semantic types (or in name)
    4. Numeric metric columns
    5. Fallback: all other columns
    """
    col_scores = []
    for col in df.columns:
        col_lower = str(col).lower()
        score = 0
        
        # Primary Key/Key identifiers
        is_key = any(x in col_lower for x in ("id", "key", "code", "ref", "pk"))
        # Email/Phone/UUID
        is_contact_or_uuid = any(x in col_lower for x in ("email", "phone", "mobile", "contact", "tel", "uuid", "guid", "uid"))
        # Date/Datetime
        is_date = any(x in col_lower for x in ("date", "time", "dt", "created", "updated", "_at"))
        
        # Approved semantic override
        approved_tag = (approved_semantics or {}).get(col, "").lower() if approved_semantics else ""
        
        if approved_tag in ("id", "pk"):
            score = 10
        elif is_key:
            score = 9
        elif approved_tag in ("email", "phone", "uuid") or is_contact_or_uuid:
            score = 8
        elif approved_tag in ("date", "datetime") or is_date:
            score = 7
        elif approved_tag == "metric" or pd.api.types.is_numeric_dtype(df[col]):
            score = 6
        else:
            score = 1
            
        col_scores.append((score, col))
        
    # Sort descending by score, stable sorting (maintains original order for same score)
    col_scores.sort(key=lambda x: x[0], reverse=True)
    return [col for _, col in col_scores[:top_n]]


def profile_dataframe(
    df: pd.DataFrame,
    job_id: Optional[str] = None,
    thresholds: Optional[Dict[str, Any]] = None,
    approved_semantics: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """
    Returns a consistent profiling dictionary for a DataFrame, including:
    - row_count, column_count, data_volume_bytes
    - columns: { col: { dtype, dtype_inference?, null_percentage, unique_count, semantic_type, candidate_primary_key }}
    """
    from agent.jobs_store import add_event
    if job_id:
        add_event(job_id=job_id, level="info", message="Profiling columns...")
    row_count = int(len(df))
    col_count = int(len(df.columns))

    # Fast memory usage estimate for large DataFrames
    if row_count > SAMPLING_THRESHOLD:
        # Shallow usage
        shallow = df.memory_usage(deep=False).sum()
        # Estimate deep overhead by sampling object columns
        obj_cols = df.select_dtypes(include=["object"]).columns
        deep_overhead = 0
        if not obj_cols.empty:
            sample_size = min(row_count, DEFAULT_SAMPLE_SIZE // 10) # Smaller sample for memory estimate
            sample = df[obj_cols].sample(sample_size, random_state=42)
            # Subtract shallow size of the sample to get deep overhead
            deep_sample = sample.memory_usage(deep=True).sum()
            shallow_sample = sample.memory_usage(deep=False).sum()
            overhead_per_row = (deep_sample - shallow_sample) / sample_size
            deep_overhead = overhead_per_row * row_count
        data_volume_bytes = int(shallow + deep_overhead)
    else:
        data_volume_bytes = int(df.memory_usage(deep=True).sum())

    ext = thresholds.get("extended_checks") or {} if thresholds else {}
    top_n = int(ext.get("top_n_priority_cols", 15))
    priority_cols = set(select_top_priority_columns(df, approved_semantics, top_n))

    profile: Dict[str, Any] = {
        "row_count": row_count,
        "column_count": col_count,
        "data_volume_bytes": data_volume_bytes,
        "sampling_info": f"Full dataset has {row_count:,} rows. Analysis performed on a representative sample of {min(row_count, SAMPLING_THRESHOLD):,} rows." if row_count > SAMPLING_THRESHOLD else "Analysis performed on 100% of rows.",
        "columns": {},
        "priority_columns": list(priority_cols),
    }

    def profile_col(col: str) -> Tuple[str, Dict[str, Any]]:
        s = df[col]
        dtype_str = str(s.dtype)
        semantic = detect_semantic_type(s, col)
        
        is_priority = (col in priority_cols)
        
        if is_priority:
            hint = _dtype_inference_for_object(s) if _is_text_dtype(dtype_str) else None
            if semantic == "numeric_id" and hint == "datetime_like":
                hint = "numeric_like"
            type_dist = scalar_type_distribution(s) if _is_text_dtype(dtype_str) else None
        else:
            hint = None
            type_dist = None

        raw_smp = s.dropna().head(20).astype(str).tolist()

        null_pct = float(s.isna().mean())
        null_count = int(s.isna().sum())
        type_confidence = 0.92 if hint else (0.78 if _is_text_dtype(dtype_str) else 0.95)

        col_profile = {
            "dtype": dtype_str,
            "dtype_inference": hint,
            "type_distribution": type_dist,
            "null_percentage": null_pct,
            "null_count": null_count,
            "type_confidence": round(type_confidence, 3),
            "unique_count": safe_nunique(s),
            "semantic_type": semantic,
            "candidate_primary_key": safe_is_unique(s),
            "raw_samples": raw_smp,
        }
        
        if is_priority:
            n_nonnull = int(s.notna().sum())
            if n_nonnull > 0:
                dupes = int(s.duplicated(keep=False).sum())
                if dupes > 0:
                    col_profile["duplicate_value_count"] = dupes
                try:
                    num = pd.to_numeric(s, errors="coerce")
                    nn = num.dropna()
                    if len(nn) >= 3:
                        col_profile["mean"] = float(nn.mean())
                        col_profile["median"] = float(nn.median())
                        col_profile["std"] = float(nn.std())
                        if len(nn) >= 8:
                            sk = float(nn.skew())
                            col_profile["skew"] = round(sk, 4)
                            col_profile["p5"] = float(nn.quantile(0.05))
                            col_profile["p95"] = float(nn.quantile(0.95))
                except Exception:
                    pass
        return col, col_profile

    # Parallelize column profiling for speed on large datasets
    processed_cols = 0
    with concurrent.futures.ThreadPoolExecutor() as executor:
        futures = {executor.submit(profile_col, col): col for col in df.columns}
        for future in concurrent.futures.as_completed(futures):
            col, col_prof = future.result()
            profile["columns"][col] = col_prof
            processed_cols += 1
            if job_id and col_count > 0:
                pct = int((processed_cols / col_count) * 40) # 0-40% for profiling
                overall_pct = 20 + pct
                try:
                    from agent.jobs_store import update_job_progress
                    update_job_progress(job_id, overall_pct)
                except Exception:
                    pass
                add_event(job_id=job_id, level="info", message=f"Profiling: {pct}% complete")

    return profile


# ============================================================
# SQL LOADER
# ============================================================

def _sql_location_key_prefix(loc: Dict[str, Any], conn: Dict[str, Any], db_index: int, multi_db: bool) -> str:
    """Prefix for dataset keys when multiple database locations are configured."""
    if not multi_db:
        return ""
    for k in ("id", "label", "name"):
        v = loc.get(k)
        if v and str(v).strip():
            s = re.sub(r"[^\w\-]+", "_", str(v).strip())[:48].strip("_")
            if s:
                return s + "__"
    db = str(conn.get("database") or conn.get("Database") or f"db{db_index}")
    srv = str(conn.get("server") or conn.get("Server") or "")
    h = hashlib.md5(f"{srv}|{db}".encode("utf-8")).hexdigest()[:8]
    tail = re.sub(r"[^\w]+", "_", db)[:24].strip("_") or "db"
    return f"{tail}_{h}__"


def load_sql_datasets(
    connection_cfg: Dict[str, Any],
    dataset_key_prefix: str = "",
    max_rows: Optional[int] = None,
    db_connectors_by_dataset: Optional[Dict[str, Tuple[Any, str]]] = None,
    only_tables: Optional[List[str]] = None
) -> Dict[str, pd.DataFrame]:
    """
    Loads all discovered tables from Azure SQL using the provided connector configuration.
    Returns a dict: { "<schema>.<table>": DataFrame, ... } or prefixed keys if dataset_key_prefix set.
    """
    if AzureSQLPythonNetConnector is None:
        print("[INFO] AzureSQLPythonNetConnector not available, skipping SQL datasets")
        return {}

    p = (dataset_key_prefix or "").strip()
    if p and not p.endswith("__"):
        p = p + "__"

    datasets: Dict[str, pd.DataFrame] = {}
    try:
        connector = AzureSQLPythonNetConnector(connection_cfg)
        tables = connector.discover_tables()

        if only_tables is not None:
            allowed_set = {t.lower() for t in only_tables}
            filtered_tables = []
            for t in tables:
                key = f"{p}{t}" if p else t
                if key.lower() in allowed_set:
                    filtered_tables.append(t)
            tables = filtered_tables

        for table in tables:
            key = f"{p}{table}" if p else table
            try:
                datasets[key] = connector.load_table(table, max_rows=max_rows)
                if db_connectors_by_dataset is not None:
                    db_connectors_by_dataset[key] = (connector, table)
            except Exception as e:
                print(f"[ERROR] Failed to load table {table}: {e}")
    except Exception as e:
        print(f"[INFO] Failed to connect to SQL database: {e}")

    return datasets


# ============================================================
# JSON DEEP-FLATTEN HELPERS
# ============================================================

def _find_record_path(obj: Any, path: Optional[List[str]] = None, max_depth: int = 4) -> Optional[List[str]]:
    """Find nested list-of-dicts path for record_path (e.g., ['departments','employees'])."""
    if path is None:
        path = []
    if max_depth < 0:
        return None
    if isinstance(obj, list):
        if obj and isinstance(obj[0], dict):
            return path
        return None
    if isinstance(obj, dict):
        for k, v in obj.items():
            rp = _find_record_path(v, path + [k], max_depth - 1)
            if rp:
                return rp
    return None


def _json_deep_flatten(data: Any) -> pd.DataFrame:
    from pandas import json_normalize

    if isinstance(data, list):
        if not data:
            return pd.DataFrame()
        if isinstance(data[0], dict):
            return json_normalize(data, max_level=1)
        return pd.DataFrame({"value": data})

    if not isinstance(data, dict):
        return pd.DataFrame([{"value": data}])

    record_path = _find_record_path(data, max_depth=4)
    if not record_path:
        return json_normalize(data, max_level=1)

    meta_keys: List[str] = []

    def collect_scalars(d: Dict[str, Any]) -> None:
        for k, v in d.items():
            if not isinstance(v, (list, dict)):
                if k not in meta_keys:
                    meta_keys.append(k)

    parent: Any = data
    for k in record_path[:-1]:
        if isinstance(parent, dict):
            collect_scalars(parent)
            parent = parent.get(k, {})
        else:
            break

    try:
        return json_normalize(
            data,
            record_path=record_path,
            meta=meta_keys if meta_keys else None,
            errors="ignore"
        )
    except Exception:
        return json_normalize(data, max_level=1)


def _load_json_to_df(path: str, max_rows: Optional[int] = None) -> pd.DataFrame:
    if path.lower().endswith(".jsonl"):
        if max_rows is not None:
            import random
            reservoir = []
            count = 0
            rng = random.Random(42)
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    if len(reservoir) < max_rows:
                        reservoir.append(line)
                    else:
                        j = rng.randint(0, count)
                        if j < max_rows:
                            reservoir[j] = line
                    count += 1
            rows = []
            for line in reservoir:
                try:
                    rows.append(json.loads(line))
                except Exception:
                    rows.append({"value": line})
        else:
            rows = []
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rows.append(json.loads(line))
                    except Exception:
                        rows.append({"value": line})
        if not rows:
            return pd.DataFrame()
        return pd.json_normalize(rows, max_level=1)

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return _json_deep_flatten(data)


# ============================================================
# XML EXPLODE (one row per <Item> container when consistent)
# ============================================================

def _xml_to_df_exploded(path: str) -> pd.DataFrame:
    root = ET.parse(path).getroot()
    nodes = list(root)
    if not nodes:
        return pd.DataFrame()

    if len(set(n.tag for n in nodes)) == 1:
        records: List[Dict[str, Any]] = []
        for node in nodes:
            base: Dict[str, Any] = {}
            containers: List[ET.Element] = []
            for child in node:
                g = list(child)
                if g:
                    containers.append(child)
                else:
                    base[child.tag] = child.text

            exploded = False
            for container in containers:
                items = list(container)
                if not items:
                    continue
                if len({c.tag for c in items}) == 1:
                    exploded = True
                    for item in items:
                        row = dict(base)
                        for sub in item:
                            row[f"{container.tag}_{sub.tag}"] = sub.text
                        records.append(row)
            if not exploded:
                records.append(base)

        return pd.DataFrame(records)

    return pd.DataFrame([{c.tag: c.text for c in node} for node in nodes])


# ============================================================
# FILE LOADER (CSV, TSV, JSON, JSONL, XML, PARQUET, XLSX)
# ============================================================

def load_file_datasets(
    path: str,
    max_rows: Optional[int] = None,
    only_files: Optional[List[str]] = None
) -> Dict[str, pd.DataFrame]:
    """
    Reads supported files from a local folder and returns a dict: { "<file_name>": DataFrame }
    """
    data: Dict[str, pd.DataFrame] = {}

    if not os.path.isdir(path):
        print("[INFO] Filesystem path not found:", path)
        return data

    files_to_load = os.listdir(path)
    if only_files is not None:
        allowed_set = {f.lower() for f in only_files}
        files_to_load = [f for f in files_to_load if f.lower() in allowed_set]

    for file in files_to_load:
        fp = os.path.join(path, file)
        if not os.path.isfile(fp):
            continue

        try:
            low = file.lower()
            if low.endswith(".csv"):
                data[file] = load_csv_sampled(fp, sep=",", max_rows=max_rows)
            elif low.endswith(".tsv"):
                data[file] = load_csv_sampled(fp, sep="\t", max_rows=max_rows)
            elif low.endswith(".json") or low.endswith(".jsonl"):
                data[file] = _load_json_to_df(fp, max_rows=max_rows)
            elif low.endswith(".xml"):
                data[file] = _xml_to_df_exploded(fp) # XML is harder to sample early
            elif low.endswith(".parquet"):
                # Parquet can be sampled early if we use a different engine, but for now:
                data[file] = pd.read_parquet(fp).head(max_rows) if max_rows else pd.read_parquet(fp)
            elif low.endswith(".xlsx"):
                data[file] = pd.read_excel(fp, engine="openpyxl", nrows=max_rows)
            elif low.endswith(".html") or low.endswith(".htm"):
                tables = pd.read_html(fp)
                data[file] = tables[0] if tables else pd.DataFrame()
        except Exception as e:
            print(f"[ERROR] Reading {file}: {e}")

    return data


# ============================================================
# RELATIONSHIP DETECTION (cardinality + row-level orphan checks)
# ============================================================

def _guess_parent_child_tables(
    n1: str, df1: pd.DataFrame, c1: str,
    n2: str, df2: pd.DataFrame, c2: str,
    meta1: Dict[str, Any], meta2: Dict[str, Any],
) -> Optional[Tuple[str, pd.DataFrame, str, str, pd.DataFrame, str]]:
    """
    Return (parent_ds, parent_df, parent_col, child_ds, child_df, child_col) for FK-style checks, or None.
    """
    nn1 = int(df1[c1].notna().sum())
    nn2 = int(df2[c2].notna().sum())
    if nn1 == 0 or nn2 == 0:
        return None
    u1, u2 = safe_nunique(df1[c1]), safe_nunique(df2[c2])
    r1, r2 = u1 / max(nn1, 1), u2 / max(nn2, 1)

    # Use sampling for large datasets when checking for overlap and cardinality
    if len(df1) > 100_000 or len(df2) > 100_000:
        sample_size = 50_000
        s1 = df1[c1].dropna().sample(min(len(df1[c1].dropna()), sample_size), random_state=42)
        s2 = df2[c2].dropna().sample(min(len(df2[c2].dropna()), sample_size), random_state=42)
        k1 = s1.map(_to_key)
        k2 = s2.map(_to_key)
        try:
            vc1 = k1.value_counts()
            vc2 = k2.value_counts()
            common = vc1.index.intersection(vc2.index)
        except Exception:
            return None
        if len(common) == 0:
            return None
        m1 = int(vc1.reindex(common).fillna(0).max())
        m2 = int(vc2.reindex(common).fillna(0).max())
    else:
        k1 = df1[c1].map(_to_key)
        k2 = df2[c2].map(_to_key)
        try:
            vc1 = k1.dropna().value_counts()
            vc2 = k2.dropna().value_counts()
            common = vc1.index.intersection(vc2.index)
        except Exception:
            return None
        if len(common) == 0:
            return None
        m1 = int(vc1.reindex(common).fillna(0).max())
        m2 = int(vc2.reindex(common).fillna(0).max())

    pk1 = (meta1.get("columns") or {}).get(c1, {}).get("candidate_primary_key")
    pk2 = (meta2.get("columns") or {}).get(c2, {}).get("candidate_primary_key")
    if pk1 and not pk2:
        return (n1, df1, c1, n2, df2, c2)
    if pk2 and not pk1:
        return (n2, df2, c2, n1, df1, c1)
    if r1 >= 0.995 and r2 < 0.97:
        return (n1, df1, c1, n2, df2, c2)
    if r2 >= 0.995 and r1 < 0.97:
        return (n2, df2, c2, n1, df1, c1)
    if m1 == 1 and m2 > 1:
        return (n1, df1, c1, n2, df2, c2)
    if m2 == 1 and m1 > 1:
        return (n2, df2, c2, n1, df1, c1)
    return None


def _classify_cardinality(m1: int, m2: int) -> Tuple[str, str]:
    """
    m1 = max rows per shared key in table A; m2 = max in table B.
    Returns (cardinality_code, human_summary).
    """
    if m1 <= 1 and m2 <= 1:
        return ("one_to_one", "Each key appears at most once in both tables (1:1 on overlapping keys).")
    if m1 <= 1 < m2:
        return ("one_to_many", f"Table A has at most one row per key; table B has up to {m2} rows per key (1:N from A to B).")
    if m2 <= 1 < m1:
        return ("many_to_one", f"Table B has at most one row per key; table A has up to {m1} rows per key (N:1 from A to B).")
    return ("many_to_many", f"Keys repeat on both sides (up to {m1} vs {m2} rows per key) - M:N or bridge-style.")


MAX_REL_ROW_INDEXES = 200


def analyze_cross_dataset_relationships(
    datasets: Dict[str, pd.DataFrame],
    metadata: Dict[str, Any],
    thresholds: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    For each pair of datasets sharing a column name (case-insensitive):
    - overlap count, cardinality (one_to_one / one_to_many / many_to_one / many_to_many)
    - Row-level orphan FK issues (child rows whose key is missing from parent)
    - Warnings for ambiguous M:N on id-like columns
    """
    relationships: List[Dict[str, Any]] = []
    row_issues: List[Dict[str, Any]] = []
    warnings: List[Dict[str, Any]] = []
    thresholds = thresholds or {}
    rel_cfg = thresholds.get("relationships") or {}
    include_non_key = bool(rel_cfg.get("include_non_key_columns", False))
    orphan_only_if_same_data = bool(rel_cfg.get("orphan_only_if_same_dataset", True))
    same_data_min_id_overlap = float(rel_cfg.get("same_dataset_min_id_overlap_ratio", 0.90))
    same_data_max_row_diff = float(rel_cfg.get("same_dataset_max_rowcount_diff_ratio", 0.10))

    def _is_key_like(col_lower: str) -> bool:
        return any(x in col_lower for x in ("_id", "id", "key", "code", "sku"))

    def _same_dataset_representation(df1: pd.DataFrame, df2: pd.DataFrame) -> bool:
        """
        Heuristic guard: only treat datasets as join-compatible for orphan/FK checks when
        they look like different serializations of the SAME records.
        """
        try:
            cols1 = {str(c).strip().lower() for c in df1.columns}
            cols2 = {str(c).strip().lower() for c in df2.columns}
            if cols1 != cols2 or "id" not in cols1:
                return False
            c1 = next(c for c in df1.columns if str(c).lower() == "id")
            c2 = next(c for c in df2.columns if str(c).lower() == "id")
            k1 = set(df1[c1].map(_to_key).dropna().tolist())
            k2 = set(df2[c2].map(_to_key).dropna().tolist())
            if not k1 or not k2:
                return False
            inter = k1 & k2
            overlap_ratio = len(inter) / max(1, min(len(k1), len(k2)))
            r1, r2 = len(df1), len(df2)
            row_diff_ratio = abs(r1 - r2) / max(1, max(r1, r2))
            if not (overlap_ratio >= same_data_min_id_overlap and row_diff_ratio <= same_data_max_row_diff):
                return False

            # Stronger check: do rows actually match on shared IDs?
            # This avoids falsely treating independent sources with same id range as identical datasets.
            inter_list = list(inter)
            if len(inter_list) > 50:
                inter_list = inter_list[:50]
            # prefer email if present, else compare full row signature excluding id
            cols = [c for c in df1.columns if str(c).lower() != "id"]
            if not cols:
                return True
            # Map id -> normalized tuple of values
            def _row_sig(df: pd.DataFrame, id_col: str) -> Dict[Any, Tuple[Any, ...]]:
                out = {}
                for _, row in df.iterrows():
                    ik = _to_key(row[id_col])
                    if ik is None or ik in out:
                        continue
                    out[ik] = tuple(_to_key(row[c]) for c in cols)
                return out
            m1 = _row_sig(df1, c1)
            m2 = _row_sig(df2, c2)
            if not m1 or not m2:
                return False
            matches = 0
            total = 0
            for ik in inter_list:
                if ik in m1 and ik in m2:
                    total += 1
                    if m1[ik] == m2[ik]:
                        matches += 1
            if total == 0:
                return False
            return (matches / total) >= 0.80
        except Exception:
            return False

    names = list(datasets.keys())

    for i in range(len(names)):
        n1, df1 = names[i], datasets[names[i]]
        meta1 = metadata.get(n1, {}) or {}
        for j in range(i + 1, len(names)):
            n2, df2 = names[j], datasets[names[j]]
            meta2 = metadata.get(n2, {}) or {}
            if df1.empty or df2.empty:
                continue
            common = set(map(str.lower, df1.columns)) & set(map(str.lower, df2.columns))
            for col_lower in common:
                if (not include_non_key) and (not _is_key_like(col_lower)):
                    continue
                c1 = next(x for x in df1.columns if str(x).lower() == col_lower)
                c2 = next(x for x in df2.columns if str(x).lower() == col_lower)
                try:
                    k1_full = df1[c1]
                    k2_full = df2[c2]
                    # No sampling, user wants full analysis
                    k1 = k1_full.map(_to_key)
                    k2 = k2_full.map(_to_key)
                    s1k = set(k1.dropna().tolist())
                    s2k = set(k2.dropna().tolist())
                    overlap = s1k & s2k
                except Exception:
                    continue
                if not overlap:
                    continue
                vc1 = k1.dropna().value_counts()
                vc2 = k2.dropna().value_counts()
                common_idx = vc1.index.intersection(vc2.index)
                m1 = int(vc1.reindex(common_idx).fillna(0).max()) if len(common_idx) else 1
                m2 = int(vc2.reindex(common_idx).fillna(0).max()) if len(common_idx) else 1
                card, summary = _classify_cardinality(m1, m2)
                rel = {
                    "from": f"{n1}.{c1}",
                    "to": f"{n2}.{c2}",
                    "dataset_a": n1,
                    "dataset_b": n2,
                    "column_a": c1,
                    "column_b": c2,
                    "overlap_count": len(overlap),
                    "cardinality": card,
                    "max_rows_per_key_a": m1,
                    "max_rows_per_key_b": m2,
                    "summary": summary,
                    "from_a_to_b": (
                        "one_to_many" if m1 <= 1 < m2 else
                        "many_to_one" if m2 <= 1 < m1 else
                        "one_to_one" if m1 <= 1 and m2 <= 1 else
                        "many_to_many"
                    ),
                }
                relationships.append(rel)

                if m1 > 1 and m2 > 1:
                    id_like = any(
                        x in col_lower for x in ("_id", "id", "key", "code", "sku")
                    )
                    sev = "medium" if id_like else "low"
                    warnings.append({
                        "severity": sev,
                        "type": "many_to_many_relationship",
                        "datasets": [n1, n2],
                        "columns": [c1, c2],
                        "message": (
                            f"{n1}.{c1} <-> {n2}.{c2}: keys repeat on both sides "
                            f"(max {m1} rows per key in {n1}, max {m2} in {n2})."
                        ),
                        "recommendation": (
                            "If you expected a parent-child (1:N) model, deduplicate keys on the 'one' side "
                            "or fix source extraction. If M:N is correct (e.g. orders-products), model it with "
                            "a junction table and FK constraints."
                        ),
                    })

                guess = _guess_parent_child_tables(n1, df1, c1, n2, df2, c2, meta1, meta2)
                if guess:
                    _pn, pdf, pc, cn, cdf, cc = guess
                    if orphan_only_if_same_data and not _same_dataset_representation(pdf, cdf):
                        continue
                    try:
                        parent_keys = set(_to_key(x) for x in pdf[pc].dropna())
                    except Exception:
                        parent_keys = set()
                    if not parent_keys:
                        continue
                    ck = cdf[cc].map(lambda x: _to_key(x) if pd.notna(x) else None)
                    orphan = cdf[cc].notna() & ~ck.isin(parent_keys)
                    oc = int(orphan.sum())
                    if oc > 0:
                        oidx = cdf.index[orphan].tolist()[:MAX_REL_ROW_INDEXES]
                        samples = list(cdf.loc[orphan, cc].head(8))
                        row_issues.append({
                            "severity": "high",
                            "type": "orphan_foreign_key_rows",
                            "dataset": cn,
                            "column": cc,
                            "related_dataset": _pn,
                            "related_column": pc,
                            "count": oc,
                            "row_indexes": oidx,
                            "sample_values": samples,
                            "message": (
                                f"{oc} row(s) in '{cn}' column '{cc}' reference value(s) not found in "
                                f"'{_pn}'.'{pc}' (orphan / broken FK)."
                            ),
                            "recommendation": (
                                f"1) Add missing keys to '{_pn}' or remove bad rows from '{cn}'. "
                                f"2) Enforce FK in the source DB or pipeline. "
                                f"3) Trim/normalize keys (whitespace, type) if mismatch is format-only."
                            ),
                        })

    return {
        "relationships": relationships,
        "relationship_row_issues": row_issues,
        "relationship_warnings": warnings,
    }


def detect_relationships(
    datasets: Dict[str, pd.DataFrame],
    metadata: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Returns enriched relationship list (cardinality, summaries)."""
    return analyze_cross_dataset_relationships(datasets, metadata or {})["relationships"]


def analyze_cross_dataset_consistency(
    datasets: Dict[str, pd.DataFrame],
    metadata: Dict[str, Any],
    thresholds: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """
    Cross-dataset insights for data engineers:
    - ID type drift across datasets (e.g., JSON mixed str/int vs CSV int)
    - Likely duplicate representations (same schema + high ID overlap)
    """
    thresholds = thresholds or {}
    out: List[Dict[str, Any]] = []

    # ID type drift
    try:
        id_summaries: Dict[str, Any] = {}
        for name, df in datasets.items():
            id_col = None
            for c in df.columns:
                cl = str(c).lower()
                if cl == "id" or cl.endswith("_id"):
                    id_col = c
                    break
            if id_col is None:
                continue
            td = scalar_type_distribution(df[id_col])
            id_summaries[name] = {"column": str(id_col), "type_distribution": td}

        if len(id_summaries) >= 2:
            def _bucket(td: Dict[str, Any]) -> str:
                pct = (td.get("pct") or {})
                strp = float(pct.get("str", 0.0))
                nump = float(pct.get("int", 0.0)) + float(pct.get("float", 0.0))
                if strp >= 0.10 and nump >= 0.10:
                    return "mixed_str_num"
                if nump >= 0.80:
                    return "mostly_numeric"
                if strp >= 0.80:
                    return "mostly_string"
                return "other"

            buckets = {ds: _bucket(v["type_distribution"]) for ds, v in id_summaries.items()}
            if len(set(buckets.values())) >= 2:
                out.append({
                    "severity": "high",
                    "type": "id_type_drift_across_datasets",
                    "message": "ID column uses inconsistent scalar types across datasets (serialization/type drift).",
                    "details": {"buckets": buckets, "samples": id_summaries},
                })
    except Exception:
        pass

    # Duplicate representation candidates: schema match + high ID overlap
    try:
        dupe_cfg = thresholds.get("duplicate_detection") or {}
        min_overlap = float(dupe_cfg.get("min_id_overlap_ratio", 0.95))
        max_row_diff = float(dupe_cfg.get("max_rowcount_diff_ratio", 0.05))

        def _schema_sig(df: pd.DataFrame) -> Tuple[str, ...]:
            return tuple(sorted({str(c).strip().lower() for c in df.columns}))

        groups: Dict[Tuple[str, ...], List[str]] = {}
        for name, df in datasets.items():
            groups.setdefault(_schema_sig(df), []).append(name)

        for sig, names in groups.items():
            if len(names) < 2 or len(sig) == 0:
                continue
            for i in range(len(names)):
                for j in range(i + 1, len(names)):
                    a, b = names[i], names[j]
                    dfa, dfb = datasets[a], datasets[b]
                    if "id" not in [str(c).lower() for c in dfa.columns] or "id" not in [str(c).lower() for c in dfb.columns]:
                        continue
                    ca = next(c for c in dfa.columns if str(c).lower() == "id")
                    cb = next(c for c in dfb.columns if str(c).lower() == "id")
                    inter = set()
                    # Sampling for large datasets in duplicate representation check
                    if len(dfa) > 100_000 or len(dfb) > 100_000:
                        sample_a = dfa[ca].dropna().sample(min(len(dfa), 50_000), random_state=42).map(_to_key)
                        sample_b = dfb[cb].dropna().sample(min(len(dfb), 50_000), random_state=42).map(_to_key)
                        ka = set(sample_a.tolist())
                        kb = set(sample_b.tolist())
                    else:
                        ka = set(dfa[ca].map(_to_key).dropna().tolist())
                        kb = set(dfb[cb].map(_to_key).dropna().tolist())
                    
                    if not ka or not kb:
                        continue
                    inter = ka & kb
                    overlap_ratio = len(inter) / max(1, min(len(ka), len(kb)))
                    ra, rb = len(dfa), len(dfb)
                    row_diff_ratio = abs(ra - rb) / max(1, max(ra, rb))
                    if overlap_ratio >= min_overlap and row_diff_ratio <= max_row_diff:
                        out.append({
                            "severity": "medium",
                            "type": "duplicate_representation_candidate",
                            "message": f"Datasets '{a}' and '{b}' likely represent the same records in different formats.",
                            "details": {
                                "schema_columns": list(sig)[:30],
                                "id_overlap_ratio": round(overlap_ratio, 4),
                                "id_overlap_count": len(inter),
                                "row_counts": {a: ra, b: rb},
                            },
                        })
    except Exception:
        pass

    # Enrich recommendations
    for it in out:
        enrich_issue_with_recommendation(it)
    return out


def build_executive_summary_items(
    per_dataset_dq: Dict[str, Any],
    global_issues: Dict[str, Any],
    thresholds: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """
    Business-first summary: rank the most impactful signals into a small list.
    Uses a lightweight scoring model (severity * datasets affected).
    """
    thresholds = thresholds or {}
    cfg = thresholds.get("executive_summary") or {}
    max_items = int(cfg.get("max_items", 8))
    sev_w = {"high": 3.0, "medium": 2.0, "low": 1.0}

    rollup: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for ds, block in (per_dataset_dq or {}).items():
        issues = (block or {}).get("issues") or []
        for it in issues:
            typ = str(it.get("type") or "")
            col = str(it.get("column") or "")
            key = (typ, col)
            r = rollup.setdefault(key, {"type": typ, "column": col, "datasets": set(), "sev_max": "low", "rows": 0})
            r["datasets"].add(ds)
            r["rows"] += int(it.get("count") or 0)
            if sev_w.get(str(it.get("severity") or "low"), 1) > sev_w.get(r["sev_max"], 1):
                r["sev_max"] = str(it.get("severity") or "low")

    # add cross-dataset consistency signals
    for it in (global_issues.get("cross_dataset_consistency") or []):
        if not isinstance(it, dict):
            continue
        key = (str(it.get("type") or ""), "")
        r = rollup.setdefault(key, {"type": key[0], "column": "", "datasets": set(), "sev_max": "low", "rows": 0})
        if sev_w.get(str(it.get("severity") or "low"), 1) > sev_w.get(r["sev_max"], 1):
            r["sev_max"] = str(it.get("severity") or "low")

    ranked = []
    for r in rollup.values():
        ds_count = len(r["datasets"]) if r["datasets"] else 1
        score = sev_w.get(r["sev_max"], 1.0) * (1.0 + min(3.0, ds_count / 2.0))
        ranked.append({**r, "datasets_affected": ds_count, "score": float(score)})
    ranked.sort(key=lambda x: (-x.get("score", 0.0), -x.get("datasets_affected", 0), -x.get("rows", 0)))

    items = []
    for x in ranked[:max_items]:
        items.append({
            "title": x["type"] + (f" ({x['column']})" if x.get("column") else ""),
            "severity": x.get("sev_max"),
            "datasets_affected": x.get("datasets_affected"),
            "estimated_rows_affected": x.get("rows"),
            "recommendation": DQ_ISSUE_RECOMMENDATIONS.get(x["type"], _DEFAULT_REC),
        })
    return items


# ============================================================
# DATA QUALITY CHECKS (with row indexes, config-driven thresholds)
# ============================================================

PLACEHOLDERS = {
    "", " ", "-", "--", "---", "n/a", "na", "none", "null", "nil",
    "unknown", "not available", "missing", "undefined", "not applicable",
    "tbd", "tba", "n.a.", "n.a", "#n/a", "#null!", "#value!", "#ref!",
    "#div/0!", "error", "nan", "inf", "-inf", "0000-00-00", "1900-01-01",
    "9999-12-31", "00", "000", "0000", "?", "??", "???", "!",
    "temp", "test", "dummy", "placeholder", "na.", "na,", "not set",
    "unknown unknown", "n.d.", "nd", "not known",
}
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]*\.[^@\s]+$")
PHONE_RE = re.compile(r"^[+()\-\.\s0-9]{7,}$")
URL_RE = re.compile(
    r"^(https?://|ftp://|www\.)[^\s/$.?#][^\s]*$",
    re.IGNORECASE,
)
INVALID_URL_RE = re.compile(
    r"^(https?://|ftp://|www\.).*",
    re.IGNORECASE,
)
HTML_TAG_RE = re.compile(r"<[a-zA-Z][^>]*>|</[a-zA-Z]+>")
UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
PUNCTUATION_ONLY_RE = re.compile(r"^[\W_]+$")
LEADING_ZERO_RE = re.compile(r"^0[0-9]+$")
MULTI_SPACE_RE = re.compile(r"  +")  # two or more consecutive spaces

_UUID_RE = re.compile(
    r'^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$'
)
_URL_RE = re.compile(r'^https?://', re.IGNORECASE)
_IP4_RE = re.compile(r'^\d{1,3}(?:\.\d{1,3}){3}$')
_IP6_RE = re.compile(r'^[0-9a-fA-F:]{7,39}$')
_BOOL_VALS = frozenset({"true","false","yes","no","y","n","1","0","t","f","on","off"})
_PHONE_NAME_HINTS = frozenset({
    "phone","mobile","contact","tel","cell","fax",
    "whatsapp","landline","ph_no","phno","phone_no",
    "telephone","phn","mob","cellphone","handphone"
})
SENTINEL_NUMBERS = {
    -999, -9999, -99999, -999999, -9999999,
    999, 9999, 99999, 999999, 9999999,
    -1, -99, -100, -1000,
    0.0, -0.0,
    1111, 1234, 12345, 123456, 1234567,
    9876, 98765, 9876543,
    11111, 22222, 33333, 44444, 55555, 66666, 77777, 88888,
}
BOOL_VARIANTS: Dict[str, set] = {
    "true_false": {"true", "false"},
    "yes_no": {"yes", "no"},
    "y_n": {"y", "n"},
    "1_0": {"1", "0"},
    "on_off": {"on", "off"},
    "active_inactive": {"active", "inactive"},
    "enabled_disabled": {"enabled", "disabled"},
}

_DEFAULT_REC = (
    "Review with domain owners; document the expected rule; add validation at ingest or in the warehouse."
)
DQ_ISSUE_RECOMMENDATIONS: Dict[str, str] = {
    "nulls": "Map source placeholders to NULL; fix upstream capture; use defaults only where business-approved.",
    "whitespace": "Trim strings in ETL (e.g. TRIM in SQL, str.strip in pandas) before load or constraint checks.",
    "invalid_email": "Reject or quarantine bad emails; validate with regex or a mailbox API at entry.",
    "invalid_phone": "Normalize to E.164 or national format; strip junk characters in staging.",
    "invalid_date_format": "Standardize to ISO-8601 in pipeline; use robust parse with explicit format/locale.",
    "invalid_numeric": "Coerce after trim; fix type in source; quarantine non-numeric rows for manual fix.",
    "negative_values": "Clip to zero if business allows, or flag rows; verify sign convention in source.",
    "suspicious_zero": "Treat 0 as missing if appropriate, or validate IDs never zero at source.",
    "mixed_types": "Cast column to single type in ETL; split into two columns if genuinely mixed semantics.",
    "nested_structure": "Flatten JSON/XML to scalar columns or child tables before relational load.",
    "duplicate_rows": "Deduplicate on business key (keep latest by timestamp); add uniqueness constraint.",
    "duplicate_primary_key": "Resolve duplicates before load; enforce PRIMARY KEY in database.",
    "potential_primary_key": "Promote column to natural key in modeling docs; add UNIQUE constraint if stable.",
    "empty_dataset": "Verify extract scope and filters; re-run load or fix source path.",
    "duplicate_column_names": "Rename duplicate columns in extract; use explicit aliases in SQL SELECT.",
    "case_insensitive_column_collision": "Rename to a single convention (snake_case); avoid Windows/Excel collisions.",
    "very_wide_table": "Split wide tables by domain or normalize repeating groups.",
    "column_name_whitespace": "Rename columns to strip/replace spaces for SQL compatibility.",
    "date_range_violation": "Swap dates if reversed by mistake; invalidate rows that violate business window.",
    "constant_column": "Drop column if no variance, or fix extract if value should vary.",
    "dominant_value_skew": "Investigate default/fill behavior; segment by dimensions to see real spread.",
    "very_high_cardinality": "Confirm not free-text in ID column; consider hashing or surrogate keys for privacy.",
    "binary_like_column": "Encode as boolean 0/1; document semantics for both values.",
    "numeric_outliers_iqr": "Winsorize, cap, or investigate fraud/measurement errors; document exclusion rules.",
    "skewed_distribution": "Apply log transform for analytics or stratify reporting; check for contamination.",
    "integer_stored_as_float": "Cast to integer type (Int64 nullable) to avoid float drift.",
    "future_dates": "Correct clock skew or data entry; set max date validation at source.",
    "ancient_dates": "Fix century typos or replace sentinel dates with NULL.",
    "very_wide_date_span": "Split historical vs operational feeds if span is implausible for one entity.",
    "extremely_long_strings": "Truncate with audit trail, or move large text to blob/document store.",
    "empty_string_values": "Normalize empty string to NULL for consistent SQL semantics.",
    "control_characters_in_text": "Strip non-printable chars in ETL; fix export encoding (UTF-8).",
    "mixed_scalar_types": "Standardize to a single scalar type in ETL (e.g. cast all IDs to string or integer) and enforce it at ingest.",
    "case_inconsistency": "Normalize case in ETL (e.g. UPPER/LOWER) and consider adding a canonical mapping table for display.",
    "name_format_inconsistency": "Normalize name presentation (trim, collapse spaces, title-case) in staging; preserve raw in an audit column if needed.",
    "mixed_phone_formats": "Normalize phones to a single canonical format (prefer E.164) and validate length/country rules at capture time.",
    "systematic_placeholder": "Investigate upstream defaults; replace placeholders with NULL and enforce domain constraints at source.",
    "out_of_range": "Clip/correct out-of-range values or quarantine rows; confirm expected business bounds with domain owners.",
    "id_type_drift_across_datasets": "Align serialization across formats: IDs should use a consistent type (string or integer) across JSON/CSV/XML exports.",
    "duplicate_representation_candidate": "These datasets likely represent the same entities in different formats; avoid double-counting and choose a system-of-record.",
    "custom_one_of": "Map invalid values to allowed enum or reject rows per data contract.",
    "custom_range": "Clip to bounds or reject; align with business limits.",
    "custom_regex": "Fix format at source or apply regex replace in staging.",
    "custom_not_null": "Backfill from upstream or drop incomplete rows per policy.",
    # --- NEW CHECKS ---
    "invalid_url": "Validate URL format at entry; normalize with urllib.parse; reject structurally invalid URLs.",
    "html_tags_in_text": "Strip HTML/XML tags with BeautifulSoup or regex before storing in a plain-text column.",
    "punctuation_only_value": "Replace symbol-only strings with NULL; investigate upstream export bugs.",
    "sentinel_numeric_value": "Replace sentinel values (-999, 9999999, etc.) with NULL; enforce domain constraints at source.",
    "boolean_inconsistency": "Standardize to a single boolean representation (True/False or 1/0) across the pipeline.",
    "internal_whitespace": "Collapse consecutive spaces with REGEXP_REPLACE or str.strip in ETL.",
    "non_ascii_characters": "Normalize to UTF-8; strip or transliterate unexpected non-ASCII if column is meant to be ASCII.",
    "invalid_uuid": "Enforce UUID v4 format at source; regenerate malformed UUIDs.",
    "leading_zeros_on_numeric_id": "Store leading-zero IDs as VARCHAR/TEXT to prevent data loss on integer cast.",
    "numeric_outliers_zscore": "Investigate extreme z-score outliers (>4 std devs); likely data entry errors, test records, or fraud signals.",
    "round_number_anomaly": "Suspiciously round numbers may indicate estimates or placeholders; validate exact source values.",
    "date_clumping_jan1": "Dates clustering on Jan 1 often indicate default/dummy dates; replace with actual dates or NULL.",
    "date_clumping_month_end": "Dates clustering on month-end may indicate estimated or rolled-up dates; verify with source.",
    "all_caps_values": "Inconsistent all-caps entries may indicate data entry from legacy systems; normalize case in ETL.",
    "string_length_outlier": "Strings significantly longer than the column average may contain concatenated data or free-text errors.",
    "numeric_precision_anomaly": "Mixing integers with high-precision floats suggests inconsistent data capture; standardize precision.",
    "impossible_date": "Dates like 2000-02-30 or 2001-13-01 are structurally invalid; fix upstream date parsing.",
    "weekend_date_anomaly": "Business transactions on weekends may be legitimate or may indicate date errors; verify with domain.",
    "duplicate_insensitive_values": "Values that differ only by case/whitespace produce false uniqueness; deduplicate after normalization.",
    "low_variance_numeric": "Near-constant numeric column may indicate fill/default behavior rather than real data.",
    "high_null_ratio_in_key_column": "Key or ID columns with high null rates cannot reliably join; backfill or reject at ingest.",
    "mixed_date_formats": "Multiple date formats in the same column (e.g. DD/MM/YYYY vs YYYY-MM-DD) cause silent parse errors.",
    "implausible_age": "Age values outside the range 0-150 are likely data entry errors; validate at source.",
    "implausible_percentage": "Percentage values outside 0-100 are structurally invalid; add range constraint at ingest.",
    "timezone_inconsistency": "Datetime values mixing timezone-aware and timezone-naive records cause comparison errors.",
    "string_with_only_digits_in_text_column": "Text columns containing only digits may indicate a schema mismatch or misrouted data.",
    "repeated_token_in_string": "Values with repeated words/tokens (e.g. 'test test') often indicate data entry errors.",
    "near_duplicate_rows": "Rows that are identical except for one or two fields may be erroneous duplicates; deduplicate or merge.",
}


def enrich_issue_with_recommendation(issue: Dict[str, Any]) -> None:
    if issue.get("recommendation"):
        return
    issue["recommendation"] = DQ_ISSUE_RECOMMENDATIONS.get(
        issue.get("type") or "", _DEFAULT_REC
    )


FIXABILITY_BY_ISSUE_TYPE: Dict[str, str] = {
    # deterministic transforms
    "whitespace": "FIXABLE",
    "empty_string_values": "FIXABLE",
    "case_inconsistency": "FIXABLE",
    "mixed_scalar_types": "FIXABLE",
    "integer_stored_as_float": "FIXABLE",
    "control_characters_in_text": "FIXABLE",
    "nested_structure": "FIXABLE",
    "internal_whitespace": "FIXABLE",
    "non_ascii_characters": "FIXABLE",
    "html_tags_in_text": "FIXABLE",
    "boolean_inconsistency": "FIXABLE",
    "all_caps_values": "FIXABLE",
    "duplicate_insensitive_values": "FIXABLE",
    "id_type_drift_across_datasets": "FIXABLE",
    # complex / requires domain decision
    "invalid_email": "NOT_FIXABLE",
    "invalid_phone": "COMPLEX",
    "mixed_phone_formats": "COMPLEX",
    "invalid_numeric": "COMPLEX",
    "mixed_types": "COMPLEX",
    "negative_values": "COMPLEX",
    "out_of_range": "COMPLEX",
    "numeric_outliers_iqr": "COMPLEX",
    "numeric_outliers_zscore": "COMPLEX",
    "dominant_value_skew": "COMPLEX",
    "name_format_inconsistency": "COMPLEX",
    "systematic_placeholder": "COMPLEX",
    "sentinel_numeric_value": "COMPLEX",
    "punctuation_only_value": "COMPLEX",
    "round_number_anomaly": "COMPLEX",
    "date_clumping_jan1": "COMPLEX",
    "date_clumping_month_end": "COMPLEX",
    "invalid_url": "COMPLEX",
    "leading_zeros_on_numeric_id": "COMPLEX",
    "string_length_outlier": "COMPLEX",
    "numeric_precision_anomaly": "COMPLEX",
    "impossible_date": "COMPLEX",
    "weekend_date_anomaly": "COMPLEX",
    "mixed_date_formats": "COMPLEX",
    "implausible_age": "COMPLEX",
    "implausible_percentage": "COMPLEX",
    "string_with_only_digits_in_text_column": "COMPLEX",
    "repeated_token_in_string": "COMPLEX",
    "near_duplicate_rows": "COMPLEX",
    "low_variance_numeric": "COMPLEX",
    "timezone_inconsistency": "COMPLEX",
    # cannot be auto-repaired without authoritative source
    "duplicate_primary_key": "NOT_FIXABLE",
    "duplicate_rows": "COMPLEX",
    "orphan_foreign_key_rows": "NOT_FIXABLE",
    "orphan_foreign_key": "NOT_FIXABLE",
    "invalid_uuid": "NOT_FIXABLE",
    "impossible_date": "NOT_FIXABLE",
    "high_null_ratio_in_key_column": "NOT_FIXABLE",
    "duplicate_representation_candidate": "COMPLEX",
}


def enrich_issue_with_fixability(issue: Dict[str, Any]) -> None:
    if issue.get("fixability"):
        return
    issue["fixability"] = FIXABILITY_BY_ISSUE_TYPE.get(issue.get("type") or "", "COMPLEX")


def dq_issue(
    sev: str,
    typ: str,
    msg: str,
    *,
    column: Optional[str] = None,
    count: Optional[int] = None,
    rows: Optional[List[int]] = None,
    sample: Optional[List[Any]] = None
) -> Dict[str, Any]:
    """
    Create a normalized DQ issue record.
    - severity: "low" | "medium" | "high"
    - row_indexes: list of 0-based indexes (capped to 50)
    - sample_values: capped to 10
    """
    return {
        "severity": sev,
        "type": typ,
        "column": column,
        "count": count,
        "row_indexes": rows[:50] if rows else [],
        "sample_values": sample[:10] if sample else [],
        "message": msg,
        "fixability": FIXABILITY_BY_ISSUE_TYPE.get(typ, "COMPLEX"),
    }


def make_json_serializable(obj: Any) -> Any:
    """Recursively convert datetime/Timestamp/System.DateTime/numpy types to JSON-safe types."""
    import pandas as pd
    import json
    
    if isinstance(obj, dict):
        return {str(k): make_json_serializable(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [make_json_serializable(v) for v in obj]
    elif isinstance(obj, tuple):
        return tuple(make_json_serializable(v) for v in obj)
    elif isinstance(obj, set):
        return {make_json_serializable(v) for v in obj}
    
    if not isinstance(obj, (dict, list, tuple, set)):
        if pd.isna(obj):
            return None
            
    if hasattr(obj, "isoformat"):
        return obj.isoformat()
        
    tname = type(obj).__name__
    if tname in ("DateTime", "Timestamp", "datetime", "date"):
        try:
            return str(obj.ToString() if hasattr(obj, "ToString") else obj)
        except Exception:
            return str(obj)
            
    if hasattr(obj, "item") and callable(obj.item):
        try:
            return obj.item()
        except Exception:
            return str(obj)
            
    try:
        json.dumps(obj)
        return obj
    except Exception:
        return str(obj)


def analyze_column(
    series: pd.Series,
    col: str,
    semantic: str,
    thresholds: Optional[Dict[str, Any]] = None,
    is_priority: bool = True,
    non_nullable: Optional[set[str]] = None,
) -> List[Dict[str, Any]]:
    """
    Per-column data quality checks using Great Expectations core engine.
    """
    df = pd.DataFrame({col: series})
    profile = {
        "columns": {
            col: {"semantic_type": semantic}
        }
    }
    if is_priority:
        profile["priority_columns"] = [col]
    else:
        profile["priority_columns"] = []
        
    business_rules = {}
    if non_nullable:
        business_rules["non_nullable"] = list(non_nullable)
        
    res = analyze_dataset_quality(
        name="temp_dataset",
        df=df,
        profile=profile,
        thresholds=thresholds,
        business_rules=business_rules
    )
    return make_json_serializable(res.get("issues") or [])


def analyze_dataset_quality(
    name: str,
    df: pd.DataFrame,
    profile: Dict[str, Any],
    thresholds: Optional[Dict[str, Any]] = None,
    job_id: Optional[str] = None,
    business_rules: Optional[Dict[str, Any]] = None,
    approved_semantics: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """
    Validation engine powered by Great Expectations.
    Runs validations using GX and translates the failed expectations to the unified issues format.
    """
    from agent.specialists.gx_validation_specialist import run_gx_validation
    
    thresholds = thresholds or {}
    business_rules = business_rules or {}
    issues: List[Dict[str, Any]] = []
    n = len(df)
    
    # 1. Run Great Expectations validation
    try:
        gx_res = run_gx_validation(
            datasets={name: df},
            profile_results={"datasets": {name: profile}},
            thresholds=thresholds,
            business_rules=business_rules
        )
    except Exception as e:
        logger.error(f"GX Validation call failed for {name}: {e}")
        gx_res = {}
        
    ds_res = gx_res.get(name) or {}
    results = ds_res.get("results") or []
    
    # Non-nullable set for severity mapping
    non_nullable_set = set()
    nn_list = business_rules.get("non_nullable") or []
    req_list = business_rules.get("required_columns") or []
    for c in nn_list:
        non_nullable_set.add(str(c).lower())
    for c in req_list:
        non_nullable_set.add(str(c).lower())
    for col_name, col_meta in profile.get("columns", {}).items():
        if col_meta.get("nullable") == "NO" or col_meta.get("candidate_primary_key") is True:
            non_nullable_set.add(str(col_name).lower())
            
    # Map failed results to legacy DQ issues
    for r in results:
        if r.get("success"):
            continue
            
        col = r.get("column") or "-"
        exp = str(r.get("expectation") or "").lower()
        unexp_cnt = int(r.get("unexpected_count") or 0)
        unexp_idx = r.get("unexpected_index_list") or []
        unexp_vals = r.get("unexpected_values") or []
        details = r.get("details") or ""
        
        # Heuristically determine severity and issue type
        severity = "medium"
        issue_type = "custom_rule_violation"
        msg = f"{col}: expectation failed."
        
        if "not be null" in exp or "placeholder_detected" in exp:
            issue_type = "nulls"
            severity = "high" if str(col).lower() in non_nullable_set else "low"
            msg = f"{unexp_cnt} null/placeholder" if unexp_cnt > 0 else "Null or placeholder value(s) found"
        elif "be unique" in exp:
            issue_type = "duplicate_primary_key"
            severity = "high"
            msg = f"{unexp_cnt} duplicate in candidate PK" if unexp_cnt > 0 else "Duplicate key values found"
        elif "compound columns to be unique" in exp or "compound_columns_to_be_unique" in exp:
            issue_type = "duplicate_rows"
            severity = "medium"
            msg = f"{unexp_cnt} duplicate row(s)" if unexp_cnt > 0 else "Duplicate rows found"
        elif "be in type list" in exp or "be of type" in exp:
            issue_type = "invalid_numeric"
            severity = "medium"
            msg = f"{unexp_cnt} non-numeric value(s)" if unexp_cnt > 0 else "Type mismatch"
        elif exp == "internal_whitespace":
            issue_type = "internal_whitespace"
            severity = "low"
            msg = f"{unexp_cnt} value(s) with consecutive spaces"
        elif "whitespace" in exp:
            issue_type = "whitespace"
            severity = "low"
            msg = f"{unexp_cnt} leading/trailing spaces"
        elif exp == "html_tags_in_text":
            issue_type = "html_tags_in_text"
            severity = "medium"
            msg = f"{unexp_cnt} value(s) containing HTML tags"
        elif exp == "punctuation_only_value":
            issue_type = "punctuation_only_value"
            severity = "medium"
            msg = f"{unexp_cnt} punctuation-only value(s)"
        elif exp == "invalid_email":
            issue_type = "invalid_email"
            severity = "medium"
            msg = f"{unexp_cnt} invalid email(s)"
        elif exp == "invalid_phone":
            issue_type = "invalid_phone"
            severity = "medium"
            msg = f"{unexp_cnt} invalid phone number(s)"
        elif exp == "invalid_uuid":
            issue_type = "invalid_uuid"
            severity = "high"
            msg = f"{unexp_cnt} value(s) do not match UUID format"
        elif "match regex" in exp or "match_regex" in exp:
            if "email" in exp:
                issue_type = "invalid_email"
                severity = "medium"
                msg = f"{unexp_cnt} invalid email(s)"
            elif "phone" in exp:
                issue_type = "invalid_phone"
                severity = "medium"
                msg = f"{unexp_cnt} invalid phone number(s)"
            elif "uuid" in exp:
                issue_type = "invalid_uuid"
                severity = "high"
                msg = f"{unexp_cnt} value(s) do not match UUID format"
            elif "url" in exp or (col and "url" in str(col).lower()):
                issue_type = "invalid_url"
                severity = "medium"
                msg = f"{unexp_cnt} structurally invalid URL(s)"
            else:
                issue_type = "custom_regex"
                severity = "medium"
                msg = f"{unexp_cnt} value(s) failed regex check"
        elif "dateutil parseable" in exp:
            issue_type = "invalid_date_format"
            severity = "medium"
            msg = f"{unexp_cnt} bad date(s) (failed parsing)"
        elif exp == "negative_values":
            issue_type = "negative_values"
            severity = "medium"
            msg = f"{unexp_cnt} negative value(s)"
        elif "be between" in exp:
            if "age" in str(col).lower():
                issue_type = "implausible_age"
                severity = "high"
                msg = f"{unexp_cnt} age value(s) outside range 0-150"
            elif any(k in str(col).lower() for k in ("percent", "pct", "rate", "ratio", "share")):
                issue_type = "implausible_percentage"
                severity = "medium"
                msg = f"{unexp_cnt} value(s) outside expected 0-100% range"
            else:
                issue_type = "out_of_range"
                severity = "medium"
                msg = f"{unexp_cnt} value(s) outside expected range"
        elif exp == "suspicious_zero":
            issue_type = "suspicious_zero"
            severity = "medium"
            msg = f"{unexp_cnt} suspicious zero(s) in ID column"
        elif "not be in set" in exp or exp == "sentinel_numeric_value":
            issue_type = "sentinel_numeric_value"
            severity = "medium"
            msg = details or f"{unexp_cnt} sentinel/magic number(s) detected"
        elif exp == "conditional_not_null":
            issue_type = "conditional_not_null"
            severity = "medium"
            msg = details
        elif exp == "conditional_range":
            issue_type = "conditional_range"
            severity = "medium"
            msg = details
        elif exp == "formula_rule_violation":
            issue_type = "formula_rule_violation"
            severity = "medium"
            msg = details
        elif exp == "date_range_violation":
            issue_type = "date_range_violation"
            severity = "high"
            msg = details
        elif exp == "invalid_lookup_value":
            issue_type = "invalid_lookup_value"
            severity = "medium"
            msg = details
        elif exp == "near_duplicate_rows":
            issue_type = "near_duplicate_rows"
            severity = "medium"
            msg = details
        elif exp == "intra_dataset_orphan_fk":
            issue_type = "intra_dataset_orphan_fk"
            severity = "high"
            msg = details
        elif exp == "multivariate_outliers":
            issue_type = "multivariate_outliers"
            severity = "medium"
            msg = details
        elif exp == "functional_dependency_violation":
            issue_type = "functional_dependency_violation"
            severity = "medium"
            msg = details
        elif exp == "mixed_date_formats":
            issue_type = "mixed_date_formats"
            severity = "medium"
            msg = details
        elif exp == "all_caps_values":
            issue_type = "all_caps_values"
            severity = "low"
            msg = details
        elif exp == "duplicate_uuid":
            issue_type = "duplicate_uuid"
            severity = "high"
            msg = details
        elif exp == "ambiguous_boolean":
            issue_type = "ambiguous_boolean"
            severity = "medium"
            msg = details
        elif exp == "custom_rule_violation":
            issue_type = "custom_rule_violation"
            severity = "medium"
            msg = details
            
        issues.append({
            "severity": severity,
            "type": issue_type,
            "column": col,
            "count": unexp_cnt,
            "row_indexes": unexp_idx[:50],
            "sample_values": unexp_vals[:10],
            "message": msg,
            "fixability": FIXABILITY_BY_ISSUE_TYPE.get(issue_type, "COMPLEX")
        })
        
    # Calculate Scorecard Summary Metrics
    try:
        score_cfg = thresholds.get("dq_score") or {}
        w = score_cfg.get("weights") or {}
        wh = float(w.get("high", 3.0))
        wm = float(w.get("medium", 1.0))
        wl = float(w.get("low", 0.3))
        sev_w = {"high": wh, "medium": wm, "low": wl}

        high_rows, med_rows, low_rows = set(), set(), set()
        for it in issues:
            sev = str(it.get("severity") or "low").lower()
            rows = it.get("row_indexes") or []
            if rows:
                if sev == "high":
                    high_rows.update(rows)
                elif sev == "medium":
                    med_rows.update(rows)
                else:
                    low_rows.update(rows)

        med_rows = set(med_rows) - set(high_rows)
        low_rows = set(low_rows) - set(high_rows) - set(med_rows)

        frac_h = len(high_rows) / max(1, n)
        frac_m = len(med_rows) / max(1, n)
        frac_l = len(low_rows) / max(1, n)

        raw_penalty = (sev_w["high"] * frac_h) + (sev_w["medium"] * frac_m) + (sev_w["low"] * frac_l)
        max_penalty = sev_w["high"] + sev_w["medium"] + sev_w["low"]
        dq_score = 100.0 * max(0.0, 1.0 - (raw_penalty / max(1e-9, max_penalty)))

        clean_est_high = max(0, n - len(high_rows))
        clean_est_high_med = max(0, n - len(high_rows.union(med_rows)))
    except Exception:
        dq_score = None
        clean_est_high = None
        clean_est_high_med = None

    return make_json_serializable({
        "issues": issues,
        "summary": {
            "issue_count": len(issues),
            "high_severity": sum(1 for i in issues if i["severity"] == "high"),
            "medium_severity": sum(1 for i in issues if i["severity"] == "medium"),
            "low_severity": sum(1 for i in issues if i["severity"] == "low"),
            "dq_score_0_100": dq_score,
            "estimated_clean_rows_after_high": clean_est_high,
            "estimated_clean_rows_after_high_and_medium": clean_est_high_med,
        }
    })


def detect_global_issues(datasets: Dict[str, pd.DataFrame], thresholds: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    - Orphan foreign keys: values present in one dataset.column but not in the counterpart
    - Cross-dataset inconsistencies: coarse mixed numeric/text indicator per column by parse-rate
    """
    thresholds = thresholds or {}
    rel_cfg = thresholds.get("relationships") or {}
    orphan_only_if_same_data = bool(rel_cfg.get("orphan_only_if_same_dataset", True))
    same_data_min_id_overlap = float(rel_cfg.get("same_dataset_min_id_overlap_ratio", 0.90))
    same_data_max_row_diff = float(rel_cfg.get("same_dataset_max_rowcount_diff_ratio", 0.10))

    def _same_dataset_representation(df1: pd.DataFrame, df2: pd.DataFrame) -> bool:
        try:
            cols1 = {str(c).strip().lower() for c in df1.columns}
            cols2 = {str(c).strip().lower() for c in df2.columns}
            if cols1 != cols2 or "id" not in cols1:
                return False
            c1 = next(c for c in df1.columns if str(c).lower() == "id")
            c2 = next(c for c in df2.columns if str(c).lower() == "id")
            k1 = set(df1[c1].map(_to_key).dropna().tolist())
            k2 = set(df2[c2].map(_to_key).dropna().tolist())
            if not k1 or not k2:
                return False
            inter = k1 & k2
            overlap_ratio = len(inter) / max(1, min(len(k1), len(k2)))
            r1, r2 = len(df1), len(df2)
            row_diff_ratio = abs(r1 - r2) / max(1, max(r1, r2))
            if not (overlap_ratio >= same_data_min_id_overlap and row_diff_ratio <= same_data_max_row_diff):
                return False

            # Stronger check: do rows actually match on shared IDs?
            inter_list = list(inter)
            if len(inter_list) > 50:
                inter_list = inter_list[:50]
            cols = [c for c in df1.columns if str(c).lower() != "id"]
            if not cols:
                return True

            def _row_sig(df: pd.DataFrame, id_col: str) -> Dict[Any, Tuple[Any, ...]]:
                out = {}
                for _, row in df.iterrows():
                    ik = _to_key(row[id_col])
                    if ik is None or ik in out:
                        continue
                    out[ik] = tuple(_to_key(row[c]) for c in cols)
                return out

            m1 = _row_sig(df1, c1)
            m2 = _row_sig(df2, c2)
            if not m1 or not m2:
                return False
            matches = 0
            total = 0
            for ik in inter_list:
                if ik in m1 and ik in m2:
                    total += 1
                    if m1[ik] == m2[ik]:
                        matches += 1
            if total == 0:
                return False
            return (matches / total) >= 0.80
        except Exception:
            return False

    global_issues = {
        "orphan_foreign_keys": [],
        "cross_dataset_inconsistencies": [],
        "schema_drift": []
    }

    names = list(datasets.keys())
    for i in range(len(names)):
        df1 = datasets[names[i]]
        for j in range(i + 1, len(names)):
            df2 = datasets[names[j]]
            same_data = _same_dataset_representation(df1, df2)

            common = set(map(str.lower, df1.columns)) & set(map(str.lower, df2.columns))
            for col in common:
                if not col.endswith("id"):
                    continue
                c1 = next(x for x in df1.columns if x.lower() == col)
                c2 = next(x for x in df2.columns if x.lower() == col)

                s1 = df1[c1].dropna()
                s2 = df2[c2].dropna()

                try:
                    set1 = set(s1.map(_to_key).dropna())
                    set2 = set(s2.map(_to_key).dropna())
                except Exception:
                    continue

                only_left = list(set1 - set2)
                only_right = list(set2 - set1)

                _orph_rec = (
                    "Align keys between datasets (trim, type cast). Add missing reference rows or remove "
                    "orphan facts in the child extract. Prefer FK constraints in the source system."
                )
                if (not orphan_only_if_same_data) or same_data:
                    if only_left:
                        global_issues["orphan_foreign_keys"].append({
                            "from": f"{names[i]}.{c1}",
                            "to": f"{names[j]}.{c2}",
                            "orphan_count": len(only_left),
                            "sample_values": only_left[:10],
                            "recommendation": _orph_rec,
                        })
                    if only_right:
                        global_issues["orphan_foreign_keys"].append({
                            "from": f"{names[j]}.{c2}",
                            "to": f"{names[i]}.{c1}",
                            "orphan_count": len(only_right),
                            "sample_values": only_right[:10],
                            "recommendation": _orph_rec,
                        })

            for nm, df in ((names[i], df1), (names[j], df2)):
                for col in df.columns:
                    s = df[col].map(_strip)
                    num = pd.to_numeric(s, errors="coerce")
                    parse_rate = 1.0 - float(num.isna().mean())
                    if 0.2 < parse_rate < 0.8:
                        global_issues["cross_dataset_inconsistencies"].append({
                            "dataset": nm,
                            "column": col,
                            "issue_type": "mixed_types",
                            "message": f"Mixed numeric/text values (parse={round(parse_rate*100,1)}%)",
                            "recommendation": (
                                "Standardize to one type in staging: coerce numerics after validation, "
                                "or split into _raw and _numeric columns."
                            ),
                        })

    # Deduplicate cross-dataset inconsistencies: one row per (dataset, column, issue_type)
    try:
        seen = set()
        deduped = []
        for x in global_issues.get("cross_dataset_inconsistencies", []) or []:
            key = (x.get("dataset"), x.get("column"), x.get("issue_type"))
            if key in seen:
                continue
            seen.add(key)
            deduped.append(x)
        global_issues["cross_dataset_inconsistencies"] = deduped
    except Exception:
        pass

    # ------------------------------------------------------------
    # 8. Schema Drift Detection Across Runs
    # ------------------------------------------------------------
    import os
    import json
    
    schema_cache_file = os.path.join("config", "schema_cache.json")
    # Build current schema representation
    current_schema = {}
    for name, df in datasets.items():
        current_schema[name] = {
            col: str(df[col].dtype) for col in df.columns
        }
        
    prev_schema = {}
    if os.path.exists(schema_cache_file):
        try:
            with open(schema_cache_file, "r", encoding="utf-8") as f:
                prev_schema = json.load(f)
        except Exception:
            pass
            
    # Save current schema for next runs
    try:
        os.makedirs(os.path.dirname(schema_cache_file), exist_ok=True)
        with open(schema_cache_file, "w", encoding="utf-8") as f:
            json.dump(current_schema, f, indent=4)
    except Exception:
        pass
        
    # Compare current schema with previous schema
    if prev_schema:
        for ds_name, curr_cols in current_schema.items():
            if ds_name in prev_schema:
                prev_cols = prev_schema[ds_name]
                added = [c for c in curr_cols if c not in prev_cols]
                removed = [c for c in prev_cols if c not in curr_cols]
                type_changed = []
                for c in curr_cols:
                    if c in prev_cols and curr_cols[c] != prev_cols[c]:
                        type_changed.append({"column": c, "from": prev_cols[c], "to": curr_cols[c]})
                        
                if added or removed or type_changed:
                    global_issues["schema_drift"].append({
                        "dataset": ds_name,
                        "added_columns": added,
                        "removed_columns": removed,
                        "type_changes": type_changed,
                        "message": f"Schema drift detected on '{ds_name}'. Added: {added}, Removed: {removed}, Type changes: {type_changed}"
                    })

    return global_issues


# ============================================================
# CUSTOM RULES (config-driven, applied after standard DQ)
# ============================================================

def run_custom_rules(
    datasets: Dict[str, pd.DataFrame],
    custom_rules: List[Dict[str, Any]],
) -> Dict[str, List[Dict[str, Any]]]:
    """
    Apply custom rules from config. Each rule: dataset (or "*"), column, rule, params.
    rule: one_of, not_one_of, range, regex, not_null.
    Returns extra issues per dataset name.
    """
    extra: Dict[str, List[Dict[str, Any]]] = {}
    if not custom_rules:
        return extra

    for rule_cfg in custom_rules:
        dataset_pattern = (rule_cfg.get("dataset") or "*").strip()
        column = rule_cfg.get("column")
        rule_type = (rule_cfg.get("rule") or "").strip().lower()
        params = rule_cfg.get("params")
        if not column or not rule_type:
            continue

        for ds_name, df in datasets.items():
            if dataset_pattern != "*" and dataset_pattern != ds_name:
                continue
            if column not in df.columns:
                continue
            s = df[column].dropna().astype(str)
            if s.empty:
                continue
            issues: List[Dict[str, Any]] = []
            if rule_type == "one_of" and isinstance(params, list):
                allowed = set(str(x).strip().lower() for x in params)
                bad = ~s.str.strip().str.lower().isin(allowed)
                if bad.any():
                    cnt = int(bad.sum())
                    issues.append(dq_issue("medium", "custom_one_of",
                        f"Value not in allowed list ({cnt} rows)", column=column, count=cnt,
                        rows=df.index[bad].tolist()[:50], sample=list(s[bad].head(5))))
            elif rule_type == "range" and isinstance(params, dict):
                try:
                    num = pd.to_numeric(s, errors="coerce")
                    min_v = params.get("min")
                    max_v = params.get("max")
                    bad = pd.Series(False, index=s.index)
                    if min_v is not None:
                        bad = bad | (num < float(min_v))
                    if max_v is not None:
                        bad = bad | (num > float(max_v))
                    if bad.any():
                        cnt = int(bad.sum())
                        issues.append(dq_issue("high", "custom_range",
                            f"Value outside range ({cnt} rows)", column=column, count=cnt,
                            rows=df.index[bad].tolist()[:50], sample=list(s[bad].head(5))))
                except (TypeError, ValueError):
                    pass
            elif rule_type == "regex" and isinstance(params, (str, dict)):
                pattern = params if isinstance(params, str) else params.get("pattern", "")
                if not pattern:
                    continue
                try:
                    import re as re_mod
                    pat = re_mod.compile(pattern)
                    bad = ~s.str.strip().apply(lambda v: bool(pat.match(v)) if isinstance(v, str) else False)
                    if bad.any():
                        cnt = int(bad.sum())
                        issues.append(dq_issue("medium", "custom_regex",
                            f"Value does not match pattern ({cnt} rows)", column=column, count=cnt,
                            rows=df.index[bad].tolist()[:50], sample=list(s[bad].head(5))))
                except Exception:
                    pass
            elif rule_type == "not_null":
                null_mask = df[column].isna() | (df[column].astype(str).str.strip() == "")
                if null_mask.any():
                    cnt = int(null_mask.sum())
                    issues.append(dq_issue("high", "custom_not_null",
                        f"Null or empty not allowed ({cnt} rows)", column=column, count=cnt,
                        rows=df.index[null_mask].tolist()[:50], sample=list(df.loc[null_mask, column].head(5))))
            for i in issues:
                if ds_name not in extra:
                    extra[ds_name] = []
                extra[ds_name].append(i)
    return extra


def detect_date_format_variants(series: pd.Series) -> list[dict]:
    """
    For object/string columns suspected as dates, count format variants.
    Returns list of {"format": str, "count": int, "pct": float}
    """
    import re
    patterns = {
        "DD/MM/YYYY": r"^\d{2}/\d{2}/\d{4}$",
        "YYYY-MM-DD": r"^\d{4}-\d{2}-\d{2}$",
        "MM-DD-YYYY": r"^\d{2}-\d{2}-\d{4}$",
        "YYYY/MM/DD": r"^\d{4}/\d{2}/\d{2}$",
        "Mon D YYYY": r"^[A-Za-z]+ \d{1,2} \d{4}$",
        "DD-Mon-YYYY": r"^\d{2}-[A-Za-z]+-\d{4}$",
    }
    sample = series.dropna().astype(str).str.strip().head(5000)
    total = len(sample)
    results = []
    if total == 0:
        return []
    for fmt_name, pattern in patterns.items():
        count = sample.str.match(pattern).sum()
        if count > 0:
            results.append({"format": fmt_name, "count": int(count), "pct": round(float(count / total), 4)})
    return sorted(results, key=lambda x: -x["count"])


def confirm_business_key_duplicates(df: pd.DataFrame, pk_cols: list[str]) -> dict:
    """
    Given LLM-suggested PK columns, confirm actual duplicate count.
    """
    available = [c for c in pk_cols if c in df.columns]
    if not available:
        return {"confirmed": False, "reason": "pk_cols not found in dataframe"}
    dup_count = int(df.duplicated(subset=available).sum())
    return {
        "confirmed": True,
        "business_key_cols": available,
        "business_key_duplicate_count": dup_count,
        "dedup_strategy_hint": "keep_last" if dup_count > 0 else "no_action_needed"
    }


def detect_null_pattern(df: pd.DataFrame, col_name: str) -> dict:
    """
    Check if nulls in col_name correlate with a specific categorical column (MNAR detection).
    Caps at top-5 categorical columns to keep performance O(n).
    """
    null_mask = df[col_name].isnull()
    total_nulls = null_mask.sum()
    if total_nulls == 0:
        return {"type": "none"}
    cat_cols = [c for c in df.columns if c != col_name and df[c].dtype == object][:5]
    for cat_col in cat_cols:
        try:
            null_by_cat = df.groupby(cat_col)[col_name].apply(lambda x: x.isnull().mean())
            if not null_by_cat.empty and null_by_cat.max() > 0.8: # 80%+ nulls concentrated in one category
                return {
                    "type": "MNAR",
                    "concentrated_in_col": cat_col,
                    "concentrated_in_value": str(null_by_cat.idxmax()),
                    "fill_strategy_hint": "flag_only"
                }
        except Exception:
            pass
    return {"type": "MCAR", "fill_strategy_hint": "median_or_mode"}


# ============================================================
# MAIN ENTRYPOINT
# ============================================================

def load_and_profile(
    source_cfg: Dict[str, Any],
    *,
    additional_data: Optional[Dict[str, pd.DataFrame]] = None,
    dq_thresholds_path: Optional[str] = None,
    dq_thresholds: Optional[Dict[str, Any]] = None,
    return_datasets: bool = False,
    location_types: Optional[Collection[str]] = None,
    job_id: Optional[str] = None,
    max_rows: Optional[int] = None,
    business_rules: Optional[Dict[str, Any]] = None,
    db_connectors: Optional[Dict[str, Any]] = None,
    approved_semantics: Optional[Dict[str, Dict[str, str]]] = None,
) -> Dict[str, Any]:
    """
    Orchestrator:
    - Iterate over source_cfg["locations"]: all database + filesystem entries (azure_blob via additional_data)
    - Multiple databases: table keys prefixed (id/label or db hash) so names never collide
    - Merge with additional_data if provided (e.g., from Azure Blob Storage)
    - Profile each dataset; per-dataset DQ; relationships; global issues.
    - dq_thresholds: optional dict (if None, loaded from dq_thresholds_path or config).
    - return_datasets: if True, add result["_datasets"] = raw DataFrames (pop before JSON serialize).
    - location_types: optional set/list of lowercase location type strings (e.g. {"database","azure_blob"}).
      If set, only those location blocks are loaded from YAML. Blob data still comes only via additional_data
      (caller should pass {} when blob is excluded). If None, all location types are processed.
    """
    thresholds = dq_thresholds
    if thresholds is None:
        thresholds = load_dq_thresholds(dq_thresholds_path)

    datasets: Dict[str, pd.DataFrame] = {}
    source_root_by_dataset: Dict[str, str] = {}

    db_connectors_by_dataset: Dict[str, Tuple[Any, str]] = {}
    if db_connectors:
        for k, v in db_connectors.items():
            if isinstance(v, tuple) and len(v) == 2:
                db_connectors_by_dataset[k] = v
            else:
                table_name = k.split("__")[-1]
                db_connectors_by_dataset[k] = (v, table_name)

    locations = list(source_cfg.get("locations", []) or [])
    if location_types is not None:
        allowed = {str(t).lower() for t in location_types}
        locations = [loc for loc in locations if (loc.get("type") or "").lower() in allowed]
    db_locs = [loc for loc in locations if (loc.get("type") or "").lower() == "database"]
    multi_db = len(db_locs) > 1
    db_seen = 0

    for loc in locations:
        typ = (loc.get("type") or "").lower()

        if typ == "database":
            conn = loc.get("connection", {}) or {}
            prefix = _sql_location_key_prefix(loc, conn, db_seen, multi_db)
            label = (prefix.rstrip("_") if prefix else "") or "__default__"
            for table_key, df in load_sql_datasets(
                conn, dataset_key_prefix=prefix, max_rows=max_rows, db_connectors_by_dataset=db_connectors_by_dataset
            ).items():
                datasets[table_key] = df
                source_root_by_dataset[table_key] = (
                    f"__database__:{label}" if multi_db else "__database__"
                )
            db_seen += 1

        elif typ == "filesystem":
            fp = loc.get("path")
            if fp:
                root = os.path.abspath(os.path.normpath(fp))
                for fname, df in load_file_datasets(root, max_rows=max_rows).items():
                    key = fname
                    if key in datasets:
                        key = f"{os.path.basename(root.rstrip(os.sep))}__{fname}"
                    if key in datasets:
                        key = f"{hashlib.md5(root.encode('utf-8')).hexdigest()[:8]}__{fname}"
                    datasets[key] = df
                    source_root_by_dataset[key] = root

    if additional_data:
        for name, df in additional_data.items():
            datasets[name] = df
            norm = (name or "").replace("\\", "/")
            parent = os.path.dirname(norm).strip("/")
            source_root_by_dataset[name] = (
                f"azure_blob:{parent}" if parent else "azure_blob:"
            )

    metadata = {}
    for name, df in datasets.items():
        if job_id:
            from agent.jobs_store import add_event
            add_event(job_id=job_id, level="info", message=f"Profiling dataset: {name}")
        meta = profile_dataframe(df, job_id=job_id)
        try:
            from agent.specialists.ydata_profiler import enrich_assessment_with_profile
            meta = enrich_assessment_with_profile(df, meta)
        except Exception:
            pass # ydata-profiling optional — graceful skip

        # S4-02: SQL Server Pushdown — compute stats server-side when connector available
        if name in db_connectors_by_dataset:
            connector, table = db_connectors_by_dataset[name]

            # Pushdown aggregate stats (null counts, distinct counts, min/max)
            try:
                if hasattr(connector, 'compute_column_stats'):
                    pushdown_stats = connector.compute_column_stats(table)
                    if pushdown_stats.get("columns"):
                        for col_name, pstats in pushdown_stats["columns"].items():
                            if col_name in meta.get("columns", {}):
                                col_meta = meta["columns"][col_name]
                                # Use server-side null_percentage as authoritative
                                if "null_percentage" in pstats:
                                    col_meta["null_percentage"] = pstats["null_percentage"]
                                if "distinct_count" in pstats and pstats["distinct_count"] is not None:
                                    col_meta["unique_count"] = pstats["distinct_count"]
                                if "min_value" in pstats:
                                    col_meta["server_min"] = pstats["min_value"]
                                if "max_value" in pstats:
                                    col_meta["server_max"] = pstats["max_value"]
                                if "sql_data_type" in pstats:
                                    col_meta["sql_data_type"] = pstats["sql_data_type"]
                                # Update candidate_primary_key based on exact distinct count
                                if pushdown_stats.get("row_count") and pstats.get("distinct_count"):
                                    col_meta["candidate_primary_key"] = (
                                        pstats["distinct_count"] == pushdown_stats["row_count"]
                                        and pstats.get("null_count", 0) == 0
                                    )
                        if job_id:
                            from agent.jobs_store import add_event
                            add_event(job_id=job_id, level="info", message=f"SQL pushdown stats enriched for {name}")
            except Exception as e:
                if job_id:
                    from agent.jobs_store import add_event
                    add_event(job_id=job_id, level="warning", message=f"SQL pushdown stats failed for {name}: {e}")

            # Full database profiling (existing)
            try:
                db_prof = profile_database_table_full(connector, table, df, job_id=job_id)
                meta = merge_in_db_profile(meta, db_prof)
            except Exception as e:
                if job_id:
                    from agent.jobs_store import add_event
                    add_event(job_id=job_id, level="warning", message=f"Full database profiling failed for {name}: {e}")
                    
        meta["source_root"] = source_root_by_dataset.get(name, "")
        metadata[name] = meta

    if approved_semantics:
        import re
        def _norm_key(k: str) -> str:
            return re.sub(r"[^\w]+", "", str(k).lower())

        norm_metadata = {_norm_key(k): k for k in metadata.keys()}
        for name, table_sem in approved_semantics.items():
            norm_name = _norm_key(name)
            if norm_name in norm_metadata:
                meta = metadata[norm_metadata[norm_name]]
                norm_cols = {_norm_key(c): c for c in meta.get("columns", {})}
                for col, tag in table_sem.items():
                    norm_col = _norm_key(col)
                    if norm_col in norm_cols:
                        meta["columns"][norm_cols[norm_col]]["semantic_type"] = tag

    if len(datasets) >= 2:
        try:
            from agent.specialists.cross_dataset_agent import generate_sweetviz_comparison
            names = list(datasets.keys())
            generate_sweetviz_comparison(
                datasets[names[0]], datasets[names[1]], names[0], names[1]
            )
        except Exception:
            pass

    per_dataset_dq = {}
    ds_list = list(datasets.keys())
    for idx, name in enumerate(ds_list):
        df = datasets[name]
        if job_id:
            from agent.jobs_store import add_event
            add_event(job_id=job_id, level="info", message=f"Analyzing data quality: {name}")
        per_dataset_dq[name] = analyze_dataset_quality(name, df, metadata[name], thresholds, job_id=job_id, business_rules=business_rules)
        metadata[name]["quality"] = per_dataset_dq[name]
        if job_id:
            add_event(job_id=job_id, level="info", message=f"Quality check complete for {name}")
            try:
                from agent.jobs_store import update_job_progress
                pct = int(60 + ((idx + 1) / len(ds_list)) * 20)
                update_job_progress(job_id, pct)
            except Exception:
                pass

    # Apply custom rules from config and merge into per_dataset_dq
    custom_rules = (thresholds or {}).get("custom_rules") or []
    if isinstance(custom_rules, list):
        extra_issues = run_custom_rules(datasets, custom_rules)
        for ds_name, issues in extra_issues.items():
            if ds_name in per_dataset_dq:
                per_dataset_dq[ds_name]["issues"].extend(issues)
                per_dataset_dq[ds_name]["summary"]["issue_count"] = len(per_dataset_dq[ds_name]["issues"])
                per_dataset_dq[ds_name]["summary"]["medium_severity"] = sum(
                    1 for i in per_dataset_dq[ds_name]["issues"] if i.get("severity") == "medium"
                )
                per_dataset_dq[ds_name]["summary"]["high_severity"] = sum(
                    1 for i in per_dataset_dq[ds_name]["issues"] if i.get("severity") == "high"
                )

    rel_bundle = analyze_cross_dataset_relationships(datasets, metadata, thresholds)
    relationships = rel_bundle["relationships"]
    global_issues = detect_global_issues(datasets, thresholds)
    global_issues["relationship_row_issues"] = rel_bundle["relationship_row_issues"]
    global_issues["relationship_warnings"] = rel_bundle["relationship_warnings"]
    global_issues["cross_dataset_consistency"] = analyze_cross_dataset_consistency(datasets, metadata, thresholds)

    is_sampled = (max_rows is not None)
    for ds_name, block in per_dataset_dq.items():
        ds_sampled = is_sampled or (metadata.get(ds_name, {}).get("row_count", 0) > HEAVY_OPERATION_THRESHOLD)
        for iss in block.get("issues", []):
            iss.setdefault("dataset", ds_name)
            enrich_issue_with_recommendation(iss)
            enrich_issue_with_fixability(iss)
            if ds_sampled and iss.get("row_indexes"):
                iss["row_indexes_estimated"] = True
                if "estimated" not in str(iss.get("message")).lower():
                    iss["message"] = f"{iss['message']} (Row indexes are estimated based on a sampled subset of the data)"

    # Enrich global/cross-dataset issues
    try:
        for iss in (global_issues.get("relationship_row_issues") or []):
            enrich_issue_with_recommendation(iss)
            enrich_issue_with_fixability(iss)
            if is_sampled and iss.get("row_indexes"):
                iss["row_indexes_estimated"] = True
                if "estimated" not in str(iss.get("message")).lower():
                    iss["message"] = f"{iss['message']} (Row indexes are estimated based on a sampled subset of the data)"
        for iss in (global_issues.get("relationship_warnings") or []):
            enrich_issue_with_recommendation(iss)
            enrich_issue_with_fixability(iss)
            if is_sampled and iss.get("row_indexes"):
                iss["row_indexes_estimated"] = True
                if "estimated" not in str(iss.get("message")).lower():
                    iss["message"] = f"{iss['message']} (Row indexes are estimated based on a sampled subset of the data)"
        for iss in (global_issues.get("cross_dataset_consistency") or []):
            enrich_issue_with_recommendation(iss)
            enrich_issue_with_fixability(iss)
            if is_sampled and iss.get("row_indexes"):
                iss["row_indexes_estimated"] = True
                if "estimated" not in str(iss.get("message")).lower():
                    iss["message"] = f"{iss['message']} (Row indexes are estimated based on a sampled subset of the data)"
        for iss in (global_issues.get("cross_dataset_inconsistencies") or []):
            # these use issue_type, not type
            if isinstance(iss, dict) and iss.get("issue_type") and not iss.get("fixability"):
                iss["fixability"] = FIXABILITY_BY_ISSUE_TYPE.get(str(iss.get("issue_type")), "COMPLEX")
    except Exception:
        pass

    out = {
        "datasets": metadata,
        "relationships": relationships,
        "data_quality_issues": {
            "datasets": per_dataset_dq,
            "global_issues": global_issues
        },
        "executive_summary_items": build_executive_summary_items(per_dataset_dq, global_issues, thresholds),
    }

    # 1. Run LLM Schema Enrichment first
    try:
        from agent.llm_schema_enricher import enrich_assessment_with_schema_llm
        out = enrich_assessment_with_schema_llm(out)
    except Exception as e:
        logger.error(f"Enrichment error: {e}")

    # 2. Run the Pandas Confirmation Pass using the loaded dataframes
    for name, df in datasets.items():
        if name not in out["datasets"]:
            continue
        ds_meta = out["datasets"][name]
        
        # A. Business Key duplicate confirmation
        llm_ds_hints = ds_meta.setdefault("llm_hints", {})
        probable_pks = llm_ds_hints.get("probable_pk_columns") or []
        if probable_pks:
            dup_info = confirm_business_key_duplicates(df, probable_pks)
            llm_ds_hints["business_key_confirmation"] = dup_info
            
        # B. Date variant and Null patterns per column
        for col_name, col_meta in ds_meta.get("columns", {}).items():
            if col_name not in df.columns:
                continue
            hints = col_meta.setdefault("llm_hints", {})
            
            # Date check
            if hints.get("mixed_formats_suspected") or hints.get("semantic_type") == "date":
                fmt_vars = detect_date_format_variants(df[col_name])
                hints["format_variants"] = fmt_vars
                if len(fmt_vars) > 1:
                    hints["mixed_formats_suspected"] = True
                    
            # Null pattern check
            if col_meta.get("null_percentage", 0) > 0:
                null_pat = detect_null_pattern(df, col_name)
                hints["null_pattern"] = null_pat

    if job_id:
        try:
            from agent.jobs_store import update_job_progress
            update_job_progress(job_id, 100)
        except Exception:
            pass

    try:
        from agent.assessment_governance import enrich_assessment_with_governance

        out = enrich_assessment_with_governance(
            out,
            datasets,
            job_id=job_id,
            business_rules=business_rules,
        )
    except Exception as e:
        logger.warning("governance enrichment failed: %s", e)

    if return_datasets:
        datasets_temp = out.pop("_datasets", None)
        out = make_json_serializable(out)
        if datasets_temp is not None:
            out["_datasets"] = datasets_temp
        else:
            out["_datasets"] = datasets
    else:
        out = make_json_serializable(out)

    return out
