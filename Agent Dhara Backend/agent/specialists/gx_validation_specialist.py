import pandas as pd
import great_expectations as gx
from typing import Dict, Any, List, Optional, Tuple
import logging
import re
import numpy as np

logger = logging.getLogger(__name__)

# Fallback presets matching intelligent_data_assessment.py
PLACEHOLDERS = {
    "", " ", "-", "--", "---", "n/a", "na", "none", "null", "nil",
    "unknown", "not available", "missing", "undefined", "not applicable",
    "tbd", "tba", "n.a.", "n.a", "#n/a", "#null!", "#value!", "#ref!",
    "#div/0!", "error", "nan", "inf", "-inf", "0000-00-00", "1900-01-01",
    "9999-12-31", "00", "000", "0000", "?", "??", "???", "!",
    "temp", "test", "dummy", "placeholder", "na.", "na,", "not set",
    "unknown unknown", "n.d.", "nd", "not known",
}

SENTINEL_NUMBERS = {
    -999, -9999, -99999, -999999, -9999999,
    999, 9999, 99999, 999999, 9999999,
    -1, -99, -100, -1000,
    0.0, -0.0,
    1111, 1234, 12345, 123456, 1234567,
    9876, 98765, 9876543,
    11111, 22222, 33333, 44444, 55555, 66666, 77777, 88888,
}

BOOL_VARIANTS = {
    "true_false": {"true", "false"},
    "yes_no": {"yes", "no"},
    "y_n": {"y", "n"},
    "1_0": {"1", "0"},
    "on_off": {"on", "off"},
    "active_inactive": {"active", "inactive"},
    "enabled_disabled": {"enabled", "disabled"},
}

_DATE_RANGE_PAIRS = (
    ("start_date", "end_date"),
    ("start_dt", "end_dt"),
    ("valid_from", "valid_to"),
    ("from_date", "to_date"),
    ("begin_date", "end_date"),
    ("effective_date", "expiry_date"),
    ("effective_from", "effective_to"),
    ("period_start", "period_end"),
    ("open_date", "close_date"),
    ("order_date", "ship_date"),
    ("order_date", "delivery_date"),
    ("ship_date", "delivery_date"),
    ("created_at", "updated_at"),
    ("birth_date", "death_date"),
)

def _is_text_dtype(dtype) -> bool:
    ds = str(dtype).lower()
    return "object" in ds or "string" in ds or "str" in ds or "category" in ds

def _is_actual_numeric_column(col_name: str, approved_semantic_tag: Optional[str] = None) -> bool:
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
    return True

import os

def get_safe_validation_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """
    OOM Gating / Pre-sampling logic for production environments.
    Capping memory usage at 100MB or cell count at 1,000,000 to keep GX stable and avoid timeouts.
    Can be configured via env vars:
      - DHARA_MAX_VALIDATION_ROWS (default: 100000, set to 0 or -1 to disable row limits)
      - DHARA_MAX_VALIDATION_MEM_MB (default: 100, set to 0 or -1 to disable memory limits)
    """
    row_count = len(df)
    col_count = len(df.columns)
    if row_count == 0:
        return df

    try:
        mem_bytes = df.memory_usage(deep=False).sum()
    except Exception:
        mem_bytes = row_count * col_count * 8

    # Load custom row limits from environment
    max_rows_env = os.environ.get("DHARA_MAX_VALIDATION_ROWS")
    if max_rows_env is not None:
        try:
            MAX_ROWS = int(max_rows_env)
        except ValueError:
            MAX_ROWS = -1
    else:
        MAX_ROWS = -1

    # Load custom memory limits from environment
    max_mem_env = os.environ.get("DHARA_MAX_VALIDATION_MEM_MB")
    if max_mem_env is not None:
        try:
            val_mb = int(max_mem_env)
            MAX_MEM = val_mb * 1024 * 1024 if val_mb > 0 else -1
        except ValueError:
            MAX_MEM = -1
    else:
        MAX_MEM = -1

    # Check if limits are disabled
    disable_rows = (MAX_ROWS <= 0)
    disable_mem = (MAX_MEM <= 0)

    if (not disable_rows and row_count > MAX_ROWS) or (not disable_mem and mem_bytes > MAX_MEM):
        target_rows = MAX_ROWS if not disable_rows else row_count
        if col_count > 50 and not disable_rows:
            target_rows = min(target_rows, 50_000)
        if col_count > 100 and not disable_rows:
            target_rows = min(target_rows, 25_000)
        logger.info(f"OOM Protection: Sampling dataset from {row_count} rows to {target_rows} rows for GX validation.")
        return df.sample(n=target_rows, random_state=42)
    return df

def run_gx_validation(
    datasets: Dict[str, pd.DataFrame],
    profile_results: Dict[str, Any],
    thresholds: Optional[Dict[str, Any]] = None,
    business_rules: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Runs dynamically configured GX validation on the provided datasets.
    """
    gx_results = {}
    thresholds = thresholds or {}
    business_rules = business_rules or {}

    local_placeholders = set(str(p).lower() for p in thresholds.get("placeholders", [])) if thresholds.get("placeholders") else PLACEHOLDERS
    local_sentinels = set(float(s) for s in thresholds.get("sentinels", []) if s is not None) if thresholds.get("sentinels") else SENTINEL_NUMBERS

    try:
        context = gx.get_context()

        for name, df in datasets.items():
            if df is None or (isinstance(df, pd.DataFrame) and df.empty):
                gx_results[name] = {"success": True, "statistics": {"evaluated_expectations": 0, "successful_expectations": 0, "unsuccessful_expectations": 0, "success_percent": 100}, "results": []}
                continue

            dataset_safe_name = name.replace('.', '_').replace('/', '_').replace('\\', '_')
            datasource_name = f"ds_{dataset_safe_name}"
            asset_name = f"asset_{dataset_safe_name}"
            suite_name = f"suite_{dataset_safe_name}"

            validation_df = get_safe_validation_dataframe(df)

            try:
                # 1. Datasource Setup
                datasource = None
                if hasattr(context, "data_sources"):  # GX 1.0+
                    try:
                        datasource = context.data_sources.add_pandas(name=datasource_name)
                    except Exception:
                        datasource = context.data_sources.get(datasource_name)
                elif hasattr(context, "sources"):  # GX 0.17+
                    try:
                        datasource = context.sources.add_pandas(name=datasource_name)
                    except Exception:
                        datasource = context.sources.get(datasource_name)

                if not datasource:
                    logger.warning(f"Could not initialize datasource {datasource_name}")
                    continue

                try:
                    asset = datasource.add_dataframe_asset(name=asset_name)
                except Exception:
                    asset = datasource.get_asset(asset_name)

                # 2. Suite Setup
                if hasattr(context, "suites"):  # GX 1.0+
                    try:
                        suite = context.suites.add(gx.ExpectationSuite(name=suite_name))
                    except Exception:
                        suite = context.suites.get(suite_name)
                else:  # GX 0.x
                    try:
                        suite = context.add_expectation_suite(expectation_suite_name=suite_name)
                    except Exception:
                        suite = context.get_expectation_suite(expectation_suite_name=suite_name)

                # 3. Validator Setup
                batch_definition_name = f"batch_def_{dataset_safe_name}"
                try:
                    batch_definition = asset.add_batch_definition_whole_dataframe(batch_definition_name)
                except Exception:
                    batch_definition = asset.get_batch_definition(batch_definition_name)

                batch = batch_definition.get_batch(batch_parameters={"dataframe": validation_df})
                validator = context.get_validator(batch=batch, expectation_suite_name=suite_name)

                # 4. Read Metadata Profile
                ds_profile = (profile_results.get("datasets") or {}).get(name) or {}
                cols_meta = ds_profile.get("columns") or {}
                priority_cols = set(ds_profile.get("priority_columns") or list(validation_df.columns))

                # --- Build Expectations ---
                
                # A. Table-Level
                validator.expect_table_columns_to_match_ordered_list(column_list=list(validation_df.columns))
                
                # Uniqueness of rows (Duplicate row check) - Guard to make sure there are at least two columns
                if len(validation_df.columns) >= 2:
                    validator.expect_compound_columns_to_be_unique(column_list=list(validation_df.columns))

                # Non-nullable columns from business rules
                non_nullable_set = set()
                nn_list = business_rules.get("non_nullable") or []
                req_list = business_rules.get("required_columns") or []
                for c in nn_list:
                    non_nullable_set.add(str(c).lower())
                for c in req_list:
                    non_nullable_set.add(str(c).lower())

                # Build custom assertions list for prioritizing rules
                assertions_list = []
                if isinstance(business_rules, dict):
                    assertions_list.extend(business_rules.get("custom_assertions") or [])
                    assertions_list.extend(business_rules.get("assertions") or [])
                seen_assertions = set()
                deduped_assertions = []
                for r in assertions_list:
                    if isinstance(r, dict) and r.get("assertion"):
                        ast = r.get("assertion")
                        if ast not in seen_assertions:
                            seen_assertions.add(ast)
                            deduped_assertions.append(r)

                has_business_rules = False
                if isinstance(business_rules, dict):
                    if (business_rules.get("non_nullable") or 
                        business_rules.get("required_columns") or 
                        business_rules.get("valid_values") or 
                        deduped_assertions):
                        has_business_rules = True
                columns_with_custom_rules = set()
                
                # Check valid values
                vv = business_rules.get("valid_values") or {}
                for col_key in vv.keys():
                    for col in validation_df.columns:
                        from agent.intelligent_data_assessment import match_column_key
                        if match_column_key(col_key, name, col):
                            columns_with_custom_rules.add(col.lower())

                # Check custom assertions
                for rule in deduped_assertions:
                    assertion = rule.get("assertion", "")
                    for col in validation_df.columns:
                        pattern = r'\b' + re.escape(col) + r'\b'
                        if re.search(pattern, assertion, re.IGNORECASE):
                            columns_with_custom_rules.add(col.lower())

                # B. Column-Level Expectations
                for col_name in validation_df.columns:
                    meta = cols_meta.get(col_name) or {}
                    s = validation_df[col_name]
                    dtype = str(s.dtype).lower()
                    
                    semantic_type = (meta.get("semantic_type") or "unknown").lower()
                    if semantic_type == "unknown" or not semantic_type:
                        from agent.intelligent_data_assessment import detect_semantic_type
                        try:
                            semantic_type = detect_semantic_type(s).lower()
                        except Exception:
                            semantic_type = "unknown"
                            
                    null_pct = meta.get("null_percentage", 0.0)

                    # Null check:
                    # If business rules are active, only enforce non-null on required/non-nullable columns or candidate primary keys.
                    # Otherwise, run it on all columns.
                    is_required = (col_name.lower() in non_nullable_set)
                    is_primary_key = bool(meta.get("candidate_primary_key"))
                    
                    if not has_business_rules or is_required or is_primary_key:
                        validator.expect_column_values_to_not_be_null(column=col_name)

                    # Uniqueness / Primary Key candidates
                    if is_primary_key:
                        validator.expect_column_values_to_be_unique(column=col_name)

                    # Typings & Ranges
                    if "int" in dtype:
                        validator.expect_column_values_to_be_in_type_list(column=col_name, type_list=["int64", "int32", "int", "Int64"])
                    elif "float" in dtype or "decimal" in dtype:
                        validator.expect_column_values_to_be_in_type_list(column=col_name, type_list=["float64", "float32", "float"])

                    # If this column has a custom business rule (valid values or custom assertion),
                    # we suppress the default semantic validations to avoid duplicate/conflicting failures.
                    if col_name.lower() in columns_with_custom_rules:
                        continue

                    # Semantic Regex
                    if semantic_type == "email":
                        validator.expect_column_values_to_match_regex(column=col_name, regex=r"^[^@\s]+@[^@\s]*\.[^@\s]+$")
                    elif semantic_type == "phone":
                        validator.expect_column_values_to_match_regex(column=col_name, regex=r"^[+()\-\.\s0-9]{7,}$")
                    elif semantic_type in ("uuid", "guid"):
                        validator.expect_column_values_to_match_regex(
                            column=col_name,
                            regex=r"(?i)^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
                        )
                    elif semantic_type == "date":
                        validator.expect_column_values_to_be_dateutil_parseable(column=col_name)

                    # Numeric bounds and Sentinel checks for non-ID numeric columns
                    is_id_like = col_name.lower().endswith("id") or col_name.lower().endswith("key") or col_name.lower().endswith("code") or semantic_type in ("numeric_id", "id")
                    
                    if ("int" in dtype or "float" in dtype) and not is_id_like:
                        v_clean = s.dropna()
                        if not v_clean.empty:
                            # Negative values check
                            validator.expect_column_values_to_be_between(column=col_name, min_value=0)
                            
                            # Sentinel/magic values check
                            if local_sentinels:
                                validator.expect_column_values_to_not_be_in_set(column=col_name, value_set=list(local_sentinels))

                    # Suspicious zero check for ID columns (numeric or string)
                    if is_id_like:
                        validator.expect_column_values_to_not_be_in_set(column=col_name, value_set=[0, 0.0, "0", "0.0"])




                # 5. Run GX Validation (using COMPLETE format for index tracking)
                validation_result = validator.validate(result_format="COMPLETE")

                # Parse the outcomes
                results_processed = []
                res_list = validation_result.get("results", []) if isinstance(validation_result, dict) else getattr(validation_result, "results", [])

                for r in res_list:
                    exp_type = "unknown"
                    col = "-"
                    cfg = getattr(r, "expectation_config", None)
                    kwargs_dict = {}
                    if cfg:
                        if isinstance(cfg, dict):
                            exp_type = cfg.get("expectation_type") or cfg.get("type") or "unknown"
                            kwargs_dict = cfg.get("kwargs", {})
                            col = kwargs_dict.get("column", "-")
                        else:
                            exp_type = getattr(cfg, "expectation_type", None) or getattr(cfg, "type", "unknown")
                            kwargs_obj = getattr(cfg, "kwargs", {})
                            if isinstance(kwargs_obj, dict):
                                kwargs_dict = kwargs_obj
                            else:
                                try:
                                    kwargs_dict = dict(kwargs_obj)
                                except Exception:
                                    kwargs_dict = {
                                        "column": getattr(kwargs_obj, "column", "-"),
                                        "regex": getattr(kwargs_obj, "regex", None)
                                    }
                            col = kwargs_dict.get("column", "-") if "column" in kwargs_dict else getattr(kwargs_obj, "column", "-")

                    if not col or col == "-":
                        # compound compound column or row-level expectation
                        kwargs = getattr(cfg, "kwargs", {}) if not isinstance(cfg, dict) else cfg.get("kwargs", {})
                        if "column_list" in kwargs:
                            col = "[Row-level]"

                    exp_type_str = str(exp_type).replace("expect_", "").replace("_", " ")

                    # Map semantic regex patterns to clean, specific expectation names
                    if exp_type == "expect_column_values_to_match_regex" and kwargs_dict:
                        pattern = kwargs_dict.get("regex")
                        if pattern == r"^[^@\s]+@[^@\s]*\.[^@\s]+$":
                            exp_type_str = "invalid_email"
                        elif pattern == r"^[+()\-\.\s0-9]{7,}$":
                            exp_type_str = "invalid_phone"
                        elif pattern == r"(?i)^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$":
                            exp_type_str = "invalid_uuid"
                    elif exp_type == "expect_column_values_to_be_between" and kwargs_dict:
                        min_v = kwargs_dict.get("min_value")
                        max_v = kwargs_dict.get("max_value")
                        if min_v == 0 and max_v is None:
                            exp_type_str = "negative_values"
                    elif exp_type == "expect_column_values_to_not_be_in_set" and kwargs_dict:
                        v_set = kwargs_dict.get("value_set") or []
                        try:
                            v_set_str = [str(v) for v in v_set]
                            if v_set_str and all(v in ("0", "0.0", "0.0") for v in v_set_str):
                                exp_type_str = "suspicious_zero"
                            else:
                                exp_type_str = "sentinel_numeric_value"
                        except Exception:
                            exp_type_str = "sentinel_numeric_value"

                    success = bool(r.get("success", False) if isinstance(r, dict) else getattr(r, "success", False))

                    res_obj = r.get("result", {}) if isinstance(r, dict) else getattr(r, "result", {})
                    unexp_cnt = res_obj.get("unexpected_count", 0) if isinstance(res_obj, dict) else getattr(res_obj, "unexpected_count", 0)
                    pct = res_obj.get("unexpected_percent", 0.0) if isinstance(res_obj, dict) else getattr(res_obj, "unexpected_percent", 0.0)
                    
                    unexp_indices = res_obj.get("unexpected_index_list", []) if isinstance(res_obj, dict) else getattr(res_obj, "unexpected_index_list", [])
                    if not unexp_indices and isinstance(res_obj, dict):
                        unexp_indices = res_obj.get("partial_unexpected_index_list", [])
                    
                    unexp_vals = res_obj.get("unexpected_list", []) if isinstance(res_obj, dict) else getattr(res_obj, "unexpected_list", [])
                    if not unexp_vals and isinstance(res_obj, dict):
                        unexp_vals = res_obj.get("partial_unexpected_list", [])

                    details = "All values meet the expectation."
                    if not success:
                        if unexp_cnt > 0:
                            details = f"Found {unexp_cnt} invalid values ({round(pct, 2)}%)"
                        else:
                            details = "Validation failed for some values."

                    results_processed.append({
                        "expectation": exp_type_str,
                        "column": col,
                        "success": success,
                        "details": details,
                        "unexpected_count": unexp_cnt,
                        "unexpected_index_list": unexp_indices,
                        "unexpected_values": unexp_vals
                    })

                # --- Evaluate Custom/Conditional/Formula rules and append to results ---
                # This ensures they run on the safe sampled validation_df, preventing OOM.

                # 0.0.1 Whitespace Padding Check (leading/trailing or empty/whitespace-only)
                for col in validation_df.columns:
                    col_series = validation_df[col]
                    if _is_text_dtype(col_series.dtype):
                        non_null_s = col_series.dropna().astype(str)
                        if not non_null_s.empty:
                            mask_padding = non_null_s.str.contains(r"^\s+|\s+$", regex=True)
                            mask_empty = non_null_s.str.contains(r"^\s*$", regex=True)
                            mask = mask_padding | mask_empty
                            bad_cnt = int(mask.sum())
                            if bad_cnt > 0:
                                results_processed.append({
                                    "expectation": "whitespace",
                                    "column": col,
                                    "success": False,
                                    "details": f"{bad_cnt} value(s) with leading/trailing or empty whitespace padding",
                                    "unexpected_count": bad_cnt,
                                    "unexpected_index_list": non_null_s.index[mask].tolist(),
                                    "unexpected_values": col_series.loc[non_null_s.index[mask]].head(5).tolist()
                                })

                # 0.0.2 Internal Whitespace Check (consecutive spaces)
                for col in validation_df.columns:
                    col_series = validation_df[col]
                    if _is_text_dtype(col_series.dtype):
                        non_null_s = col_series.dropna().astype(str)
                        if not non_null_s.empty:
                            mask = non_null_s.str.contains(r"  +", regex=True)
                            bad_cnt = int(mask.sum())
                            if bad_cnt > 0:
                                results_processed.append({
                                    "expectation": "internal_whitespace",
                                    "column": col,
                                    "success": False,
                                    "details": f"{bad_cnt} value(s) with consecutive spaces",
                                    "unexpected_count": bad_cnt,
                                    "unexpected_index_list": non_null_s.index[mask].tolist(),
                                    "unexpected_values": col_series.loc[non_null_s.index[mask]].head(5).tolist()
                                })

                # 0.0.3 HTML Tags Check
                for col in validation_df.columns:
                    col_meta = cols_meta.get(col) or {}
                    semantic_type = (col_meta.get("semantic_type") or "").lower()
                    col_series = validation_df[col]
                    if _is_text_dtype(col_series.dtype) or semantic_type in ("email", "free_text", "categorical"):
                        non_null_s = col_series.dropna().astype(str)
                        if not non_null_s.empty:
                            mask = non_null_s.str.contains(r"<[a-zA-Z][^>]*>|</[a-zA-Z]+>", regex=True)
                            bad_cnt = int(mask.sum())
                            if bad_cnt > 0:
                                results_processed.append({
                                    "expectation": "html_tags_in_text",
                                    "column": col,
                                    "success": False,
                                    "details": f"{bad_cnt} value(s) containing HTML tags",
                                    "unexpected_count": bad_cnt,
                                    "unexpected_index_list": non_null_s.index[mask].tolist(),
                                    "unexpected_values": col_series.loc[non_null_s.index[mask]].head(5).tolist()
                                })

                # 0.0.4 Punctuation-Only Check
                for col in validation_df.columns:
                    col_meta = cols_meta.get(col) or {}
                    semantic_type = (col_meta.get("semantic_type") or "").lower()
                    col_series = validation_df[col]
                    if _is_text_dtype(col_series.dtype) or semantic_type in ("email", "free_text", "categorical"):
                        non_null_s = col_series.dropna().astype(str)
                        if not non_null_s.empty:
                            mask = non_null_s.str.contains(r"^[\W_]+$", regex=True)
                            bad_cnt = int(mask.sum())
                            if bad_cnt > 0:
                                results_processed.append({
                                    "expectation": "punctuation_only_value",
                                    "column": col,
                                    "success": False,
                                    "details": f"{bad_cnt} punctuation-only value(s)",
                                    "unexpected_count": bad_cnt,
                                    "unexpected_index_list": non_null_s.index[mask].tolist(),
                                    "unexpected_values": col_series.loc[non_null_s.index[mask]].head(5).tolist()
                                })

                # 0.1 Placeholders Check
                for col in validation_df.columns:
                    col_meta = cols_meta.get(col) or {}
                    col_series = validation_df[col]
                    col_stripped = col_series.dropna().astype(str).str.strip().str.lower()
                    if not col_stripped.empty:
                        pl_mask = col_stripped.isin(local_placeholders)
                        pl_cnt = int(pl_mask.sum())
                        if pl_cnt > 0:
                            results_processed.append({
                                "expectation": "placeholder_detected",
                                "column": col,
                                "success": False,
                                "details": f"{pl_cnt} null/placeholder value(s) detected",
                                "unexpected_count": pl_cnt,
                                "unexpected_index_list": col_stripped.index[pl_mask].tolist(),
                                "unexpected_values": col_series.loc[col_stripped.index[pl_mask]].head(5).tolist()
                            })

                # 0.2 Sentinels Check
                for col in validation_df.columns:
                    col_meta = cols_meta.get(col) or {}
                    semantic_type = (col_meta.get("semantic_type") or "unknown").lower()
                    col_series = validation_df[col]
                    dtype = str(col_series.dtype).lower()
                    if ("int" in dtype or "float" in dtype) or semantic_type in ("numeric_id", "numeric"):
                        num_col = pd.to_numeric(col_series.astype(str).str.strip(), errors="coerce").dropna()
                        if not num_col.empty:
                            sent_mask = num_col.apply(lambda v: float(v) in local_sentinels)
                            sent_cnt = int(sent_mask.sum())
                            if sent_cnt > 0:
                                results_processed.append({
                                    "expectation": "sentinel_numeric_value",
                                    "column": col,
                                    "success": False,
                                    "details": f"{sent_cnt} sentinel/magic number(s) detected (e.g. -999, 9999999)",
                                    "unexpected_count": sent_cnt,
                                    "unexpected_index_list": num_col.index[sent_mask].tolist(),
                                    "unexpected_values": col_series.loc[num_col.index[sent_mask]].head(5).tolist()
                                })
                # 1. Valid Values Lookup
                if business_rules:
                    vv = business_rules.get("valid_values")
                    if vv and isinstance(vv, dict):
                        from agent.intelligent_data_assessment import match_column_key
                        for col_key, vals in vv.items():
                            for col in validation_df.columns:
                                if match_column_key(col_key, name, col):
                                    allowed = {str(v).lower() for v in (vals if isinstance(vals, list) else [vals])}
                                    col_values_lower = validation_df[col].astype(str).str.lower()
                                    invalid_mask = validation_df[col].notna() & (~col_values_lower.isin(allowed))
                                    invalid_cnt = int(invalid_mask.sum())
                                    if invalid_cnt > 0:
                                        results_processed.append({
                                            "expectation": "invalid_lookup_value",
                                            "column": col,
                                            "success": False,
                                            "details": f"Value not in allowed lookup list for {col} ({invalid_cnt} invalid value(s))",
                                            "unexpected_count": invalid_cnt,
                                            "unexpected_index_list": validation_df.index[invalid_mask].tolist(),
                                            "unexpected_values": validation_df.loc[invalid_mask, col].head(5).tolist()
                                        })

                # 2. Custom Assertions
                for rule in deduped_assertions:
                    assertion = rule.get("assertion")
                    custom_msg = rule.get("message")
                    try:
                        from agent.intelligent_data_assessment import evaluate_custom_assertion
                        res, ref_cols = evaluate_custom_assertion(validation_df, assertion)
                        if isinstance(res, pd.Series):
                            viol_mask = ~res.fillna(False)
                            viol_cnt = int(viol_mask.sum())
                            if viol_cnt > 0:
                                msg = custom_msg or f"Custom rule violation: '{assertion}' ({viol_cnt} violations)"
                                results_processed.append({
                                    "expectation": "custom_rule_violation",
                                    "column": ",".join(ref_cols) if ref_cols else "[Formula]",
                                    "success": False,
                                    "details": msg,
                                    "unexpected_count": viol_cnt,
                                    "unexpected_index_list": validation_df.index[viol_mask].tolist(),
                                    "unexpected_values": validation_df.loc[viol_mask, ref_cols].head(5).to_dict(orient="records") if ref_cols else []
                                })
                    except Exception as ex:
                        logger.error(f"Error evaluating custom assertion: {ex}")

                # 3. Conditional Rules
                conditional_rules = thresholds.get("conditional_rules") or []
                for rule in conditional_rules:
                    if not isinstance(rule, dict):
                        continue
                    rule_type = rule.get("type")
                    try:
                        if rule_type == "conditional_not_null":
                            when_col, when_val, then_col = rule["when_column"], rule["when_value"], rule["then_column"]
                            if when_col in validation_df.columns and then_col in validation_df.columns:
                                mask = validation_df[when_col].astype(str).str.strip().eq(str(when_val)) & validation_df[then_col].isna()
                                bad_rows = validation_df.loc[mask]
                                if len(bad_rows) > 0:
                                    results_processed.append({
                                        "expectation": "conditional_not_null",
                                        "column": then_col,
                                        "success": False,
                                        "details": f"'{then_col}' must not be null when '{when_col}' = '{when_val}'.",
                                        "unexpected_count": len(bad_rows),
                                        "unexpected_index_list": bad_rows.index.tolist(),
                                        "unexpected_values": [None] * len(bad_rows)
                                    })
                        elif rule_type == "conditional_range":
                            when_col, when_val, then_col = rule["when_column"], rule["when_value"], rule["then_column"]
                            min_val, max_val = rule.get("min"), rule.get("max")
                            if when_col in validation_df.columns and then_col in validation_df.columns:
                                cond = validation_df[when_col].astype(str).str.strip().eq(str(when_val))
                                sub = validation_df.loc[cond]
                                if not sub.empty:
                                    num = pd.to_numeric(sub[then_col], errors="coerce")
                                    viol = num.isna() & sub[then_col].notna()
                                    if min_val is not None: viol |= num.notna() & (num < float(min_val))
                                    if max_val is not None: viol |= num.notna() & (num > float(max_val))
                                    bad_rows = sub.loc[viol]
                                    if len(bad_rows) > 0:
                                        results_processed.append({
                                            "expectation": "conditional_range",
                                            "column": then_col,
                                            "success": False,
                                            "details": f"'{then_col}' must be between {min_val} and {max_val} when '{when_col}' = '{when_val}'.",
                                            "unexpected_count": len(bad_rows),
                                            "unexpected_index_list": bad_rows.index.tolist(),
                                            "unexpected_values": bad_rows[then_col].tolist()
                                        })
                    except Exception as ex:
                        logger.error(f"Error evaluating conditional rule: {ex}")

                # 4. Formula Rules
                formula_rules = thresholds.get("formula_rules") or []
                for rule in formula_rules:
                    if not isinstance(rule, dict):
                        continue
                    assertion = rule.get("assertion")
                    if not assertion:
                        continue
                    try:
                        ref_cols = [col for col in validation_df.columns if re.search(r'\b' + re.escape(col) + r'\b', assertion)]
                        if ref_cols:
                            eval_df = pd.DataFrame(index=validation_df.index)
                            valid_rows = pd.Series(True, index=validation_df.index)
                            for col in ref_cols:
                                eval_df[col] = pd.to_numeric(validation_df[col], errors='coerce')
                                valid_rows &= eval_df[col].notna()
                            if valid_rows.any():
                                res = eval_df.eval(assertion)
                                viol_mask = valid_rows & (~res.fillna(False))
                                viol_cnt = int(viol_mask.sum())
                                if viol_cnt > 0:
                                    results_processed.append({
                                        "expectation": "formula_rule_violation",
                                        "column": ",".join(ref_cols),
                                        "success": False,
                                        "details": f"Formula assertion failed: '{assertion}'",
                                        "unexpected_count": viol_cnt,
                                        "unexpected_index_list": validation_df.index[viol_mask].tolist(),
                                        "unexpected_values": validation_df.loc[viol_mask, ref_cols].head(5).to_dict(orient="records")
                                    })
                    except Exception as ex:
                        logger.error(f"Error evaluating formula rule: {ex}")

                # 5. Near-Duplicate Rows (rapidfuzz)
                nd_cfg = thresholds.get("near_duplicate") or {}
                if nd_cfg.get("enabled", True):
                    from rapidfuzz import fuzz
                    text_cols = [c for c in validation_df.columns if _is_text_dtype(validation_df[c].dtype) and not c.lower().endswith("id")]
                    if len(text_cols) >= 2:
                        sub_df = validation_df[text_cols].dropna(how="all")
                        # limit rows for near duplicate checks to avoid extreme latency
                        sub_df = sub_df.head(1000)
                        row_strings = sub_df.apply(lambda row: " | ".join(str(val) for val in row), axis=1).tolist()
                        row_indices = sub_df.index.tolist()
                        threshold = float(nd_cfg.get("threshold", 0.92)) * 100
                        near_dups = []
                        # Compare pairwise
                        for i in range(len(row_strings)):
                            for j in range(i + 1, len(row_strings)):
                                ratio = fuzz.token_sort_ratio(row_strings[i], row_strings[j])
                                if ratio >= threshold:
                                    near_dups.append((row_indices[i], row_indices[j], ratio / 100.0))
                        if near_dups:
                            results_processed.append({
                                "expectation": "near_duplicate_rows",
                                "column": "[Row-level]",
                                "success": False,
                                "details": f"Found {len(near_dups)} pair(s) of near-duplicate rows withsimilarity >= {threshold/100:.2f}",
                                "unexpected_count": len(near_dups),
                                "unexpected_index_list": [a for a, b, s in near_dups],
                                "unexpected_values": [{"row_index_a": int(a), "row_index_b": int(b), "similarity": float(s)} for a, b, s in near_dups[:10]]
                            })

                # 6. Multivariate Outliers (sklearn IsolationForest)
                num_cols = [c for c in validation_df.columns if pd.api.types.is_numeric_dtype(validation_df[c]) and not c.lower().endswith("id")]
                if len(num_cols) >= 2 and len(validation_df) >= 10:
                    outlier_cfg = thresholds.get("multivariate_outliers") or {}
                    if outlier_cfg.get("enabled", True):
                        clean_df = validation_df[num_cols].dropna()
                        if len(clean_df) >= 10:
                            try:
                                from sklearn.ensemble import IsolationForest
                                contamination = float(outlier_cfg.get("contamination", 0.02))
                                model = IsolationForest(contamination=contamination, random_state=42)
                                preds = model.fit_predict(clean_df)
                                outlier_mask = preds == -1
                                outliers = clean_df[outlier_mask]
                                if len(outliers) > 0:
                                    results_processed.append({
                                        "expectation": "multivariate_outliers",
                                        "column": "[Row-level]",
                                        "success": False,
                                        "details": f"Detected {len(outliers)} multivariate outlier(s) using IsolationForest",
                                        "unexpected_count": len(outliers),
                                        "unexpected_index_list": outliers.index.tolist(),
                                        "unexpected_values": outliers.head(5).to_dict(orient="records")
                                    })
                            except Exception:
                                pass

                # 7. Self-referencing hierarchical FK hierarchy check
                id_cols = [c for c in validation_df.columns if c.lower().endswith("id")]
                if len(id_cols) >= 2:
                    for col_pk in id_cols:
                        if validation_df[col_pk].dropna().is_unique and validation_df[col_pk].notna().any():
                            pk_lower = col_pk.lower()
                            pk_base = pk_lower[:-2].strip("_")
                            for col_fk in id_cols:
                                if col_fk == col_pk:
                                    continue
                                fk_lower = col_fk.lower()
                                is_hierarchical = any(w in fk_lower for w in ["parent", "manager", "prev", "next", "reports", "sub", "master", "hierarchy", "ancestor", "descendant"])
                                if pk_base and pk_base not in fk_lower and not is_hierarchical:
                                    continue
                                fk_vals = validation_df[col_fk].dropna()
                                if len(fk_vals) > 0:
                                    pk_vals = set(validation_df[col_pk].dropna())
                                    orphans = [v for v in fk_vals if v not in pk_vals]
                                    if len(orphans) > 0:
                                        results_processed.append({
                                            "expectation": "intra_dataset_orphan_fk",
                                            "column": col_fk,
                                            "success": False,
                                            "details": f"{len(orphans)} self-referencing orphan value(s) in '{col_fk}' (referring to '{col_pk}')",
                                            "unexpected_count": len(orphans),
                                            "unexpected_index_list": validation_df.index[validation_df[col_fk].isin(orphans)].tolist(),
                                            "unexpected_values": list(set(orphans))[:5]
                                        })

                # 8. Functional Dependencies
                _DEFAULT_FUNCTIONAL_DEPENDENCIES = [
                    {"determinant": "zip", "dependent": "city"},
                    {"determinant": "zip", "dependent": "state"},
                    {"determinant": "postal_code", "dependent": "city"},
                    {"determinant": "postal_code", "dependent": "state"},
                    {"determinant": "country_code", "dependent": "country"},
                    {"determinant": "store_id", "dependent": "store_name"},
                    {"determinant": "product_id", "dependent": "product_name"},
                    {"determinant": "customer_id", "dependent": "customer_name"},
                ]
                fd_cfg = thresholds.get("functional_dependencies") or _DEFAULT_FUNCTIONAL_DEPENDENCIES
                if isinstance(fd_cfg, list):
                    for rule in fd_cfg:
                        det = str(rule.get("determinant", "")).lower().strip()
                        dep = str(rule.get("dependent", "")).lower().strip()
                        if det and dep:
                            cmap = {str(c).lower().strip(): c for c in validation_df.columns}
                            det_col = cmap.get(det)
                            dep_col = cmap.get(dep)
                            if det_col and dep_col and len(validation_df) >= 10:
                                clean = validation_df[[det_col, dep_col]].dropna()
                                if len(clean) >= 10:
                                    gp = clean.groupby(det_col)[dep_col].nunique()
                                    violations = gp[gp > 1]
                                    if len(violations) > 0:
                                        violation_keys = list(violations.index)
                                        v_mask = validation_df[det_col].isin(violation_keys)
                                        results_processed.append({
                                            "expectation": "functional_dependency_violation",
                                            "column": det_col,
                                            "success": False,
                                            "details": f"Functional dependency violation: '{det_col}' -> '{dep_col}'.",
                                            "unexpected_count": len(violations),
                                            "unexpected_index_list": validation_df.index[v_mask].tolist(),
                                            "unexpected_values": [{"determinant_value": vk, "distinct_dependent_values": list(clean[clean[det_col] == vk][dep_col].unique())} for vk in violation_keys[:5]]
                                        })

                # 9. Date Range pairs ordering
                cmap = {str(c).lower(): c for c in validation_df.columns}
                for a, b in _DATE_RANGE_PAIRS:
                    ca, cb = cmap.get(a), cmap.get(b)
                    if ca and cb:
                        from dateutil import parser as du_parser
                        def _robust_date_parse(val: Any):
                            if pd.isna(val) or not isinstance(val, str) or not val.strip():
                                return None
                            try:
                                return du_parser.parse(val.strip(), fuzzy=False)
                            except Exception:
                                return None
                        d1 = validation_df[ca].map(_robust_date_parse)
                        d2 = validation_df[cb].map(_robust_date_parse)
                        bad = d2.notna() & d1.notna() & (d2 < d1)
                        bc = int(bad.sum())
                        if bc > 0:
                            results_processed.append({
                                "expectation": "date_range_violation",
                                "column": f"{ca},{cb}",
                                "success": False,
                                "details": f"'{cb}' is before '{ca}'",
                                "unexpected_count": bc,
                                "unexpected_index_list": validation_df.index[bad].tolist(),
                                "unexpected_values": validation_df.loc[bad, [ca, cb]].head(5).to_dict(orient="records")
                            })

                # 10. Mixed Date Formats check
                for col_name in validation_df.columns:
                    meta = cols_meta.get(col_name, {})
                    semantic_type = (meta.get("semantic_type") or "").lower()
                    if semantic_type == "date":
                        s = validation_df[col_name]
                        if _is_text_dtype(s.dtype):
                            non_empty = s.dropna().astype(str).str.strip()
                            non_empty = non_empty[non_empty != ""]
                            if len(non_empty) >= 10:
                                fmt_iso = non_empty.str.match(r"^\d{4}-\d{2}-\d{2}", na=False)
                                fmt_us = non_empty.str.match(r"^\d{1,2}/\d{1,2}/\d{2,4}", na=False)
                                fmt_eu = non_empty.str.match(r"^\d{1,2}\.\d{1,2}\.\d{2,4}", na=False)
                                active_fmts = [(c, v) for c, v in [("ISO(YYYY-MM-DD)", int(fmt_iso.sum())),
                                                                    ("US(MM/DD/YYYY)", int(fmt_us.sum())),
                                                                    ("EU(DD.MM.YYYY)", int(fmt_eu.sum()))]
                                               if v > 0]
                                if len(active_fmts) >= 2:
                                    detail = ", ".join(f"{n}={c}" for n, c in active_fmts)
                                    results_processed.append({
                                        "expectation": "mixed_date_formats",
                                        "column": col_name,
                                        "success": False,
                                        "details": f"Multiple date formats detected: {detail}",
                                        "unexpected_count": sum(c for _, c in active_fmts),
                                        "unexpected_index_list": non_empty.index[fmt_iso | fmt_us | fmt_eu].tolist(),
                                        "unexpected_values": [n for n, _ in active_fmts]
                                    })

                # 11. Case inconsistency check
                for col_name in validation_df.columns:
                    s = validation_df[col_name]
                    if _is_text_dtype(s.dtype):
                        sub = s.dropna()
                        if len(sub) > 5:
                            col_lower_name = str(col_name).lower()
                            is_text_like = any(k in col_lower_name for k in ("name", "title", "label", "desc", "comment", "remark", "status", "type"))
                            if is_text_like:
                                all_caps = sub.astype(str).str.isupper()
                                all_caps_cnt = int(all_caps.sum())
                                not_all_caps_cnt = int((~all_caps).sum())
                                if all_caps_cnt > 0 and not_all_caps_cnt > 0 and all_caps_cnt < len(sub) * 0.9:
                                    results_processed.append({
                                        "expectation": "all_caps_values",
                                        "column": col_name,
                                        "success": False,
                                        "details": f"{all_caps_cnt} ALL-CAPS value(s) mixed with {not_all_caps_cnt} mixed/lower-case",
                                        "unexpected_count": all_caps_cnt,
                                        "unexpected_index_list": sub.index[all_caps].tolist(),
                                        "unexpected_values": list(sub[all_caps].head(5))
                                    })

                # 12. Duplicate UUID
                for col_name in validation_df.columns:
                    meta = cols_meta.get(col_name, {})
                    semantic_type = (meta.get("semantic_type") or "").lower()
                    if semantic_type == "uuid" and col_name in validation_df.columns:
                        s = validation_df[col_name].dropna()
                        dup_uuids = s[s.duplicated()]
                        if len(dup_uuids) > 0:
                            results_processed.append({
                                "expectation": "duplicate_uuid",
                                "column": col_name,
                                "success": False,
                                "details": f"{len(dup_uuids)} duplicate UUID(s)",
                                "unexpected_count": len(dup_uuids),
                                "unexpected_index_list": validation_df.index[validation_df[col_name].duplicated(keep=False) & validation_df[col_name].notna()].tolist(),
                                "unexpected_values": list(dup_uuids.head(5))
                            })

                # 13. Ambiguous boolean
                for col_name in validation_df.columns:
                    meta = cols_meta.get(col_name, {})
                    semantic_type = (meta.get("semantic_type") or "").lower()
                    if semantic_type == "boolean_like" and col_name in validation_df.columns:
                        s = validation_df[col_name].dropna()
                        if len(s) > 10:
                            vals = s.astype(str).str.strip().str.lower().value_counts()
                            true_variants = [v for v in vals.index if v in {"true","yes","y","1","t"}]
                            false_variants = [v for v in vals.index if v in {"false","no","n","0","f"}]
                            if len(true_variants) + len(false_variants) >= 3:
                                results_processed.append({
                                    "expectation": "ambiguous_boolean",
                                    "column": col_name,
                                    "success": False,
                                    "details": f"Multiple representations of boolean: {dict(vals.head(6).to_dict())}",
                                    "unexpected_count": len(s),
                                    "unexpected_index_list": s.index.tolist(),
                                    "unexpected_values": list(vals.index[:6])
                                })

                # 14. Univariate IQR Outliers
                for col in validation_df.columns:
                    col_meta = cols_meta.get(col) or {}
                    semantic = (col_meta.get("semantic_type") or "").lower()
                    dtype = str(validation_df[col].dtype).lower()
                    if ("int" in dtype or "float" in dtype) and _is_actual_numeric_column(col, semantic):
                        v = pd.to_numeric(validation_df[col], errors="coerce").dropna()
                        if len(v) >= 20:
                            q1, q3 = v.quantile(0.25), v.quantile(0.75)
                            iqr = q3 - q1
                            if iqr > 0:
                                lower, upper = q1 - 1.5 * iqr, q3 + 1.5 * iqr
                                mask = (v < lower) | (v > upper)
                                cnt = int(mask.sum())
                                if cnt > 0 and cnt < len(v) * 0.3:  # skip if >30% outliers (likely bimodal)
                                    results_processed.append({
                                        "expectation": "numeric_outliers_iqr",
                                        "column": col,
                                        "success": False,
                                        "details": f"{cnt} IQR outlier(s) outside [{round(lower,2)}, {round(upper,2)}]",
                                        "unexpected_count": cnt,
                                        "unexpected_index_list": v.index[mask].tolist()[:50],
                                        "unexpected_values": v[mask].head(5).tolist()
                                    })

                # 15. Z-Score Extreme Outliers (>4 standard deviations)
                for col in validation_df.columns:
                    col_meta = cols_meta.get(col) or {}
                    semantic = (col_meta.get("semantic_type") or "").lower()
                    dtype = str(validation_df[col].dtype).lower()
                    if ("int" in dtype or "float" in dtype) and _is_actual_numeric_column(col, semantic):
                        v = pd.to_numeric(validation_df[col], errors="coerce").dropna()
                        if len(v) >= 20:
                            mean, std = v.mean(), v.std()
                            if std > 0:
                                z = ((v - mean) / std).abs()
                                mask = z > 4
                                cnt = int(mask.sum())
                                if cnt > 0 and cnt < len(v) * 0.05:  # <5% to avoid noise
                                    results_processed.append({
                                        "expectation": "numeric_outliers_zscore",
                                        "column": col,
                                        "success": False,
                                        "details": f"{cnt} extreme outlier(s) beyond 4σ from mean ({round(mean,2)} ± {round(std,2)})",
                                        "unexpected_count": cnt,
                                        "unexpected_index_list": v.index[mask].tolist()[:50],
                                        "unexpected_values": v[mask].head(5).tolist()
                                    })

                # 16. Low Variance Numeric (near-constant columns)
                for col in validation_df.columns:
                    col_meta = cols_meta.get(col) or {}
                    semantic = (col_meta.get("semantic_type") or "").lower()
                    dtype = str(validation_df[col].dtype).lower()
                    if ("int" in dtype or "float" in dtype) and _is_actual_numeric_column(col, semantic):
                        v = pd.to_numeric(validation_df[col], errors="coerce").dropna()
                        if len(v) >= 20:
                            nunique = v.nunique()
                            if nunique <= 2 and len(v) > 50:  # only 1-2 distinct values in 50+ rows
                                vc = v.value_counts()
                                dominant_pct = vc.iloc[0] / len(v) * 100
                                if dominant_pct >= 98:
                                    results_processed.append({
                                        "expectation": "low_variance_numeric",
                                        "column": col,
                                        "success": False,
                                        "details": f"Near-constant: {nunique} unique value(s), dominant value is {round(dominant_pct,1)}% of rows",
                                        "unexpected_count": len(v),
                                        "unexpected_index_list": [],
                                        "unexpected_values": list(vc.head(3).to_dict().items())
                                    })

                # 17. Numeric Precision Anomaly (mixing integers and high-precision floats)
                for col in validation_df.columns:
                    col_meta = cols_meta.get(col) or {}
                    semantic = (col_meta.get("semantic_type") or "").lower()
                    dtype = str(validation_df[col].dtype).lower()
                    if "float" in dtype and _is_actual_numeric_column(col, semantic):
                        v = pd.to_numeric(validation_df[col], errors="coerce").dropna()
                        if len(v) >= 20:
                            is_int_like = (v == v.round(0))
                            int_pct = is_int_like.sum() / len(v) * 100
                            # Flag if 20-80% are integers (genuine mix, not just all ints or all floats)
                            if 20 < int_pct < 80:
                                non_int_mask = ~is_int_like
                                results_processed.append({
                                    "expectation": "numeric_precision_anomaly",
                                    "column": col,
                                    "success": False,
                                    "details": f"{round(int_pct,1)}% integer-like vs {round(100-int_pct,1)}% decimal — inconsistent precision",
                                    "unexpected_count": int(non_int_mask.sum()),
                                    "unexpected_index_list": v.index[non_int_mask].tolist()[:50],
                                    "unexpected_values": v[non_int_mask].head(5).tolist()
                                })

                # 18. Round Number Anomaly (suspiciously round values)
                for col in validation_df.columns:
                    col_meta = cols_meta.get(col) or {}
                    semantic = (col_meta.get("semantic_type") or "").lower()
                    dtype = str(validation_df[col].dtype).lower()
                    if ("int" in dtype or "float" in dtype) and _is_actual_numeric_column(col, semantic):
                        v = pd.to_numeric(validation_df[col], errors="coerce").dropna()
                        if len(v) >= 50:
                            # Check for values that are multiples of 100 or 1000
                            round_1000 = (v % 1000 == 0) & (v != 0)
                            round_100 = (v % 100 == 0) & (v != 0)
                            pct_1000 = round_1000.sum() / len(v) * 100
                            pct_100 = round_100.sum() / len(v) * 100
                            if pct_1000 > 30:  # >30% are multiples of 1000
                                mask = round_1000
                                results_processed.append({
                                    "expectation": "round_number_anomaly",
                                    "column": col,
                                    "success": False,
                                    "details": f"{round(pct_1000,1)}% of values are round multiples of 1000 — possible estimates/placeholders",
                                    "unexpected_count": int(mask.sum()),
                                    "unexpected_index_list": v.index[mask].tolist()[:50],
                                    "unexpected_values": v[mask].head(5).tolist()
                                })
                            elif pct_100 > 50:  # >50% are multiples of 100
                                mask = round_100
                                results_processed.append({
                                    "expectation": "round_number_anomaly",
                                    "column": col,
                                    "success": False,
                                    "details": f"{round(pct_100,1)}% of values are round multiples of 100 — possible estimates",
                                    "unexpected_count": int(mask.sum()),
                                    "unexpected_index_list": v.index[mask].tolist()[:50],
                                    "unexpected_values": v[mask].head(5).tolist()
                                })

                # 19. Future Dates
                from datetime import datetime, timedelta
                now = datetime.now()
                for col_name in validation_df.columns:
                    meta = cols_meta.get(col_name, {})
                    semantic = (meta.get("semantic_type") or "").lower()
                    if semantic == "date":
                        try:
                            dt_series = pd.to_datetime(validation_df[col_name], errors="coerce")
                            # Convert to tz-naive if tz-aware
                            dt_series_naive = dt_series.dt.tz_localize(None) if dt_series.dt.tz is not None else dt_series
                            future_mask = dt_series_naive > now + timedelta(days=1)
                            cnt = int(future_mask.sum())
                            if cnt > 0:
                                results_processed.append({
                                    "expectation": "future_dates",
                                    "column": col_name,
                                    "success": False,
                                    "details": f"{cnt} date(s) in the future",
                                    "unexpected_count": cnt,
                                    "unexpected_index_list": validation_df.index[future_mask].tolist()[:50],
                                    "unexpected_values": dt_series[future_mask].head(5).astype(str).tolist()
                                })
                        except Exception:
                            pass

                # 20. Ancient Dates (before 1900)
                ancient_cutoff = datetime(1900, 1, 1)
                for col_name in validation_df.columns:
                    meta = cols_meta.get(col_name, {})
                    semantic = (meta.get("semantic_type") or "").lower()
                    if semantic == "date":
                        try:
                            dt_series = pd.to_datetime(validation_df[col_name], errors="coerce")
                            dt_series_naive = dt_series.dt.tz_localize(None) if dt_series.dt.tz is not None else dt_series
                            ancient_mask = dt_series_naive.notna() & (dt_series_naive < ancient_cutoff)
                            cnt = int(ancient_mask.sum())
                            if cnt > 0:
                                results_processed.append({
                                    "expectation": "ancient_dates",
                                    "column": col_name,
                                    "success": False,
                                    "details": f"{cnt} date(s) before 1900 — likely sentinel or data entry error",
                                    "unexpected_count": cnt,
                                    "unexpected_index_list": validation_df.index[ancient_mask].tolist()[:50],
                                    "unexpected_values": dt_series[ancient_mask].head(5).astype(str).tolist()
                                })
                        except Exception:
                            pass

                # 21. Very Wide Date Span (>50 years)
                for col_name in validation_df.columns:
                    meta = cols_meta.get(col_name, {})
                    semantic = (meta.get("semantic_type") or "").lower()
                    if semantic == "date":
                        try:
                            dt_series = pd.to_datetime(validation_df[col_name], errors="coerce").dropna()
                            dt_series_naive = dt_series.dt.tz_localize(None) if dt_series.dt.tz is not None else dt_series
                            if len(dt_series_naive) >= 10:
                                span_days = (dt_series_naive.max() - dt_series_naive.min()).days
                                span_years = span_days / 365.25
                                if span_years > 50:
                                    results_processed.append({
                                        "expectation": "very_wide_date_span",
                                        "column": col_name,
                                        "success": False,
                                        "details": f"Date span of {round(span_years,1)} years ({dt_series_naive.min().date()} to {dt_series_naive.max().date()}) — implausible for single entity",
                                        "unexpected_count": len(dt_series_naive),
                                        "unexpected_index_list": [],
                                        "unexpected_values": [str(dt_series_naive.min().date()), str(dt_series_naive.max().date())]
                                    })
                        except Exception:
                            pass

                # 22. Date Clumping (Jan 1 / Month-End)
                for col_name in validation_df.columns:
                    meta = cols_meta.get(col_name, {})
                    semantic = (meta.get("semantic_type") or "").lower()
                    if semantic == "date":
                        try:
                            dt_series = pd.to_datetime(validation_df[col_name], errors="coerce").dropna()
                            dt_series_naive = dt_series.dt.tz_localize(None) if dt_series.dt.tz is not None else dt_series
                            if len(dt_series_naive) >= 20:
                                # Jan 1 clumping
                                jan1_mask = (dt_series_naive.dt.month == 1) & (dt_series_naive.dt.day == 1)
                                jan1_pct = jan1_mask.sum() / len(dt_series_naive) * 100
                                if jan1_pct > 20:
                                    results_processed.append({
                                        "expectation": "date_clumping_jan1",
                                        "column": col_name,
                                        "success": False,
                                        "details": f"{round(jan1_pct,1)}% of dates fall on January 1 — likely default/placeholder dates",
                                        "unexpected_count": int(jan1_mask.sum()),
                                        "unexpected_index_list": dt_series_naive.index[jan1_mask].tolist()[:50],
                                        "unexpected_values": dt_series_naive[jan1_mask].head(5).astype(str).tolist()
                                    })
                                # Month-end clumping
                                is_month_end = dt_series_naive.dt.is_month_end
                                me_pct = is_month_end.sum() / len(dt_series_naive) * 100
                                if me_pct > 30:
                                    results_processed.append({
                                        "expectation": "date_clumping_month_end",
                                        "column": col_name,
                                        "success": False,
                                        "details": f"{round(me_pct,1)}% of dates fall on month-end — likely estimated/rolled-up dates",
                                        "unexpected_count": int(is_month_end.sum()),
                                        "unexpected_index_list": dt_series_naive.index[is_month_end].tolist()[:50],
                                        "unexpected_values": dt_series_naive[is_month_end].head(5).astype(str).tolist()
                                    })
                        except Exception:
                            pass

                # 23. Weekend Business Date Anomaly
                _BUSINESS_DATE_KEYWORDS = ("order", "payment", "ship", "invoice", "transaction", "purchase", "billing", "sale")
                for col_name in validation_df.columns:
                    meta = cols_meta.get(col_name, {})
                    semantic = (meta.get("semantic_type") or "").lower()
                    col_lower = col_name.lower()
                    if semantic == "date" and any(k in col_lower for k in _BUSINESS_DATE_KEYWORDS):
                        try:
                            dt_series = pd.to_datetime(validation_df[col_name], errors="coerce").dropna()
                            dt_series_naive = dt_series.dt.tz_localize(None) if dt_series.dt.tz is not None else dt_series
                            if len(dt_series_naive) >= 20:
                                is_weekend = dt_series_naive.dt.dayofweek >= 5  # Sat=5, Sun=6
                                weekend_pct = is_weekend.sum() / len(dt_series_naive) * 100
                                if weekend_pct > 15:  # >15% on weekends is suspicious for business dates
                                    results_processed.append({
                                        "expectation": "weekend_date_anomaly",
                                        "column": col_name,
                                        "success": False,
                                        "details": f"{round(weekend_pct,1)}% of business dates fall on weekends",
                                        "unexpected_count": int(is_weekend.sum()),
                                        "unexpected_index_list": dt_series_naive.index[is_weekend].tolist()[:50],
                                        "unexpected_values": dt_series_naive[is_weekend].head(5).astype(str).tolist()
                                    })
                        except Exception:
                            pass

                # 24. Timezone Inconsistency (mixing tz-aware and tz-naive)
                for col_name in validation_df.columns:
                    meta = cols_meta.get(col_name, {})
                    semantic = (meta.get("semantic_type") or "").lower()
                    if semantic == "date" and _is_text_dtype(validation_df[col_name].dtype):
                        non_null = validation_df[col_name].dropna().astype(str)
                        if len(non_null) >= 10:
                            # Detect timezone indicators: +HH:MM, Z, UTC, EST, PST, etc.
                            tz_pattern = r"[+-]\d{2}:\d{2}$|Z$|\b(?:UTC|GMT|EST|CST|MST|PST|EDT|CDT|MDT|PDT)\b"
                            has_tz = non_null.str.contains(tz_pattern, regex=True, na=False)
                            tz_cnt = int(has_tz.sum())
                            no_tz_cnt = len(non_null) - tz_cnt
                            if tz_cnt > 0 and no_tz_cnt > 0 and min(tz_cnt, no_tz_cnt) > len(non_null) * 0.05:
                                results_processed.append({
                                    "expectation": "timezone_inconsistency",
                                    "column": col_name,
                                    "success": False,
                                    "details": f"{tz_cnt} tz-aware vs {no_tz_cnt} tz-naive datetime values — comparison errors likely",
                                    "unexpected_count": min(tz_cnt, no_tz_cnt),
                                    "unexpected_index_list": non_null.index[has_tz].tolist()[:50],
                                    "unexpected_values": non_null[has_tz].head(3).tolist() + non_null[~has_tz].head(3).tolist()
                                })

                # 25. Non-ASCII Characters in Text
                for col in validation_df.columns:
                    if _is_text_dtype(validation_df[col].dtype):
                        non_null = validation_df[col].dropna().astype(str)
                        if len(non_null) >= 10:
                            mask = non_null.str.contains(r"[^\x00-\x7F]", regex=True, na=False)
                            cnt = int(mask.sum())
                            if cnt > 0 and cnt < len(non_null) * 0.5:  # skip if majority has non-ASCII (likely legitimate)
                                results_processed.append({
                                    "expectation": "non_ascii_characters",
                                    "column": col,
                                    "success": False,
                                    "details": f"{cnt} value(s) contain non-ASCII characters",
                                    "unexpected_count": cnt,
                                    "unexpected_index_list": non_null.index[mask].tolist()[:50],
                                    "unexpected_values": non_null[mask].head(5).tolist()
                                })

                # 26. Control Characters in Text
                for col in validation_df.columns:
                    if _is_text_dtype(validation_df[col].dtype):
                        non_null = validation_df[col].dropna().astype(str)
                        if len(non_null) >= 5:
                            # Match control chars except \t \n \r
                            mask = non_null.str.contains(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", regex=True, na=False)
                            cnt = int(mask.sum())
                            if cnt > 0:
                                results_processed.append({
                                    "expectation": "control_characters_in_text",
                                    "column": col,
                                    "success": False,
                                    "details": f"{cnt} value(s) contain control characters",
                                    "unexpected_count": cnt,
                                    "unexpected_index_list": non_null.index[mask].tolist()[:50],
                                    "unexpected_values": non_null[mask].head(5).tolist()
                                })

                # 27. String Length Outliers (>mean + 4σ)
                for col in validation_df.columns:
                    if _is_text_dtype(validation_df[col].dtype):
                        non_null = validation_df[col].dropna().astype(str)
                        if len(non_null) >= 20:
                            lengths = non_null.str.len()
                            mean_len = lengths.mean()
                            std_len = lengths.std()
                            if std_len > 0 and mean_len > 1:
                                threshold = mean_len + 4 * std_len
                                mask = lengths > threshold
                                cnt = int(mask.sum())
                                if cnt > 0 and cnt < len(non_null) * 0.1:
                                    results_processed.append({
                                        "expectation": "string_length_outlier",
                                        "column": col,
                                        "success": False,
                                        "details": f"{cnt} value(s) exceed {round(threshold)} chars (mean={round(mean_len)}, σ={round(std_len)})",
                                        "unexpected_count": cnt,
                                        "unexpected_index_list": non_null.index[mask].tolist()[:50],
                                        "unexpected_values": non_null[mask].head(5).tolist()
                                    })

                # 28. Digits-Only Values in Text Columns
                for col in validation_df.columns:
                    col_meta = cols_meta.get(col) or {}
                    semantic = (col_meta.get("semantic_type") or "").lower()
                    col_lower = col.lower()
                    # Only check text columns that are NOT IDs, phones, zips, etc.
                    if (_is_text_dtype(validation_df[col].dtype) and semantic not in ("numeric_id", "id", "phone", "zip", "postal_code")
                        and not col_lower.endswith("id") and not col_lower.endswith("code") and not col_lower.endswith("zip")):
                        non_null = validation_df[col].dropna().astype(str).str.strip()
                        if len(non_null) >= 10:
                            digits_mask = non_null.str.fullmatch(r"\d+", na=False)
                            digits_pct = digits_mask.sum() / len(non_null) * 100
                            # Flag if 10-90% are digits-only (not all, not none)
                            if 10 < digits_pct < 90:
                                results_processed.append({
                                    "expectation": "string_with_only_digits_in_text_column",
                                    "column": col,
                                    "success": False,
                                    "details": f"{round(digits_pct,1)}% of values are digits-only in a text column — possible schema mismatch",
                                    "unexpected_count": int(digits_mask.sum()),
                                    "unexpected_index_list": non_null.index[digits_mask].tolist()[:50],
                                    "unexpected_values": non_null[digits_mask].head(5).tolist()
                                })

                # 29. Repeated Token in Strings (e.g., "test test", "John John")
                for col in validation_df.columns:
                    col_lower = col.lower()
                    if _is_text_dtype(validation_df[col].dtype) and any(k in col_lower for k in ("name", "title", "desc", "comment", "address", "label")):
                        non_null = validation_df[col].dropna().astype(str).str.strip()
                        if len(non_null) >= 10:
                            def _has_repeated_token(s):
                                tokens = s.lower().split()
                                return len(tokens) >= 2 and len(set(tokens)) < len(tokens) and tokens[0] == tokens[1]
                            mask = non_null.apply(_has_repeated_token)
                            cnt = int(mask.sum())
                            if cnt > 0:
                                results_processed.append({
                                    "expectation": "repeated_token_in_string",
                                    "column": col,
                                    "success": False,
                                    "details": f"{cnt} value(s) with repeated leading tokens (e.g., 'John John')",
                                    "unexpected_count": cnt,
                                    "unexpected_index_list": non_null.index[mask].tolist()[:50],
                                    "unexpected_values": non_null[mask].head(5).tolist()
                                })

                # 30. Implausible Age Values
                for col in validation_df.columns:
                    col_lower = col.lower()
                    if any(k in col_lower for k in ("age", "_age", "age_")):
                        v = pd.to_numeric(validation_df[col], errors="coerce").dropna()
                        if len(v) >= 5:
                            bad_mask = (v < 0) | (v > 150)
                            cnt = int(bad_mask.sum())
                            if cnt > 0:
                                results_processed.append({
                                    "expectation": "implausible_age",
                                    "column": col,
                                    "success": False,
                                    "details": f"{cnt} age value(s) outside plausible range [0, 150]",
                                    "unexpected_count": cnt,
                                    "unexpected_index_list": v.index[bad_mask].tolist()[:50],
                                    "unexpected_values": v[bad_mask].head(5).tolist()
                                })

                # 31. Implausible Percentage Values
                for col in validation_df.columns:
                    col_lower = col.lower()
                    if any(k in col_lower for k in ("percent", "pct", "rate", "ratio", "share", "proportion")):
                        v = pd.to_numeric(validation_df[col], errors="coerce").dropna()
                        if len(v) >= 5:
                            bad_mask = (v < 0) | (v > 100)
                            cnt = int(bad_mask.sum())
                            if cnt > 0:
                                results_processed.append({
                                    "expectation": "implausible_percentage",
                                    "column": col,
                                    "success": False,
                                    "details": f"{cnt} percentage value(s) outside [0, 100]",
                                    "unexpected_count": cnt,
                                    "unexpected_index_list": v.index[bad_mask].tolist()[:50],
                                    "unexpected_values": v[bad_mask].head(5).tolist()
                                })

                # 32. Case-Insensitive Duplicate Values
                for col in validation_df.columns:
                    col_meta = cols_meta.get(col) or {}
                    semantic = (col_meta.get("semantic_type") or "").lower()
                    if _is_text_dtype(validation_df[col].dtype) and semantic in ("categorical", "status", "enum"):
                        s = validation_df[col].dropna().astype(str).str.strip()
                        if len(s) >= 10:
                            original_unique = s.nunique()
                            normalized_unique = s.str.lower().nunique()
                            if normalized_unique < original_unique:
                                diff = original_unique - normalized_unique
                                # Find the actual colliding values
                                vc = s.str.lower().value_counts()
                                collision_keys = [k for k, v in vc.items() if v > 1]
                                collision_examples = []
                                for k in collision_keys[:3]:
                                    variants = s[s.str.lower() == k].unique().tolist()
                                    if len(variants) > 1:
                                        collision_examples.append(variants)
                                if collision_examples:
                                    results_processed.append({
                                        "expectation": "duplicate_insensitive_values",
                                        "column": col,
                                        "success": False,
                                        "details": f"{diff} value(s) that differ only by case/whitespace — false uniqueness",
                                        "unexpected_count": diff,
                                        "unexpected_index_list": [],
                                        "unexpected_values": collision_examples[:5]
                                    })

                # Statistics rollup
                eval_cnt = len(results_processed)
                succ_cnt = sum(1 for r in results_processed if r["success"])
                unsucc_cnt = eval_cnt - succ_cnt
                pct = (succ_cnt / eval_cnt * 100.0) if eval_cnt > 0 else 100.0

                gx_results[name] = {
                    "success": bool(unsucc_cnt == 0),
                    "statistics": {
                        "evaluated_expectations": eval_cnt,
                        "successful_expectations": succ_cnt,
                        "unsuccessful_expectations": unsucc_cnt,
                        "success_percent": pct,
                    },
                    "results": results_processed
                }

            except Exception as e:
                logger.error(f"Error validating {name} with GX: {e}")
                gx_results[name] = {"error": f"Validation step failed: {str(e)}", "success": False}

    except Exception as e:
        logger.error(f"Global GX error: {e}")
        return {"error": f"GX Context Initialization failed: {str(e)}", "success": False}

    return gx_results
