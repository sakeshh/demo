import os
import sys
from dotenv import load_dotenv

backend_dir = r"c:\Users\ssakesh\Documents\DHARA-GX\Agent Dhara Backend"
dotenv_path = os.path.join(backend_dir, ".env")
load_dotenv(dotenv_path)

sys.path.append(backend_dir)
from agent.etl_pipeline.sql_codegen import generate_sql_etl

def test():
    plan = {
        "plan_id": "test_student_plan",
        "generation_mode": "cleanse_only",
        "datasets": {
            "dbo.students_raw": {
                "steps": [
                    {"column": "student_id", "action": "trim", "order": 1},
                    {"column": "[Row-level]", "action": "deduplicate", "order": 2}
                ]
            }
        }
    }
    
    assessment = {
        "datasets": {
            "dbo.students_raw": {
                "columns": {
                    "student_id": {"semantic_type": "string"},
                    "name": {"semantic_type": "string"}
                }
            }
        }
    }
    
    sql_code = generate_sql_etl(plan, assessment, dialect="tsql")
    print("--- Generated SQL DDL snippet ---")
    lines = sql_code.splitlines()
    for idx, line in enumerate(lines):
        if "student_id" in line:
            print(f"Line {idx+1}: {line}")

if __name__ == "__main__":
    test()
