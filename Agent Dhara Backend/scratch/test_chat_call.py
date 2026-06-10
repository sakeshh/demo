import sys
import os
import json

sys.path.append(r"c:\Users\ssakesh\Documents\DHARA-GX\Agent Dhara Backend")

from agent.chat_graph import run_chat

# Set environment variables if needed
os.environ["BACKEND_AUTH_TOKEN"] = "change-me-dev"

try:
    print("Running chat with 'blob'...")
    res = run_chat(session_id="default", message="blob")
    print("Result:")
    print(json.dumps(res, indent=2))
except Exception as e:
    import traceback
    traceback.print_exc()
