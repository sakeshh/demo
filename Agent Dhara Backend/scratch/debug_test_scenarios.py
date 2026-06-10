import os
import json
import pandas as pd
import sys

# Adjust path to import agent
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from agent.intelligent_data_assessment import profile_dataframe, analyze_dataset_quality, load_dq_thresholds
from agent.etl_pipeline.dq_gate import check_dq_gate

def debug():
    fixtures_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../tests/etl_scenarios/fixtures"))
    thresholds = load_dq_thresholds()
    
    # Load mixed_dq_rating
    path = os.path.join(fixtures_dir, "mixed_dq_rating.json")
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    df = pd.DataFrame(data)
    
    print("DataFrame shape:", df.shape)
    print(df.head())
    
    profile = profile_dataframe(df)
    dq = analyze_dataset_quality("dbo.mixed_dq", df, profile, thresholds, business_rules=None)
    profile["quality"] = dq
    
    assessment = {
        "datasets": {
            "dbo.mixed_dq": profile
        }
    }
    
    gate_res = check_dq_gate(assessment, "dbo.mixed_dq", threshold=70.0)
    print("\nGate Result:", gate_res)
    print("Scorecard:", dq.get("scorecard"))
    print("Issues count:", len(dq.get("issues", [])))
    for issue in dq.get("issues", []):
        print(issue)

if __name__ == "__main__":
    debug()
