import urllib.request
import json
import os
from dotenv import load_dotenv

backend_dir = r"c:\Users\ssakesh\Documents\DHARA-GX\Agent Dhara Backend"
dotenv_path = os.path.join(backend_dir, ".env")
load_dotenv(dotenv_path)

token = os.getenv("BACKEND_AUTH_TOKEN", "change-me-dev")

url = "http://127.0.0.1:8000/etl/test-connection"
headers = {
    "Content-Type": "application/json",
    "X-Backend-Token": token
}
data = json.dumps({"connection_string": None}).encode("utf-8")

req = urllib.request.Request(url, data=data, headers=headers, method="POST")
try:
    with urllib.request.urlopen(req) as response:
        res = json.loads(response.read().decode())
        print("Backend Test Connection Response:", json.dumps(res, indent=2))
except Exception as e:
    print("Failed to contact backend:", e)
