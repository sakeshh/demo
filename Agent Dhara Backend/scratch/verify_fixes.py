import pandas as pd
import great_expectations as gx
import logging
import sys
import os

# Add parent dir to path to import local modules if needed
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def verify_fixes():
    print("--- Verifying GX Fix ---")
    df = pd.DataFrame({'a': [1, 2, 3], 'b': [4, 5, 6]})
    context = gx.get_context()
    
    datasource_name = "verify_ds"
    asset_name = "verify_asset"
    suite_name = "verify_suite"
    
    # Setup Suite
    try:
        suite = context.suites.add(gx.ExpectationSuite(name=suite_name))
    except Exception:
        suite = context.suites.get(suite_name)
        
    # Setup DS and Asset
    try:
        datasource = context.data_sources.add_pandas(name=datasource_name)
    except Exception:
        datasource = context.data_sources.get(datasource_name)
        
    try:
        asset = datasource.add_dataframe_asset(name=asset_name)
    except Exception:
        asset = datasource.get_asset(asset_name)
        
    # Test the fix logic (simplified version of what's in gx_validation_specialist.py)
    try:
        batch_definition_name = "verify_batch_def"
        try:
            batch_definition = asset.add_batch_definition_whole_dataframe(batch_definition_name)
        except Exception:
            batch_definition = asset.get_batch_definition(batch_definition_name)
        
        validator = context.get_validator(
            batch_definition=batch_definition,
            batch_parameters={"dataframe": df},
            expectation_suite_name=suite_name,
        )
        print("SUCCESS: GX Validator created successfully with Batch Definition.")
        validator.expect_column_values_to_not_be_null("a")
        res = validator.validate()
        print(f"Validation success: {res.success}")
    except Exception as e:
        print(f"FAILED: GX fix verification failed: {e}")
        import traceback
        traceback.print_exc()

    print("\n--- Verifying NameError Fix ---")
    try:
        from agent.intelligent_data_assessment import analyze_column
        # We just need to call it and see if it hits a NameError
        # analyze_column(series, col, semantic, thresholds)
        s = pd.Series([1, 2, None, 0])
        issues = analyze_column(s, "test_col", "numeric_id")
        print(f"SUCCESS: analyze_column executed without NameError. Found {len(issues)} issues.")
        for issue in issues:
            print(f"  - {issue['type']}: {issue['message']}")
    except NameError as e:
        print(f"FAILED: NameError still present: {e}")
    except Exception as e:
        print(f"FAILED: analyze_column failed with other error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    verify_fixes()
