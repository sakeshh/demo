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
    print("--- Verifying GX Fix (Revised) ---")
    df = pd.DataFrame({'a': [1, 2, 3], 'b': [4, 5, 6]})
    context = gx.get_context()
    
    datasource_name = "verify_ds_2"
    asset_name = "verify_asset_2"
    suite_name = "verify_suite_2"
    
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
        
    try:
        batch_definition_name = "verify_batch_def_2"
        try:
            batch_definition = asset.add_batch_definition_whole_dataframe(batch_definition_name)
        except Exception:
            batch_definition = asset.get_batch_definition(batch_definition_name)
        
        # Get the batch first
        batch = batch_definition.get_batch(batch_parameters={"dataframe": df})
        print("Successfully got batch object.")
        
        # Pass the batch object to get_validator
        validator = context.get_validator(
            batch=batch,
            expectation_suite_name=suite_name,
        )
        print("SUCCESS: GX Validator created successfully with Batch object.")
        validator.expect_column_values_to_not_be_null("a")
        res = validator.validate()
        print(f"Validation success: {res.success}")
    except Exception as e:
        print(f"FAILED: GX fix verification failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    verify_fixes()
