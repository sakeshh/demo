import sys
import os
import sqlite3
import json

sys.stdout.reconfigure(encoding='utf-8')
sys.path.append(r"c:\Users\ssakesh\Documents\DHARA-GX\Agent Dhara Backend")

from agent.chat_graph import build_chat_graph
from langgraph.checkpoint.sqlite import SqliteSaver

db_path = r"c:\Users\ssakesh\Documents\DHARA-GX\Agent Dhara Backend\agent\data\checkpointer.db"
conn = sqlite3.connect(db_path, check_same_thread=False)
checkpointer = SqliteSaver(conn)
checkpointer.setup()

graph = build_chat_graph(checkpointer=checkpointer)
config = {"configurable": {"thread_id": "8c23e2f7-9dce-4efe-a4b0-69827eb9e9f9"}}

with open("scratch/trace_output.txt", "w", encoding="utf-8") as f:
    f.write("--- STATE HISTORY ---\n")
    try:
        for s in graph.get_state_history(config):
            f.write(f"Config: {s.config}\n")
            f.write(f"Next: {s.next}\n")
            f.write(f"Created: {s.created_at}\n")
            # Filter values to avoid dumping massive raw assessment result
            val_mini = {}
            for k, v in s.values.items():
                if k == 'session':
                    if isinstance(v, dict):
                        val_mini[k] = {sk: sv for sk, sv in v.items() if sk not in ('last_assessment_result', 'last_assessment_datasets')}
                    else:
                        val_mini[k] = str(v)
                elif k != 'last_assessment_result':
                    val_mini[k] = v
            f.write(f"Values: {json.dumps(val_mini, indent=2)}\n")
            f.write("-" * 80 + "\n")
    except Exception as e:
        f.write(f"Error: {e}\n")

print("Dumped to scratch/trace_output.txt")
conn.close()
