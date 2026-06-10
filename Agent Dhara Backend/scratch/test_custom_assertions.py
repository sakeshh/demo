import pandas as pd
import numpy as np
import sys
import os

# Adjust path to import agent
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from agent.intelligent_data_assessment import evaluate_custom_assertion

def test_evaluate_custom_assertion():
    # 1. Test case-insensitivity and string function
    df1 = pd.DataFrame({
        "email": ["john@capgemini.com", "doe@example.com", "alice@capgemini.com", "bob@Capgemini.com", "invalid"]
    })
    
    # Custom assertion refers to "Email" (capital E)
    assertion1 = "Email.str.endswith('@capgemini.com')"
    res1, ref_cols1 = evaluate_custom_assertion(df1, assertion1)
    
    print("Test 1 Result Series:")
    print(res1)
    print("Referenced Columns:", ref_cols1)
    
    expected1 = pd.Series([True, False, True, False, False]) # Note: .endswith('@capgemini.com') is case-sensitive, so bob@Capgemini.com might be False depending on exact match.
    # If the user wanted case-insensitive capgemini, they could use .str.lower().str.endswith()
    # Let's check:
    assert ref_cols1 == ["email"]
    assert res1.iloc[0] == True
    assert res1.iloc[1] == False
    
    # 2. Test space in column name
    df2 = pd.DataFrame({
        "Email ID": ["john@capgemini.com", "doe@example.com", "alice@capgemini.com"]
    })
    
    # Custom assertion has backticks or no backticks
    assertion2 = "`Email ID`.str.endswith('@capgemini.com')"
    res2, ref_cols2 = evaluate_custom_assertion(df2, assertion2)
    print("\nTest 2 Result Series:")
    print(res2)
    print("Referenced Columns:", ref_cols2)
    assert ref_cols2 == ["Email ID"]
    assert res2.iloc[0] == True
    assert res2.iloc[1] == False

    # 3. Test space in column name without backticks
    # (Should match the word 'Email ID' replaced by 'Email_ID')
    assertion3 = "Email ID.str.endswith('@capgemini.com')"
    # Wait, in python syntax "Email ID.str" has a space between Email and ID. So it's not valid syntax.
    # But wait! Our tokenizer/parser sanitizes it into "Email_ID.str.endswith('@capgemini.com')".
    # Let's see if that evaluates!
    res3, ref_cols3 = evaluate_custom_assertion(df2, assertion3)
    print("\nTest 3 Result Series:")
    print(res3)
    print("Referenced Columns:", ref_cols3)
    assert ref_cols3 == ["Email ID"]
    assert res3.iloc[0] == True
    assert res3.iloc[1] == False

    print("\nALL TESTS PASSED SUCCESSFULLY!")

if __name__ == "__main__":
    test_evaluate_custom_assertion()
