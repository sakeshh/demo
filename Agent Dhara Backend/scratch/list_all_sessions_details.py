import sqlite3
import json
import time
from datetime import datetime

db_path = "c:/Users/ssakesh/Documents/DHARA-GX/Agent Dhara Backend/output/chat_sessions.sqlite3"
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

cursor.execute("SELECT session_id, created_at, updated_at, payload_json FROM sessions ORDER BY updated_at DESC")
rows = cursor.fetchall()
print(f"Total sessions: {len(rows)}")
for idx, r in enumerate(rows):
    sid = r[0]
    created = datetime.fromtimestamp(r[1]).isoformat()
    updated = datetime.fromtimestamp(r[2]).isoformat()
    payload = json.loads(r[3])
    
    flow = payload.get("context", {}).get("etl_flow", {})
    exec_res = flow.get("sql_execution_result") or {}
    post_sum = exec_res.get("post_execution_summary") or {}
    
    print(f"\n--- Session {idx+1} ---")
    print("Session ID:", sid)
    print("Created At:", created)
    print("Updated At:", updated)
    print("Target Engine:", flow.get("target_engine"))
    print("Phase:", flow.get("phase"))
    print("Execution Result Ok:", exec_res.get("ok"))
    print("Committed:", post_sum.get("transaction_committed"))
    print("Rollback Reason:", post_sum.get("rollback_reason"))
    print("Batch Count:", post_sum.get("batch_count"))

conn.close()
