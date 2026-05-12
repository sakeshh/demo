import requests
import time
import json

BASE_URL = "http://127.0.0.1:8000"

def test_gx_job():
    payload = {
        "kind": "chat",
        "input": {
            "session_id": "test_session",
            "message": "list files",
            "gx_enabled": True
        }
    }
    
    print("Creating job...")
    res = requests.post(f"{BASE_URL}/jobs", json=payload)
    if res.status_code != 200:
        print(f"Error: {res.text}")
        return
    
    job_id = res.json()["job_id"]
    print(f"Job ID: {job_id}")
    
    while True:
        res = requests.get(f"{BASE_URL}/jobs/{job_id}")
        job = res.json()["job"]
        status = job["status"]
        print(f"Status: {status}")
        
        if status == "succeeded":
            result = job["result"]
            print("Job succeeded!")
            print(f"Result keys: {list(result.keys())}")
            if "gx_results" in result:
                print("GX RESULTS FOUND!")
                print(json.dumps(result["gx_results"], indent=2))
            else:
                print("GX RESULTS MISSING!")
            break
        elif status == "failed":
            print(f"Job failed: {job['error']}")
            break
        
        time.sleep(1)

if __name__ == "__main__":
    test_gx_job()
