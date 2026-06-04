"""Tests for LLM recommendation mapping and planner integration."""
from __future__ import annotations

import unittest
from typing import Any, Dict

from agent.etl_pipeline.llm_rec_mapper import (
    map_llm_recommendation_to_action,
    compute_llm_confidence,
)
from agent.etl_pipeline.manual_review_catalog import enrich_manual_review_item
from agent.etl_pipeline.planner import build_etl_plan


class TestLlmRecMapper(unittest.TestCase):
    def test_mapped_action_direct(self) -> None:
        rec = {"mapped_action": "trim", "suggested_fix": "Use uppercase"}
        self.assertEqual(map_llm_recommendation_to_action(rec), "trim")

        rec_case = {"mapped_action": "  Fill_Nulls_Simple  "}
        self.assertEqual(map_llm_recommendation_to_action(rec_case), "fill_nulls_simple")

        rec_invalid = {"mapped_action": "invalid_action", "suggested_fix": "trim whitespace"}
        self.assertEqual(map_llm_recommendation_to_action(rec_invalid), "trim")

    def test_suggested_fix_fallback(self) -> None:
        test_cases = [
            ("Strip trailing whitespace", "trim"),
            ("Please fill null values with average", "fill_nulls_simple"),
            ("Parse date in ISO format", "parse_dates"),
            ("Validate and sanitize email address", "sanitize_email"),
            ("Normalize phone number field", "normalize_phone"),
            ("Deduplicate rows by id", "deduplicate"),
            ("Remove outlier records", "flag_outliers"),
            ("Cast to integer type", "cast_type"),
            ("Convert string to lowercase", "lowercase"),
            ("Convert string to uppercase", "uppercase"),
            ("Drop column because of missing values", "drop_column"),
            ("Random text with no match", "noop"),
        ]
        for fix_text, expected_action in test_cases:
            with self.subTest(fix_text=fix_text):
                rec = {"suggested_fix": fix_text}
                self.assertEqual(map_llm_recommendation_to_action(rec), expected_action)

    def test_compute_llm_confidence(self) -> None:
        # No mapped action should have low confidence
        rec_noop = {"mapped_action": "noop", "severity": "high"}
        self.assertEqual(compute_llm_confidence(rec_noop), 0.10)

        # High severity with mapped action
        rec_high = {
            "mapped_action": "trim",
            "severity": "high",
            "suggested_fix": "Trim spaces",
        }
        # base_conf = 0.80, suggested_fix boost = +0.05
        self.assertAlmostEqual(compute_llm_confidence(rec_high), 0.85)

        # High severity with mapped action + examples
        rec_high_examples = {
            "mapped_action": "trim",
            "severity": "high",
            "suggested_fix": "Trim spaces",
            "example_sql": "SELECT TRIM(col)",
        }
        # base_conf = 0.80 + 0.05 + 0.10 = 0.95
        self.assertAlmostEqual(compute_llm_confidence(rec_high_examples), 0.95)

        # Medium severity
        rec_med = {
            "mapped_action": "fill_nulls_simple",
            "severity": "medium",
            "suggested_fix": "Fill nulls",
        }
        # base_conf = 0.65 + 0.05 = 0.70
        self.assertAlmostEqual(compute_llm_confidence(rec_med), 0.70)


class TestManualReviewEnrichment(unittest.TestCase):
    def test_enrich_with_llm_recommendation(self) -> None:
        item = {
            "dataset": "dbo.customers",
            "column": "email",
            "issue_type": "invalid_email",
            "severity": "medium",
            "message": "Found invalid email formats",
        }
        llm_rec = {
            "dataset": "dbo.customers",
            "column": "email",
            "issue_type": "invalid_email",
            "severity": "medium",
            "suggested_fix": "Sanitize and extract correct email",
            "mapped_action": "sanitize_email",
            "why_it_matters": "Improves communication success rates",
            "risk": "Might drop invalid values if unparseable",
            "example_sql": "SELECT LCASE(TRIM(email))",
        }

        enriched = enrich_manual_review_item(item, llm_recommendation=llm_rec)

        self.assertIn("llm_recommendation", enriched)
        self.assertEqual(enriched["llm_recommendation"], llm_rec)

        options = enriched["resolution_options"]
        self.assertGreater(len(options), 0)

        # First option should be the AI Recommendation
        ai_opt = options[0]
        self.assertEqual(ai_opt["id"], "llm_suggested")
        self.assertTrue(ai_opt["recommended"])
        self.assertEqual(ai_opt["action"], "sanitize_email")
        self.assertIn("AI Recommended", ai_opt["label"])
        self.assertIn("Improves communication", ai_opt["description"])
        self.assertEqual(ai_opt["llm_metadata"]["example_sql"], "SELECT LCASE(TRIM(email))")
        self.assertAlmostEqual(ai_opt["llm_metadata"]["confidence"], 0.80)  # 0.65 + 0.05 + 0.10


class TestPlannerIntegration(unittest.TestCase):
    def test_planner_integrates_high_confidence_llm_rec(self) -> None:
        assessment = {
            "datasets": {
                "dbo.customers": {
                    "columns": {
                        "custom_value": {
                            "null_count": 0,
                            "type": "string",
                        }
                    }
                }
            }
        }
        # In suggestions, we have a rule-based suggestion for trim
        source_context = {
            "suggestions": [
                {
                    "dataset": "dbo.customers",
                    "column": "custom_value",
                    "issue_type": "whitespace_padding",
                    "severity": "medium",
                    "message": "Leading/trailing whitespace",
                    "suggested_action": "trim",
                    "auto_fixable": True,
                }
            ]
        }
        # Provide a high-confidence LLM recommendation
        dq_recs = {
            "recommendations": [
                {
                    "dataset": "dbo.customers",
                    "column": "custom_value",
                    "issue_type": "whitespace_padding",
                    "severity": "high",  # elevates confidence >= 0.80
                    "suggested_fix": "Trim name values",
                    "mapped_action": "trim",
                    "example_sql": "TRIM(name)",
                }
            ]
        }

        plan = build_etl_plan(
            assessment,
            business_rules_raw={},
            source_context=source_context,
            dq_recommendations=dq_recs,
        )

        # High confidence -> should auto-apply
        steps = plan["datasets"]["dbo.customers"]["steps"]
        self.assertEqual(len(steps), 1)
        step = steps[0]
        self.assertEqual(step["action"], "trim")
        self.assertIn("llm_recommendation", step)
        self.assertEqual(step["llm_recommendation"]["suggested_fix"], "Trim name values")

        # manual_review should be empty
        self.assertEqual(len(plan.get("manual_review", [])), 0)

    def test_planner_integrates_low_confidence_llm_rec(self) -> None:
        assessment = {
            "datasets": {
                "dbo.customers": {
                    "columns": {
                        "custom_value": {
                            "null_count": 0,
                            "type": "string",
                        }
                    }
                }
            }
        }
        source_context = {
            "suggestions": [
                {
                    "dataset": "dbo.customers",
                    "column": "custom_value",
                    "issue_type": "invalid_email",
                    "severity": "medium",
                    "message": "Invalid emails found",
                    "suggested_action": "review_manually",
                    "auto_fixable": False,
                }
            ]
        }
        # Provide a low-confidence LLM recommendation (severity = medium)
        dq_recs = {
            "recommendations": [
                {
                    "dataset": "dbo.customers",
                    "column": "custom_value",
                    "issue_type": "invalid_email",
                    "severity": "medium",  # confidence 0.70 < 0.80
                    "suggested_fix": "Fix with email pattern",
                    "mapped_action": "sanitize_email",
                }
            ]
        }

        plan = build_etl_plan(
            assessment,
            business_rules_raw={},
            source_context=source_context,
            dq_recommendations=dq_recs,
        )

        # Low confidence -> should route to manual_review
        steps = plan.get("datasets", {}).get("dbo.customers", {}).get("steps", [])
        self.assertEqual(len(steps), 0)

        manual_items = plan.get("manual_review", [])
        self.assertEqual(len(manual_items), 1)
        item = manual_items[0]
        self.assertEqual(item["dataset"], "dbo.customers")
        self.assertEqual(item["column"], "custom_value")
        self.assertIn("llm_recommendation", item)
        self.assertEqual(item["llm_recommendation"]["suggested_fix"], "Fix with email pattern")

        # Resolution options should have llm_suggested as the first option
        self.assertEqual(item["resolution_options"][0]["id"], "llm_suggested")


if __name__ == "__main__":
    unittest.main()
