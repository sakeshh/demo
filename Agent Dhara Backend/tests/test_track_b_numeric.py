import unittest
import pandas as pd
from agent.intelligent_data_assessment import analyze_dataset_quality

class TestTrackBNumeric(unittest.TestCase):
    def test_iqr_outliers_detected(self):
        # 50 rows of 10.0, 45 rows of 12.0, 5 rows of 100.0 (clearly outliers since IQR is 2.0, upper bound is 15.0)
        data = [10.0] * 50 + [12.0] * 45 + [100.0] * 5
        df = pd.DataFrame({
            "amount": data
        })
        profile = {
            "columns": {
                "amount": {"semantic_type": "numeric"}
            }
        }
        res = analyze_dataset_quality("test_df", df, profile)
        issues = [it for it in res["issues"] if it.get("type") == "numeric_outliers_iqr"]
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["column"], "amount")
        self.assertEqual(issues[0]["count"], 5)
        self.assertEqual(issues[0]["severity"], "medium")

    def test_iqr_outliers_skipped_for_id_columns(self):
        # Even if there are outliers, ID-like columns (either by name or semantic type) must be skipped.
        data = [10.0] * 50 + [12.0] * 45 + [100.0] * 5
        df = pd.DataFrame({
            "order_id": data,
            "some_code": data,
            "custom_id_col": data
        })
        profile = {
            "columns": {
                "order_id": {"semantic_type": "numeric"},
                "some_code": {"semantic_type": "numeric"},
                "custom_id_col": {"semantic_type": "id"}
            }
        }
        res = analyze_dataset_quality("test_df", df, profile)
        issues = [it for it in res["issues"] if it.get("type") == "numeric_outliers_iqr"]
        self.assertEqual(len(issues), 0)

    def test_zscore_extremes_detected(self):
        # Standard deviation needs to be reasonable, with extreme outliers beyond 4 sigma.
        # Mean ~ 10, std ~ 1. Values at 100000.0 are >4 sigma
        data = [10.0] * 98 + [100000.0] * 2
        df = pd.DataFrame({
            "amount": data
        })
        profile = {
            "columns": {
                "amount": {"semantic_type": "numeric"}
            }
        }
        res = analyze_dataset_quality("test_df", df, profile)
        issues = [it for it in res["issues"] if it.get("type") == "numeric_outliers_zscore"]
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["column"], "amount")
        self.assertEqual(issues[0]["count"], 2)
        self.assertEqual(issues[0]["severity"], "high")

    def test_low_variance_detected(self):
        # Near-constant column (99% same value in 100 rows)
        data = [5.0] * 99 + [10.0] * 1
        df = pd.DataFrame({
            "status_code_num": data
        })
        profile = {
            "columns": {
                "status_code_num": {"semantic_type": "numeric"}
            }
        }
        res = analyze_dataset_quality("test_df", df, profile)
        issues = [it for it in res["issues"] if it.get("type") == "low_variance_numeric"]
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["column"], "status_code_num")
        self.assertEqual(issues[0]["severity"], "low")

    def test_numeric_precision_anomaly(self):
        # Genuine mix of integer-like floats (e.g. 10.0) and high-precision floats (e.g. 10.12345)
        # Let's do 50% ints and 50% floats, total 40 rows.
        data = [10.0] * 20 + [10.12345] * 20
        df = pd.DataFrame({
            "amount": data
        })
        profile = {
            "columns": {
                "amount": {"semantic_type": "numeric"}
            }
        }
        # Note: pandas type needs to be float
        df["amount"] = df["amount"].astype(float)
        res = analyze_dataset_quality("test_df", df, profile)
        issues = [it for it in res["issues"] if it.get("type") == "numeric_precision_anomaly"]
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["column"], "amount")
        self.assertEqual(issues[0]["count"], 20)
        self.assertEqual(issues[0]["severity"], "low")

    def test_round_number_anomaly(self):
        # 60 rows total, 40 rows are round multiples of 1000 (e.g., 5000)
        data = [5000] * 40 + [1234] * 20
        df = pd.DataFrame({
            "estimated_amount": data
        })
        profile = {
            "columns": {
                "estimated_amount": {"semantic_type": "numeric"}
            }
        }
        res = analyze_dataset_quality("test_df", df, profile)
        issues = [it for it in res["issues"] if it.get("type") == "round_number_anomaly"]
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["column"], "estimated_amount")
        self.assertEqual(issues[0]["severity"], "low")

if __name__ == "__main__":
    unittest.main()
