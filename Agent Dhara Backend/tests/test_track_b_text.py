import unittest
import pandas as pd
from agent.intelligent_data_assessment import analyze_dataset_quality

class TestTrackBText(unittest.TestCase):
    def test_non_ascii_detected(self):
        # 10 rows: 9 plain ASCII, 1 containing non-ASCII "hello 🚀"
        data = ["hello"] * 9 + ["hello 🚀"]
        df = pd.DataFrame({"notes": data})
        profile = {"columns": {"notes": {"semantic_type": "text"}}}
        res = analyze_dataset_quality("test_df", df, profile)
        issues = [it for it in res["issues"] if it.get("type") == "non_ascii_characters"]
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["column"], "notes")
        self.assertEqual(issues[0]["count"], 1)
        self.assertEqual(issues[0]["severity"], "low")

    def test_control_chars_detected(self):
        # Control characters like \x00 or \x07 in 5+ rows
        data = ["hello"] * 4 + ["hello\x00world"]
        df = pd.DataFrame({"comments": data})
        profile = {"columns": {"comments": {"semantic_type": "text"}}}
        res = analyze_dataset_quality("test_df", df, profile)
        issues = [it for it in res["issues"] if it.get("type") == "control_characters_in_text"]
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["column"], "comments")
        self.assertEqual(issues[0]["count"], 1)
        self.assertEqual(issues[0]["severity"], "medium")

    def test_string_length_outliers(self):
        # 20 rows: 19 very short, 1 extremely long (outlier)
        data = ["abc"] * 19 + ["a" * 500]
        df = pd.DataFrame({"description": data})
        profile = {"columns": {"description": {"semantic_type": "text"}}}
        res = analyze_dataset_quality("test_df", df, profile)
        issues = [it for it in res["issues"] if it.get("type") == "string_length_outlier"]
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["column"], "description")
        self.assertEqual(issues[0]["count"], 1)
        self.assertEqual(issues[0]["severity"], "low")

    def test_digits_only_in_text(self):
        # 20 rows: 15 normal text, 5 digits-only in a non-ID text column
        data = ["abc"] * 15 + ["12345"] * 5
        df = pd.DataFrame({"product_desc": data})
        profile = {"columns": {"product_desc": {"semantic_type": "text"}}}
        res = analyze_dataset_quality("test_df", df, profile)
        issues = [it for it in res["issues"] if it.get("type") == "string_with_only_digits_in_text_column"]
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["column"], "product_desc")
        self.assertEqual(issues[0]["count"], 5)
        self.assertEqual(issues[0]["severity"], "medium")

    def test_repeated_token(self):
        # name column with repeated leading token e.g., "John John"
        data = ["John Smith"] * 9 + ["John John"]
        df = pd.DataFrame({"customer_name": data})
        profile = {"columns": {"customer_name": {"semantic_type": "text"}}}
        res = analyze_dataset_quality("test_df", df, profile)
        issues = [it for it in res["issues"] if it.get("type") == "repeated_token_in_string"]
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["column"], "customer_name")
        self.assertEqual(issues[0]["count"], 1)
        self.assertEqual(issues[0]["severity"], "low")

    def test_implausible_age(self):
        # age column with -5 and 200
        data = [25] * 8 + [-5, 200]
        df = pd.DataFrame({"user_age": data})
        profile = {"columns": {"user_age": {"semantic_type": "numeric"}}}
        res = analyze_dataset_quality("test_df", df, profile)
        issues = [it for it in res["issues"] if it.get("type") == "implausible_age"]
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["column"], "user_age")
        self.assertEqual(issues[0]["count"], 2)
        self.assertEqual(issues[0]["severity"], "high")

    def test_implausible_percentage(self):
        # percentage/pct/rate column with -10 and 150
        data = [50] * 8 + [-10, 150]
        df = pd.DataFrame({"interest_rate": data})
        profile = {"columns": {"interest_rate": {"semantic_type": "numeric"}}}
        res = analyze_dataset_quality("test_df", df, profile)
        issues = [it for it in res["issues"] if it.get("type") == "implausible_percentage"]
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["column"], "interest_rate")
        self.assertEqual(issues[0]["count"], 2)
        self.assertEqual(issues[0]["severity"], "medium")

    def test_case_insensitive_duplicates(self):
        # categorical status column with "Active", "active", "ACTIVE"
        data = ["Active"] * 5 + ["active"] * 5
        df = pd.DataFrame({"status": data})
        profile = {"columns": {"status": {"semantic_type": "categorical"}}}
        res = analyze_dataset_quality("test_df", df, profile)
        issues = [it for it in res["issues"] if it.get("type") == "duplicate_insensitive_values"]
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["column"], "status")
        self.assertEqual(issues[0]["severity"], "low")

if __name__ == "__main__":
    unittest.main()
