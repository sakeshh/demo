import sys
import os
import pandas as pd

# Add parent path to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.intelligent_data_assessment import check_custom_assertions

# Sample test data
df = pd.DataFrame({
    "Email": ["abc@capgemini.com", "xyz@gmail.com", "test@capgemini.com"],
    "Price": [10.5, -5.0, 20.0],
    "Age": [25, 30, 15]
})

# Custom rules
rules = [
    {
        "assertion": "Email.str.endswith('@capgemini.com')",
        "severity": "high",
        "message": "Email should only be @capgemini.com"
    },
    {
        "assertion": "Price > 0",
        "severity": "medium",
        "message": "Price must be positive"
    },
    {
        "assertion": "Age >= 18",
        "severity": "low",
        "message": "User must be an adult"
    }
]

print("Running Custom Assertions check on test DataFrame...")
issues = check_custom_assertions(df, rules)

print(f"\nFound {len(issues)} issues:")
for idx, iss in enumerate(issues):
    print(f"\nIssue #{idx + 1}:")
    print(f"  Type: {iss.get('type')}")
    print(f"  Severity: {iss.get('severity')}")
    print(f"  Column(s): {iss.get('column')}")
    print(f"  Count: {iss.get('count')}")
    print(f"  Row Indexes: {iss.get('row_indexes')}")
    print(f"  Message: {iss.get('message')}")
    print(f"  Sample Values: {iss.get('sample')}")
