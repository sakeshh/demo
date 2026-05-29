"""
Tests for Sprint 6 features: Heuristic Semantic Classifier, LLM Enricher caching, overrides, and PII-aware DQ gate.
"""
import unittest
from unittest.mock import MagicMock, patch

from agent.etl_pipeline.semantic_classifier import classify_column_semantic
from agent.etl_pipeline.dq_gate import check_dq_gate
from agent.etl_pipeline.planner import build_etl_plan
from agent.etl_pipeline.business_rules import normalize_business_rules

class TestSemanticClassifier(unittest.TestCase):
    """Test heuristic-based Layer 1 semantic classification logic."""

    def test_email_classification(self):
        col_meta = {
            "dtype": "object",
            "raw_samples": ["john.doe@example.com", "jane@corp.org", "test@test.net"]
        }
        res = classify_column_semantic("user_email", col_meta)
        self.assertEqual(res["semantic_type"], "id")
        self.assertEqual(res["sub_type"], "email")
        self.assertEqual(res["pii_level"], "high")
        self.assertIn("sanitize_email", res["transform_hints"])
        self.assertEqual(res["fill_strategy"], "flag")

    def test_phone_classification(self):
        col_meta = {
            "dtype": "object",
            "raw_samples": ["+91 98765 43210", "+1 (555) 019-2834"]
        }
        res = classify_column_semantic("contact_phone", col_meta)
        self.assertEqual(res["semantic_type"], "id")
        self.assertEqual(res["sub_type"], "phone")
        self.assertEqual(res["pii_level"], "high")
        self.assertIn("normalize_phone", res["transform_hints"])

    def test_currency_classification(self):
        col_meta = {
            "dtype": "float64",
            "raw_samples": ["10.5", "99.99", "1250.0"]
        }
        res = classify_column_semantic("order_amount", col_meta)
        self.assertEqual(res["semantic_type"], "metric")
        self.assertEqual(res["sub_type"], "currency")
        self.assertEqual(res["fill_strategy"], "fill_zero")

    def test_zip_code_classification(self):
        col_meta = {
            "dtype": "object",
            "raw_samples": ["560001", "10001"]
        }
        res = classify_column_semantic("zipcode", col_meta)
        self.assertEqual(res["semantic_type"], "id")
        self.assertEqual(res["sub_type"], "zip_code")
        self.assertEqual(res["pii_level"], "medium")

    def test_status_flag_classification(self):
        col_meta = {
            "dtype": "object",
            "raw_samples": ["Active", "Inactive", "Pending"]
        }
        res = classify_column_semantic("is_active_flag", col_meta)
        self.assertEqual(res["semantic_type"], "categorical")
        self.assertEqual(res["sub_type"], "status_flag")
        self.assertEqual(res["fill_strategy"], "fill_mode")


class TestSemanticOverrides(unittest.TestCase):
    """Test Layer 3 User Overrides parsing and merging."""

    def test_business_rules_overrides_normalization(self):
        raw_rules = {
            "semantic_overrides": {
                "dbo.Orders.CustomerID": {
                    "sub_type": "fk",
                    "pii_level": "low"
                }
            }
        }
        norm = normalize_business_rules(raw_rules)
        self.assertIn("semantic_overrides", norm)
        self.assertEqual(norm["semantic_overrides"]["dbo.Orders.CustomerID"]["sub_type"], "fk")

    def test_planner_applies_overrides(self):
        assessment = {
            "datasets": {
                "dbo.Orders": {
                    "columns": {
                        "CustomerID": {
                            "dtype": "int64",
                            "raw_samples": [1, 2, 3],
                            "semantic_type": "numeric_id"
                        }
                    }
                }
            }
        }
        rules = {
            "semantic_overrides": {
                "CustomerID": {
                    "sub_type": "fk",
                    "pii_level": "medium"
                }
            }
        }
        plan = build_etl_plan(assessment, rules)
        sem = plan["semantic_schema"]
        
        # Override should match by column name
        self.assertEqual(sem["dbo.Orders.CustomerID"]["sub_type"], "fk")
        self.assertEqual(sem["dbo.Orders.CustomerID"]["pii_level"], "medium")
        self.assertEqual(sem["dbo.Orders.CustomerID"]["inferred_by"], "user_override")
        self.assertEqual(sem["dbo.Orders.CustomerID"]["confidence"], 1.0)


class TestPiiAwareDQGate(unittest.TestCase):
    """Test that high-PII columns dynamically raise the DQ Gate threshold."""

    def test_pii_gate_raised(self):
        # A mock assessment with high null rate (score will be ~70.0)
        assessment = {
            "datasets": {
                "dbo.test": {
                    "columns": {
                        "email": {
                            "dtype": "object",
                            "null_percentage": 0.99,
                            "raw_samples": ["john@example.com"]
                        }
                    }
                }
            }
        }
        
        # Base schema: "user_email" matches email subtype (high PII)
        sem_schema = {
            "dbo.test.email": {
                "semantic_type": "id",
                "sub_type": "email",
                "pii_level": "high"
            }
        }
        
        # Without sem_schema, threshold is base 70.0 (passes since score ~70.0 is >= 70.0)
        gate_normal = check_dq_gate(assessment, "dbo.test", threshold=70.0)
        self.assertTrue(gate_normal["passed"])
        self.assertEqual(gate_normal["threshold"], 70.0)

        # With sem_schema containing high-PII, effective threshold raises to 85.0
        # (Should fail since score is ~70.0 < 85.0)
        gate_pii = check_dq_gate(assessment, "dbo.test", threshold=70.0, sem_schema=sem_schema)
        self.assertFalse(gate_pii["passed"])
        self.assertEqual(gate_pii["threshold"], 85.0)
        self.assertTrue(gate_pii["has_high_pii"])


if __name__ == "__main__":
    unittest.main()
