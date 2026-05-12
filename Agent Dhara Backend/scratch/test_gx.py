import sys
import os
sys.path.append(os.getcwd())
import pandas as pd
from agent.specialists.gx_validation_specialist import run_gx_validation
import logging

logging.basicConfig(level=logging.INFO)

def test_gx():
    df = pd.DataFrame({
        "id": [1, 2, 3, 4],
        "email": ["test@example.com", "foo@bar.com", "invalid-email", None],
        "value": [10.5, 20.0, 30.2, 40.1]
    })
    
    datasets = {"test_data": df}
    profile_results = {
        "datasets": {
            "test_data": {
                "columns": {
                    "id": {"null_percentage": 0, "candidate_primary_key": True, "dtype": "int64"},
                    "email": {"null_percentage": 0.25, "semantic_type": "email", "dtype": "object"},
                    "value": {"null_percentage": 0, "dtype": "float64"}
                }
            }
        }
    }
    
    print("Running GX validation...")
    results = run_gx_validation(datasets, profile_results)
    print("Results:", results)

if __name__ == "__main__":
    test_gx()
