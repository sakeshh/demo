import urllib.request
import json
import os
from dotenv import load_dotenv

backend_dir = r"c:\Users\ssakesh\Documents\DHARA-GX\Agent Dhara Backend"
dotenv_path = os.path.join(backend_dir, ".env")
load_dotenv(dotenv_path)

token = os.getenv("BACKEND_AUTH_TOKEN", "change-me-dev")

url = "http://127.0.0.1:8000/debug/env"
headers = {
    "X-Backend-Token": token
}

req = urllib.request.Request(url, headers=headers, method="GET")
try:
    with urllib.request.urlopen(req) as response:
        res = json.loads(response.read().decode())
        print("Backend Env Response:", json.dumps(res, indent=2))
except Exception as e:
    print("Failed to contact backend:", e)
