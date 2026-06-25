"""
Run the ETL procedure and then mirror Citizens_Clean to Fabric Lakehouse.
"""
import sys
import os
os.environ["PYTHONIOENCODING"] = "utf-8"

from dotenv import load_dotenv
load_dotenv()
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
from agent.azure_sql_executor import get_connection, run_transactional_sql

print("=== STEP 1: Check Citizens source table ===")
conn = get_connection()
cur = conn.cursor()
try:
    cur.execute("SELECT COUNT(*) FROM dbo.Citizens")
    cnt = cur.fetchone()[0]
    print(f"Citizens rows: {cnt}")
except Exception as e:
    print(f"dbo.Citizens not found or error: {e}")
    cnt = 0
conn.close()

print()
print("=== STEP 2: Run dbo.etl_main ===")
result = run_transactional_sql(
    "EXEC dbo.etl_main;",
    approved=True,
    timeout_s=120
)
import json
ok = result.get("ok", False)
print(f"Success: {ok}")
print(f"Committed: {result.get('transaction_committed')}")
print(f"Rollback reason: {result.get('rollback_reason')}")
print(f"Duration: {result.get('total_duration_ms')}ms")
if result.get("batch_results"):
    for i, b in enumerate(result["batch_results"]):
        err = b.get("error")
        if err:
            print(f"  Batch {i+1} ERROR: {err}")

print()
print("=== STEP 3: Check ETL results ===")
conn = get_connection()
cur = conn.cursor()

try:
    cur.execute("SELECT COUNT(*) FROM dbo.Citizens_Clean")
    clean_cnt = cur.fetchone()[0]
    print(f"Citizens_Clean rows: {clean_cnt}")
except Exception as e:
    print(f"Citizens_Clean error: {e}")
    clean_cnt = 0

try:
    cur.execute("SELECT COUNT(*) FROM dbo.etl_rejects")
    rej_cnt = cur.fetchone()[0]
    print(f"etl_rejects rows: {rej_cnt}")
except Exception as e:
    print(f"etl_rejects error: {e}")

try:
    cur.execute("SELECT TOP 5 id, process_name, status, error_message FROM dbo.etl_log ORDER BY start_time DESC")
    rows = cur.fetchall()
    print("Recent etl_log:")
    for row in rows:
        print(f"  id={row[0]} | proc={row[1]} | status={row[2]} | err={str(row[3])[:80] if row[3] else None}")
except Exception as e:
    print(f"etl_log error: {e}")

conn.close()

print()
print("=== STEP 4: Mirror Citizens_Clean to Fabric Lakehouse ===")
if not ok or clean_cnt == 0:
    print("Skipping Fabric mirror - ETL did not produce rows.")
    sys.exit(0)

# Read cleaned data
conn = get_connection()
cur = conn.cursor()
cur.execute("SELECT CitizenID, FullName, Email, Mobile, RegistrationDate, etl_batch_id FROM dbo.Citizens_Clean")
rows = cur.fetchall()
cols = [d[0] for d in cur.description]
df = pd.DataFrame.from_records(rows, columns=cols)
conn.close()

print(f"Loaded {len(df)} rows from Citizens_Clean")
print(df.head(3).to_string())

# Write to Fabric
from connectors.fabric_lakehouse_connector import write_to_lakehouse
res = write_to_lakehouse(df, "dbo.Citizens_Clean", mode="overwrite")
print()
print(f"Fabric mirror result: {res}")
