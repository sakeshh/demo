import sys
import os
import requests
import json
import time

url = "http://127.0.0.1:8000/jobs"
headers = {
    "X-Backend-Token": "change-me-dev",
    "Content-Type": "application/json"
}

payload = {
    "kind": "chat",
    "input": {
        "session_id": "8c23e2f7-9dce-4efe-a4b0-69827eb9e9f9",
        "threadId": "8c23e2f7-9dce-4efe-a4b0-69827eb9e9f9",
        "message": "blob",
        "gx_enabled": False
    }
}

try:
    print("Creating job...")
    res = requests.post(url, headers=headers, json=payload)
    print(f"Status: {res.status_code}")
    print(res.text)
    if res.status_code == 200:
        job_id = res.json().get("job_id")
        print(f"Job ID: {job_id}")
        for _ in range(20):
            time.sleep(0.5)
            status_res = requests.get(f"http://127.0.0.1:8000/jobs/{job_id}", headers=headers)
            job_data = status_res.json().get("job", {})
            status = job_data.get("status")
            print(f"Checking job: status={status}")
            if status in ("succeeded", "failed"):
                print("Result:")
                print(json.dumps(job_data.get("result"), indent=2))
                print("Error:")
                print(job_data.get("error"))
                break
except Exception as e:
    print("Error:", e)
