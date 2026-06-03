import os
import sys
import json
from dotenv import load_dotenv

backend_dir = r"c:\Users\ssakesh\Documents\DHARA-GX\Agent Dhara Backend"
dotenv_path = os.path.join(backend_dir, ".env")
load_dotenv(dotenv_path)

sys.path.append(backend_dir)
from agent.session_store import list_sessions, load_session

sessions = list_sessions()
if not sessions:
    print("No sessions found")
    sys.exit(0)

latest_sid = sessions[0]["session_id"]
print("Latest Session ID:", latest_sid)
sess = load_session(latest_sid)

context = sess.get("context", {})
etl_flow = context.get("etl_flow", {})
execution_result = etl_flow.get("sql_execution_result", {})

print("\n--- Environment Variables in Current Python Environment ---")
print("AZURE_SQL_SERVER:", os.getenv("AZURE_SQL_SERVER"))
print("AZURE_SQL_DATABASE:", os.getenv("AZURE_SQL_DATABASE"))
print("AZURE_SQL_USERNAME:", os.getenv("AZURE_SQL_USERNAME"))
print("DHARA_AZURE_SQL_CONN_STR length:", len(os.getenv("DHARA_AZURE_SQL_CONN_STR") or ""))

print("\n--- SQL Execution Result ---")
print("Execution Result Keys:", list(execution_result.keys()))
print("ok:", execution_result.get("ok"))
print("stage:", execution_result.get("stage"))
print("approved:", execution_result.get("approved"))
print("dry_run:", execution_result.get("dry_run"))

summary = execution_result.get("post_execution_summary", {})
print("\n--- Post-Execution Summary ---")
print("transaction_committed:", summary.get("transaction_committed"))
print("total_rows_affected:", summary.get("total_rows_affected"))
print("total_duration_ms:", summary.get("total_duration_ms"))
print("batch_count:", summary.get("batch_count"))
print("rollback_reason:", summary.get("rollback_reason"))
print("row_deltas:", json.dumps(summary.get("row_deltas"), indent=2))

execution_details = execution_result.get("execution", {})
print("\n--- Execution Details ---")
print("Execution ok:", execution_details.get("ok"))
print("Execution transaction_committed:", execution_details.get("transaction_committed"))
print("Execution error:", execution_details.get("error"))
print("Execution batches_run:", execution_details.get("batches_run"))
print("Execution rollback_reason:", execution_details.get("rollback_reason"))
if execution_details.get("batch_results"):
    print("Number of batch results:", len(execution_details["batch_results"]))
    errors = [b.get("error") for b in execution_details["batch_results"] if b.get("error")]
    print("Batch errors:", errors)
