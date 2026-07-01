import sqlite3
import json

conn = sqlite3.connect('output/chat_sessions.sqlite3')
cursor = conn.cursor()
cursor.execute('SELECT session_id, payload_json FROM sessions')
rows = cursor.fetchall()
print(f"Total sessions: {len(rows)}")
for r in rows:
    session_id, payload_json = r
    try:
        payload = json.loads(payload_json)
        context = payload.get("context", {})
        etl_flow = context.get("etl_flow", {})
        fabric_result = etl_flow.get("fabric_mirror_result")
        if fabric_result:
            print(f"Session: {session_id}")
            print(f"  Fabric Result: {json.dumps(fabric_result, indent=2)}")
            print(f"  Selected Source: {payload.get('selected_source')}")
            print(f"  Last Step: {payload.get('last_step')}")
            print("-" * 50)
    except Exception as e:
        print(f"Error parsing session {session_id}: {e}")
conn.close()
