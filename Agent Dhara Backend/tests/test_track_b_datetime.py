import unittest
import pandas as pd
from datetime import datetime, timedelta
from agent.intelligent_data_assessment import analyze_dataset_quality

class TestTrackBDateTime(unittest.TestCase):
    def test_future_dates_detected(self):
        # 10 rows: 9 valid past dates, 1 future date (10 days in future)
        now = datetime.now()
        dates = [str((now - timedelta(days=i)).date()) for i in range(9)] + [str((now + timedelta(days=10)).date())]
        df = pd.DataFrame({"order_date": dates})
        profile = {"columns": {"order_date": {"semantic_type": "date"}}}
        res = analyze_dataset_quality("test_df", df, profile)
        issues = [it for it in res["issues"] if it.get("type") == "future_dates"]
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["column"], "order_date")
        self.assertEqual(issues[0]["count"], 1)
        self.assertEqual(issues[0]["severity"], "high")

    def test_ancient_dates_detected(self):
        # Dates before 1900
        dates = ["2024-01-01"] * 9 + ["1899-12-31"]
        df = pd.DataFrame({"birth_date": dates})
        profile = {"columns": {"birth_date": {"semantic_type": "date"}}}
        res = analyze_dataset_quality("test_df", df, profile)
        issues = [it for it in res["issues"] if it.get("type") == "ancient_dates"]
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["column"], "birth_date")
        self.assertEqual(issues[0]["count"], 1)
        self.assertEqual(issues[0]["severity"], "medium")

    def test_wide_date_span(self):
        # Span of 80 years
        dates = ["1940-01-01"] + ["2020-01-01"] * 9
        df = pd.DataFrame({"event_date": dates})
        profile = {"columns": {"event_date": {"semantic_type": "date"}}}
        res = analyze_dataset_quality("test_df", df, profile)
        issues = [it for it in res["issues"] if it.get("type") == "very_wide_date_span"]
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["column"], "event_date")
        self.assertEqual(issues[0]["severity"], "low")

    def test_jan1_clumping(self):
        # 30% dates on Jan 1
        dates = ["2024-01-01"] * 6 + ["2024-02-15"] * 14 # 6/20 = 30%
        df = pd.DataFrame({"payment_date": dates})
        profile = {"columns": {"payment_date": {"semantic_type": "date"}}}
        res = analyze_dataset_quality("test_df", df, profile)
        issues = [it for it in res["issues"] if it.get("type") == "date_clumping_jan1"]
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["column"], "payment_date")
        self.assertEqual(issues[0]["severity"], "medium")

    def test_month_end_clumping(self):
        # 40% dates on month-end
        dates = ["2024-01-31"] * 8 + ["2024-02-15"] * 12 # 8/20 = 40%
        df = pd.DataFrame({"billing_date": dates})
        profile = {"columns": {"billing_date": {"semantic_type": "date"}}}
        res = analyze_dataset_quality("test_df", df, profile)
        issues = [it for it in res["issues"] if it.get("type") == "date_clumping_month_end"]
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["column"], "billing_date")
        self.assertEqual(issues[0]["severity"], "low")

    def test_weekend_business_dates(self):
        # order_date with >15% weekends. 2026-05-16 is Saturday, 2026-05-17 is Sunday (2 weekends)
        # Let's have 4 weekend dates and 16 weekday dates (4/20 = 20% > 15%)
        weekdays = ["2026-05-18"] * 16 # Monday
        weekends = ["2026-05-16"] * 2 + ["2026-05-17"] * 2 # Sat/Sun
        dates = weekdays + weekends
        df = pd.DataFrame({"order_date": dates})
        profile = {"columns": {"order_date": {"semantic_type": "date"}}}
        res = analyze_dataset_quality("test_df", df, profile)
        issues = [it for it in res["issues"] if it.get("type") == "weekend_date_anomaly"]
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["column"], "order_date")
        self.assertEqual(issues[0]["count"], 4)
        self.assertEqual(issues[0]["severity"], "low")

    def test_timezone_inconsistency(self):
        # 10 rows: 5 tz-aware ("2024-01-01T12:00:00Z"), 5 tz-naive ("2024-01-01T12:00:00")
        dates = ["2024-01-01T12:00:00Z"] * 5 + ["2024-01-01T12:00:00"] * 5
        df = pd.DataFrame({"created_date": dates})
        profile = {"columns": {"created_date": {"semantic_type": "date"}}}
        res = analyze_dataset_quality("test_df", df, profile)
        issues = [it for it in res["issues"] if it.get("type") == "timezone_inconsistency"]
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["column"], "created_date")
        self.assertEqual(issues[0]["count"], 5)
        self.assertEqual(issues[0]["severity"], "medium")

if __name__ == "__main__":
    unittest.main()
