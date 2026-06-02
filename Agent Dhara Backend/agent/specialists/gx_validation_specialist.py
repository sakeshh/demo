import pandas as pd
import great_expectations as gx
from typing import Dict, Any, List, Optional
import logging

logger = logging.getLogger(__name__)

def run_gx_validation(datasets: Dict[str, pd.DataFrame], profile_results: Dict[str, Any]) -> Dict[str, Any]:
    """
    Runs dynamic Great Expectations validation on the provided datasets.
    Supports both GX 0.x and 1.x API patterns.
    """
    gx_results = {}
    
    try:
        # Get a GX context (returns Ephemeral context if no config found)
        context = gx.get_context()
        
        for name, df in datasets.items():
            if df is None or (isinstance(df, pd.DataFrame) and df.empty):
                continue
                
            dataset_safe_name = name.replace('.', '_').replace('/', '_').replace('\\', '_')
            datasource_name = f"ds_{dataset_safe_name}"
            asset_name = f"asset_{dataset_safe_name}"
            suite_name = f"suite_{dataset_safe_name}"

            # --- Intelligent Sampling for GX Performance ---
            # GX validation is compute-intensive (especially uniqueness and distribution checks).
            # We sample to 500k rows if the dataset is larger than 1M to prevent job timeouts.
            GX_SAMPLING_THRESHOLD = 1_000_000
            GX_SAMPLE_SIZE = 500_000
            
            validation_df = df
            if len(df) > GX_SAMPLING_THRESHOLD:
                logger.info(f"Sampling {name} ({len(df)} rows) to {GX_SAMPLE_SIZE} for GX deep audit performance.")
                validation_df = df.sample(n=GX_SAMPLE_SIZE, random_state=42)
            
            try:
                # 1. Handle Data Source (Fluent API v0.17+ / v1.0+)
                datasource = None
                if hasattr(context, "data_sources"): # GX 1.0+
                    try:
                        datasource = context.data_sources.add_pandas(name=datasource_name)
                    except Exception:
                        datasource = context.data_sources.get(datasource_name)
                elif hasattr(context, "sources"): # GX 0.17+
                    try:
                        datasource = context.sources.add_pandas(name=datasource_name)
                    except Exception:
                        datasource = context.sources.get(datasource_name)
                
                if not datasource:
                    # Fallback for older or weirdly configured contexts
                    logger.warning(f"Could not initialize datasource {datasource_name}")
                    continue

                asset = None
                try:
                    asset = datasource.add_dataframe_asset(name=asset_name)
                except Exception:
                    asset = datasource.get_asset(asset_name)
                
                # 2. Handle Expectation Suite
                suite = None
                if hasattr(context, "suites"): # GX 1.0+
                    try:
                        suite = context.suites.add(gx.ExpectationSuite(name=suite_name))
                    except Exception:
                        suite = context.suites.get(suite_name)
                else: # GX 0.x
                    try:
                        suite = context.add_expectation_suite(expectation_suite_name=suite_name)
                    except Exception:
                        suite = context.get_expectation_suite(expectation_suite_name=suite_name)

                # 3. Get the profile for this specific dataset to drive expectations
                ds_profile = (profile_results.get("datasets") or {}).get(name) or {}
                cols_meta = ds_profile.get("columns") or {}
                
                # 4. Create the validator
                try:
                    # GX 1.x Fluent API pattern: uses Batch Definitions for in-memory data
                    batch_definition_name = f"batch_def_{dataset_safe_name}"
                    try:
                        batch_definition = asset.add_batch_definition_whole_dataframe(batch_definition_name)
                    except Exception:
                        batch_definition = asset.get_batch_definition(batch_definition_name)
                    
                    batch = batch_definition.get_batch(batch_parameters={"dataframe": validation_df})
                    validator = context.get_validator(
                        batch=batch,
                        expectation_suite_name=suite_name,
                    )
                except (AttributeError, TypeError, Exception) as original_error:
                    # Fallback for older GX versions (0.17 - 0.18) or if Batch Definition fails
                    logger.warning(f"Batch Definition pattern failed, falling back to legacy for {name}. Original error: {original_error}")
                    batch_request = asset.build_batch_request(**{"dataframe": validation_df})
                    validator = context.get_validator(
                        batch_request=batch_request,
                        expectation_suite_name=suite_name,
                    )
                
                # --- Dynamic Expectation Generation (Maximalist Approach) ---
                
                # A. Table Level Metrics
                validator.expect_table_columns_to_match_ordered_list(column_list=list(validation_df.columns))
                validator.expect_table_row_count_to_be_between(min_value=len(validation_df), max_value=len(validation_df))
                
                for col_name, meta in cols_meta.items():
                    if col_name not in validation_df.columns:
                        continue
                    
                    s = validation_df[col_name]
                    dtype = str(s.dtype).lower()
                    semantic_type = (meta.get("semantic_type") or "unknown").lower()
                    
                    # 1. Nullity Checks (Strict)
                    null_pct = meta.get("null_percentage", 0)
                    if null_pct == 0:
                        validator.expect_column_values_to_not_be_null(column=col_name)
                    else:
                        # Enforce current quality with no buffer
                        validator.expect_column_values_to_not_be_null(column=col_name, mostly=1.0 - null_pct)
                    
                    # 2. Uniqueness Checks
                    if meta.get("candidate_primary_key"):
                        validator.expect_column_values_to_be_unique(column=col_name)
                        
                    # 3. Type Checks
                    if "int" in dtype:
                        validator.expect_column_values_to_be_in_type_list(column=col_name, type_list=["int64", "int32", "int", "Int64"])
                    elif "float" in dtype or "decimal" in dtype:
                        validator.expect_column_values_to_be_in_type_list(column=col_name, type_list=["float64", "float32", "float"])
                    
                    # 4. Numeric Range & Distribution (Strict)
                    if "int" in dtype or "float" in dtype:
                        v = s.dropna()
                        if not v.empty:
                            # Bound checks
                            v_min = v.min()
                            v_max = v.max()
                            validator.expect_column_values_to_be_between(column=col_name, min_value=v_min, max_value=v_max)
                            
                            # Aggregate stats (with tight 10% tolerance for drift detection)
                            m = v.mean()
                            validator.expect_column_mean_to_be_between(column=col_name, min_value=m * 0.9, max_value=m * 1.1)
                            
                            try:
                                med = v.median()
                                validator.expect_column_median_to_be_between(column=col_name, min_value=med * 0.8, max_value=med * 1.2)
                            except Exception: pass

                    # 5. String Lengths & Patterns
                    if dtype == "object" or "str" in dtype:
                        # Categorical / Set Membership
                        uq_count = meta.get("unique_count", 0)
                        if 0 < uq_count <= 25: # Treat low cardinality as enums
                            try:
                                value_set = [str(x) for x in s.dropna().unique() if x is not None]
                                validator.expect_column_values_to_be_in_set(column=col_name, value_set=value_set)
                            except Exception: pass
                            
                        # Length constraints
                        try:
                            lens = s.dropna().astype(str).str.len()
                            if not lens.empty:
                                validator.expect_column_value_lengths_to_be_between(
                                    column=col_name, 
                                    min_value=int(lens.min()), 
                                    max_value=int(lens.max())
                                )
                        except Exception: pass
                        
                        # Semantic Patterns
                        if semantic_type == "email":
                            validator.expect_column_values_to_match_regex(column=col_name, regex=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
                        elif semantic_type == "phone":
                            validator.expect_column_values_to_match_regex(column=col_name, regex=r"^[+()\-\.\s0-9]{7,}$")
                        elif semantic_type in ("uuid", "guid"):
                            try:
                                validator.expect_column_values_to_match_regex(
                                    column=col_name,
                                    regex=r"(?i)^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
                                )
                            except Exception:
                                pass
                    
                    # 6. Dates
                    if semantic_type == "date":
                        if "datetime" not in dtype and "timestamp" not in dtype:
                            try:
                                validator.expect_column_values_to_be_dateutil_parseable(column=col_name)
                            except Exception: pass
                        
                        try:
                            # Convert to series of strings for the range check if needed, 
                            # or use the parsed values if available.
                            v_dates = pd.to_datetime(s, errors="coerce").dropna()
                            if not v_dates.empty:
                                validator.expect_column_values_to_be_between(
                                    column=col_name, 
                                    min_value=v_dates.min().isoformat(), 
                                    max_value=v_dates.max().isoformat()
                                )
                        except Exception: pass
                
                # 5. Execute validation
                validation_result = validator.validate()
                
                # 6. Extract results for frontend
                results_processed = []
                # Handle results being either list of result objects or dict
                if isinstance(validation_result, dict):
                    res_list = validation_result.get("results", [])
                else:
                    res_list = getattr(validation_result, "results", [])
                
                for r in res_list:
                    # Safely get expectation type and column
                    exp_type = "unknown"
                    col = "-"
                    
                    # 1. Try object-style access
                    cfg = getattr(r, "expectation_config", None)
                    if cfg:
                        # Extract expectation type with fallbacks
                        if isinstance(cfg, dict):
                            exp_type = cfg.get("expectation_type") or cfg.get("type") or cfg.get("name") or "unknown"
                            col = cfg.get("kwargs", {}).get("column", "-")
                        else:
                            exp_type = getattr(cfg, "expectation_type", None) or getattr(cfg, "type", None) or getattr(cfg, "name", "unknown")
                            kwargs = getattr(cfg, "kwargs", {})
                            if isinstance(kwargs, dict):
                                col = kwargs.get("column", "-")
                            else:
                                col = getattr(kwargs, "column", "-")
                    
                    # 2. Try dict-style access if object style failed or returned unknown
                    if (not exp_type or exp_type == "unknown") and isinstance(r, dict):
                        cfg_dict = r.get("expectation_config", {})
                        exp_type = cfg_dict.get("expectation_type") or cfg_dict.get("type") or cfg_dict.get("name") or "unknown"
                        col = cfg_dict.get("kwargs", {}).get("column", "-")
                    
                    # 3. Last resort: try to get it from the result object itself if available
                    if (not exp_type or exp_type == "unknown"):
                        exp_type = getattr(r, "expectation_type", "unknown")

                    # Ensure exp_type is a string and cleanup
                    exp_type_str = str(exp_type).replace("expect_", "").replace("_", " ")
                    if not exp_type_str or exp_type_str.lower() == "unknown":
                        exp_type_str = "Validation Rule"

                    details = "All values meet the expectation."
                    if isinstance(r, dict):
                        success = r.get("success", False)
                        res_obj = r.get("result", {})
                    else:
                        success = getattr(r, "success", False)
                        res_obj = getattr(r, "result", {})

                    if not success:
                        if isinstance(res_obj, dict):
                            unexp = res_obj.get("unexpected_count")
                            pct = res_obj.get("unexpected_percent")
                        else:
                            unexp = getattr(res_obj, "unexpected_count", None)
                            pct = getattr(res_obj, "unexpected_percent", None)

                        if unexp is not None:
                            details = f"Found {unexp} invalid values"
                            if pct is not None:
                                details += f" ({round(pct, 2)}%)"
                        else:
                            details = "Validation failed for some values."

                    results_processed.append({
                        "expectation": exp_type_str,
                        "column": col,
                        "success": bool(success),
                        "details": details
                    })

                # Safely get statistics
                if isinstance(validation_result, dict):
                    stats = validation_result.get("statistics", {})
                else:
                    stats = getattr(validation_result, "statistics", {})
                gx_results[name] = {
                    "success": bool(getattr(validation_result, "success", False)),
                    "statistics": {
                        "evaluated_expectations": stats.get("evaluated_expectations", 0),
                        "successful_expectations": stats.get("successful_expectations", 0),
                        "unsuccessful_expectations": stats.get("unsuccessful_expectations", 0),
                        "success_percent": stats.get("success_percent", 0),
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
