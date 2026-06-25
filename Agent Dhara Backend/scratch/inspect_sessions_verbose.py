import sqlite3
import json
import os

root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
db_path = os.path.join(root, "output", "chat_sessions.sqlite3")

if not os.path.exists(db_path):
    print("Database not found at:", db_path)
    exit(1)

conn = sqlite3.connect(db_path)
cursor = conn.cursor()

rows = cursor.execute("SELECT session_id, updated_at, payload_json FROM sessions ORDER BY updated_at DESC").fetchall()
for sid, updated_at, payload_json in rows[:3]:
    print("====================================================")
    print("Session ID:", sid)
    print("Updated At:", updated_at)
    try:
        payload = json.loads(payload_json)
        flow = payload.get("context", {}).get("etl_flow", {})
        print("Phase:", flow.get("phase"))
        print("Target Engine:", flow.get("target_engine"))
        print("Codegen Engine:", flow.get("codegen_engine"))
        print("Validation Ok:", flow.get("validation_ok"))
        print("Validation Errors:", flow.get("validation_errors"))
        print("Approved Plan Present:", flow.get("approved_plan") is not None)
        print("Failure Reason:", flow.get("failure_reason"))
    except Exception as e:
        print("Error parsing payload:", e)
conn.close()
