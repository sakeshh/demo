import sqlite3

db_path = r"c:\Users\ssakesh\Documents\DHARA-GX\Agent Dhara Backend\output\jobs.sqlite3"
conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row
cursor = conn.cursor()

with open("scratch/jobs_history.txt", "w", encoding="utf-8") as f:
    cursor.execute("SELECT * FROM jobs ORDER BY created_at DESC LIMIT 10")
    rows = cursor.fetchall()
    for r in rows:
        rd = dict(r)
        f.write(f"Job ID: {rd.get('job_id')} | Kind: {rd.get('kind')} | Status: {rd.get('status')} | Created: {rd.get('created_at')}\n")
        f.write(f"  Input: {rd.get('input_json')}\n")
        f.write(f"  Result: {rd.get('result_json')}\n")
        f.write(f"  Error: {rd.get('error')}\n")
        f.write("-" * 80 + "\n")

print("Dumped to scratch/jobs_history.txt")
conn.close()
