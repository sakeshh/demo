import pandas as pd
import great_expectations as gx
import logging
import sys
import os

# Add parent dir to path to import local modules
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from agent.specialists.gx_validation_specialist import run_gx_validation

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def verify_maximalist():
    print("--- Verifying Maximalist GX Logic ---")
    df = pd.DataFrame({
        'id': [1, 2, 3, 4, 5],
        'age': [25, 30, 35, 40, 45],
        'email': ['a@b.com', 'c@d.com', 'e@f.com', 'g@h.com', 'i@j.com'],
        'status': ['active', 'inactive', 'active', 'active', 'inactive'],
        'joined': pd.to_datetime(['2023-01-01', '2023-02-01', '2023-03-01', '2023-04-01', '2023-05-01'])
    })
    
    # Mock profile results
    profile_results = {
        "datasets": {
            "users": {
                "columns": {
                    "id": {"null_percentage": 0.0, "candidate_primary_key": True, "unique_count": 5, "semantic_type": "numeric_id"},
                    "age": {"null_percentage": 0.0, "candidate_primary_key": False, "unique_count": 5, "semantic_type": "numeric"},
                    "email": {"null_percentage": 0.0, "candidate_primary_key": True, "unique_count": 5, "semantic_type": "email"},
                    "status": {"null_percentage": 0.0, "candidate_primary_key": False, "unique_count": 2, "semantic_type": "categorical"},
                    "joined": {"null_percentage": 0.0, "candidate_primary_key": False, "unique_count": 5, "semantic_type": "date"}
                }
            }
        }
    }
    
    datasets = {"users": df}
    
    results = run_gx_validation(datasets, profile_results)
    
    if "users" in results:
        res = results["users"]
        stats = res.get("statistics", {})
        print(f"Evaluated expectations: {stats.get('evaluated_expectations')}")
        print(f"Successful expectations: {stats.get('successful_expectations')}")
        print(f"Success: {res.get('success')}")
        
        if stats.get('evaluated_expectations', 0) > 10:
            print("SUCCESS: Large number of expectations generated.")
        else:
            print(f"WARNING: Only {stats.get('evaluated_expectations')} expectations generated.")
            
        # Print some expectations to see
        for r in res.get("results", [])[:10]:
            print(f"  - {r['expectation']} ({r['column']}): {r['success']}")
    else:
        print(f"FAILED: No results for 'users'. Results: {results}")

if __name__ == "__main__":
    verify_maximalist()
