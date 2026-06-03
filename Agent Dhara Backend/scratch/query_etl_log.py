import os
import sys
from dotenv import load_dotenv

backend_dir = r"c:\Users\ssakesh\Documents\DHARA-GX\Agent Dhara Backend"
dotenv_path = os.path.join(backend_dir, ".env")
load_dotenv(dotenv_path)

sys.path.append(backend_dir)
from agent.azure_sql_executor import get_connection

try:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT TOP 20 * FROM dbo.etl_log ORDER BY start_time DESC")
    columns = [col[0] for col in cursor.description]
    rows = cursor.fetchall()
    print("--- dbo.etl_log Top 20 Rows ---")
    print(f"{' | '.join(columns)}")
    for r in rows:
        print(" | ".join(str(val) for val in r))
except Exception as e:
    print("Error querying dbo.etl_log:", e)
