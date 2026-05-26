import requests
import json

url = "http://127.0.0.1:3000/api/etl/infer-semantics"
payload = {
    "sources": ["dbo.courses_raw", "dbo.students_raw"]
}

try:
    print("Calling frontend proxy endpoint on 127.0.0.1:3000 with 120s timeout...")
    response = requests.post(url, json=payload, timeout=120)
    print("Status Code:", response.status_code)
    try:
        print("Response Body JSON:", json.dumps(response.json(), indent=2))
    except Exception:
        print("Response Body Text:", response.text)
except Exception as e:
    print("Error calling endpoint:", e)
