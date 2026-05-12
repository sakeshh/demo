import pandas as pd
import great_expectations as gx
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def test_gx_api():
    df = pd.DataFrame({'a': [1, 2, 3], 'b': [4, 5, 6]})
    context = gx.get_context()
    
    datasource_name = "test_datasource"
    asset_name = "test_asset"
    suite_name = "test_suite"
    
    try:
        datasource = context.data_sources.add_pandas(name=datasource_name)
    except Exception:
        datasource = context.data_sources.get(datasource_name)
        
    try:
        asset = datasource.add_dataframe_asset(name=asset_name)
    except Exception:
        asset = datasource.get_asset(asset_name)
        
    print(f"Asset type: {type(asset)}")
    print(f"Asset methods: {[m for m in dir(asset) if 'batch' in m.lower()]}")
    
    try:
        # Try the 1.x way
        batch_definition = None
        try:
            batch_definition = asset.add_batch_definition_whole_dataframe("test_batch_def")
        except Exception as e:
            print(f"add_batch_definition_whole_dataframe failed: {e}")
            try:
                batch_definition = asset.get_batch_definition("test_batch_def")
            except Exception as e2:
                print(f"get_batch_definition failed: {e2}")

        if batch_definition:
            print("Successfully got batch_definition")
            validator = context.get_validator(
                batch_definition=batch_definition,
                batch_parameters={"dataframe": df},
                expectation_suite_name=suite_name
            )
            print("Successfully got validator")
        else:
            # Try older build_batch_request
            try:
                batch_request = asset.build_batch_request(dataframe=df)
                print("Successfully called build_batch_request(dataframe=df)")
            except Exception as e:
                print(f"build_batch_request(dataframe=df) failed: {e}")
                
    except Exception as e:
        print(f"Global error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_gx_api()
