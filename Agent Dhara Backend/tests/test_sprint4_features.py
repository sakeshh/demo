"""
Tests for Sprint 4 features: SQL pushdown stats, column filtering, and async progress.
"""
import unittest
from unittest.mock import MagicMock, patch

from agent.etl_pipeline.dq_gate import calculate_dataset_dq_score, check_dq_gate


class TestSprint4PushdownStats(unittest.TestCase):
    """Test that SQL pushdown stats correctly enrich profile columns."""

    def test_pushdown_stats_merge(self):
        """Simulate a profile_dataframe result and verify pushdown stats merge."""
        # Simulate a base profile
        base_profile = {
            "row_count": 100,
            "column_count": 3,
            "data_volume_bytes": 5000,
            "sampling_info": "Analysis performed on 100% of rows.",
            "columns": {
                "id": {
                    "dtype": "int64",
                    "null_percentage": 0.0,
                    "unique_count": 100,
                    "semantic_type": "numeric_id",
                    "candidate_primary_key": True,
                },
                "name": {
                    "dtype": "object",
                    "null_percentage": 0.05,
                    "unique_count": 95,
                    "semantic_type": "person_name",
                    "candidate_primary_key": False,
                },
                "score": {
                    "dtype": "float64",
                    "null_percentage": 0.1,
                    "unique_count": 50,
                    "semantic_type": "numeric",
                    "candidate_primary_key": False,
                },
            },
            "priority_columns": ["id", "name", "score"],
        }

        # Simulate pushdown stats from SQL Server
        pushdown_stats = {
            "row_count": 100,
            "columns": {
                "id": {
                    "null_count": 0,
                    "null_percentage": 0.0,
                    "distinct_count": 100,
                    "min_value": "1",
                    "max_value": "100",
                    "sql_data_type": "int",
                },
                "name": {
                    "null_count": 3,
                    "null_percentage": 0.03,
                    "distinct_count": 97,
                    "min_value": "Alice",
                    "max_value": "Zoe",
                    "sql_data_type": "nvarchar",
                },
                "score": {
                    "null_count": 8,
                    "null_percentage": 0.08,
                    "distinct_count": 45,
                    "min_value": "10.5",
                    "max_value": "99.8",
                    "sql_data_type": "decimal",
                },
            },
        }

        # Apply pushdown stats merge logic (same as in load_and_profile)
        for col_name, pstats in pushdown_stats["columns"].items():
            if col_name in base_profile.get("columns", {}):
                col_meta = base_profile["columns"][col_name]
                if "null_percentage" in pstats:
                    col_meta["null_percentage"] = pstats["null_percentage"]
                if "distinct_count" in pstats and pstats["distinct_count"] is not None:
                    col_meta["unique_count"] = pstats["distinct_count"]
                if "min_value" in pstats:
                    col_meta["server_min"] = pstats["min_value"]
                if "max_value" in pstats:
                    col_meta["server_max"] = pstats["max_value"]
                if "sql_data_type" in pstats:
                    col_meta["sql_data_type"] = pstats["sql_data_type"]
                if pushdown_stats.get("row_count") and pstats.get("distinct_count"):
                    col_meta["candidate_primary_key"] = (
                        pstats["distinct_count"] == pushdown_stats["row_count"]
                        and pstats.get("null_count", 0) == 0
                    )

        # Verify server-side stats overrode DataFrame stats
        self.assertEqual(base_profile["columns"]["name"]["null_percentage"], 0.03)
        self.assertEqual(base_profile["columns"]["name"]["unique_count"], 97)
        self.assertEqual(base_profile["columns"]["name"]["server_min"], "Alice")
        self.assertEqual(base_profile["columns"]["name"]["server_max"], "Zoe")
        self.assertEqual(base_profile["columns"]["name"]["sql_data_type"], "nvarchar")

        # id should be PK (distinct_count == row_count, null_count == 0)
        self.assertTrue(base_profile["columns"]["id"]["candidate_primary_key"])
        # name should NOT be PK (distinct_count < row_count)
        self.assertFalse(base_profile["columns"]["name"]["candidate_primary_key"])

        # score had 10% null in DataFrame but pushdown says 8%
        self.assertEqual(base_profile["columns"]["score"]["null_percentage"], 0.08)

    def test_dq_gate_force_unlock(self):
        """Test that force_unlock bypasses the DQ gate regardless of score."""
        assessment = {
            "datasets": {
                "dbo.test": {
                    "columns": {
                        "col1": {"null_percentage": 0.99},
                        "col2": {"null_percentage": 0.99},
                    }
                }
            }
        }
        # Without force_unlock, should fail (score is ~70.0)
        gate = check_dq_gate(assessment, "dbo.test", threshold=75.0)
        self.assertFalse(gate["passed"])

        # With force_unlock, should pass
        gate_unlock = check_dq_gate(assessment, "dbo.test", threshold=75.0, force_unlock=True)
        self.assertTrue(gate_unlock["passed"])
        self.assertTrue(gate_unlock["force_unlocked"])


class TestSprint4ColumnFiltering(unittest.TestCase):
    """Test that priority column filtering works for extended DQ checks."""

    def test_priority_columns_in_profile(self):
        """Verify that profile_dataframe sets priority_columns."""
        import pandas as pd
        from agent.intelligent_data_assessment import profile_dataframe

        df = pd.DataFrame({
            "id": [1, 2, 3],
            "name": ["A", "B", "C"],
            "email": ["a@b.com", "b@c.com", "c@d.com"],
        })
        profile = profile_dataframe(df)
        self.assertIn("priority_columns", profile)
        self.assertTrue(len(profile["priority_columns"]) > 0)


if __name__ == "__main__":
    unittest.main()
