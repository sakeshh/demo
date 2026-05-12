import sqlite3
import os

root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
db_path = os.path.join(root, "Agent Dhara Backend", "output", "jobs.sqlite3")

print(f"Checking database at {db_path}")
if not os.path.exists(db_path):
    print("Database does not exist.")
else:
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM jobs")
    rows = cursor.fetchall()
    print(f"Found {len(rows)} jobs:")
    for r in rows:
        print(r)
    conn.close()
