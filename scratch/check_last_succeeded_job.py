import sqlite3
import os
import json

root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
db_path = os.path.join(root, "Agent Dhara Backend", "output", "jobs.sqlite3")

if not os.path.exists(db_path):
    print("Database does not exist.")
else:
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT job_id, result_json FROM jobs WHERE status='succeeded' ORDER BY updated_at DESC LIMIT 1")
    row = cursor.fetchone()
    if row:
        job_id = row[0]
        res = json.loads(row[1]) if row[1] else {}
        print(f"Job ID: {job_id}")
        # Use repr to avoid UnicodeEncodeError in console
        print("Reply (first 100):", repr(res.get("reply"))[:100])
        print("Payload keys:", list(res.get("payload", {}).keys()))
        if "payload" in res and "report_html" in res["payload"]:
            print("Report HTML found (length):", len(res["payload"]["report_html"]))
    else:
        print("No succeeded jobs found.")
    conn.close()
