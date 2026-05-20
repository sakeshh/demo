import json
from agent.session_store import load_session
from agent.etl_handlers import etl_plan_start
from dotenv import load_dotenv

load_dotenv()

# We need a fake assessment result to test
assessment = {
    "datasets": {
        "dbo.Test_Data": {
            "row_count": 100,
            "columns": {
                "Age": {
                    "dtype": "float",
                    "row_count": 100
                }
            }
        }
    }
}

# The user's unstructured rule
business_rules = {
    "notes": "Use the clip strategy for outliers. Also if you see any constant columns, just drop them."
}

# Let's mock the transformation suggester to ensure manual review items are generated
import agent.transformation_suggester
old_suggest = agent.transformation_suggester.suggest_transformations

def mock_suggest(*args, **kwargs):
    return {
        "suggested_transformations": [
            {
                "dataset": "dbo.Test_Data",
                "column": "Age",
                "issue_type": "numeric_outliers_iqr",
                "suggested_action": "clip_or_flag",
                "severity": "medium",
                "auto_fixable": True
            },
            {
                "dataset": "dbo.Test_Data",
                "column": "Useless_Flag",
                "issue_type": "constant_column",
                "suggested_action": "review_manually",
                "severity": "low",
                "auto_fixable": False,
                "message": "Only 1 distinct value"
            }
        ]
    }

agent.transformation_suggester.suggest_transformations = mock_suggest

print("Starting Agentic ETL Plan...")
result = etl_plan_start(
    session_id="test_session_123",
    business_rules=business_rules,
    assessment_result=assessment,
    engine="python"
)

plan = result.get("plan", {})
rules_used = plan.get("business_rules", {})
manual_pending = len(plan.get("manual_review", []))
resolved = len(plan.get("resolved_manual_review", []))

print("\n--- RESULTS ---")
print(f"Outlier Strategy used: {rules_used.get('outlier_strategy')}")
print(f"Pending Manual Review items: {manual_pending}")
print(f"Auto-Resolved Manual Review items: {resolved}")

if resolved > 0:
    for item in plan.get("resolved_manual_review", []):
        print(f"- {item.get('id')} -> {item.get('selected_resolution')}")
