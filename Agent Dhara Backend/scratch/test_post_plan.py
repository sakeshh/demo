import requests
import json
import time

url = "http://127.0.0.1:8000/etl/plan"
headers = {
    "Content-Type": "application/json",
    "X-Backend-Token": "change-me-dev"
}

# Fetch the actual assessment result from the session database to simulate the exact payload
from agent.session_store import load_session
sess = load_session("8c23e2f7-9dce-4efe-a4b0-69827eb9e9f9")
assessment = sess.get("context", {}).get("last_assessment_result")

payload = {
  "session_id": "8c23e2f7-9dce-4efe-a4b0-69827eb9e9f9",
  "business_rules": {
    "never_drop_rows": False,
    "required_columns": [],
    "exclude_columns": [],
    "outlier_strategy": "flag",
    "notes": "",
    "dq_threshold": 70,
    "generation_mode": "full",
    "force_unlock": [],
    "semantic_overrides": {},
    "scd": {}
  },
  "engine": "python",
  "codegen_engine": "python",
  "sql_dialect": "tsql",
  "target_destination": "dataframe_only",
  "tenant_id": "default",
  "engine_user_override": False,
  "generation_mode": "full",
  "assessment_result": assessment
}

print("Payload size (chars):", len(json.dumps(payload)))

t0 = time.time()
resp = requests.post(url, headers=headers, json=payload)
print("Response status:", resp.status_code)
print("Elapsed time:", time.time() - t0)
if resp.status_code == 200:
    data = resp.json()
    print("Response keys:", list(data.keys()))
    print("Plan steps count:", len(data.get("plan", {}).get("datasets", {}).get("dbo.courses_raw", {}).get("steps", [])))
else:
    print("Response content:", resp.text[:500])
