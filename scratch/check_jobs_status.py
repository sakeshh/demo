import sqlite3
import os

root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
db_path = os.path.join(root, "Agent Dhara Backend", "output", "jobs.sqlite3")

if not os.path.exists(db_path):
    print("Database does not exist.")
else:
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT job_id, status, kind, created_at FROM jobs ORDER BY created_at DESC LIMIT 5")
    rows = cursor.fetchall()
    print(f"Last 5 jobs:")
    for r in rows:
        print(f"ID: {r[0]}, Status: {r[1]}, Kind: {r[2]}, Created: {r[3]}")
    conn.close()
