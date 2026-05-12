import sqlite3
import os

root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
db_path = os.path.join(root, "Agent Dhara Backend", "output", "jobs.sqlite3")

if not os.path.exists(db_path):
    print("Database does not exist.")
else:
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT ts, level, message FROM job_events WHERE job_id='7550799e-c2c6-4385-85fa-de48dd939f46' ORDER BY ts")
    rows = cursor.fetchall()
    print(f"Events for job 7550799e:")
    for r in rows:
        print(f"[{r[0]}] {r[1]}: {r[2]}")
    conn.close()
