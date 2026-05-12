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
    cursor.execute("SELECT result_json FROM jobs WHERE job_id='b1afaf1a-62c1-48a1-bf1b-9e665be766e5'")
    row = cursor.fetchone()
    if row and row[0]:
        res = json.loads(row[0])
        print("Reply:", res.get("reply")[:200])
        print("Payload keys:", list(res.get("payload", {}).keys()))
    else:
        print("Job result not found.")
    conn.close()
