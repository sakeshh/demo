import unittest
from agent.etl_pipeline.dq_gate import calculate_dataset_dq_score, check_dq_gate
from agent.etl_pipeline.phase_classifier import classify_action_phase, split_plan_phases
from agent.etl_pipeline.planner import build_etl_plan
from agent.etl_pipeline.sql_codegen import generate_sql_etl


class TestSprint2Features(unittest.TestCase):
    def setUp(self):
        self.assessment = {
            "datasets": {
                "dbo.Customers_Raw": {
                    "row_count": 1000,
                    "columns": {
                        "CustomerID": {"dtype": "int", "null_percentage": 0.0},
                        "CustomerName": {"dtype": "varchar", "null_percentage": 0.05},
                        "CreatedDate": {"dtype": "varchar", "null_percentage": 0.1},
                    }
                }
            },
            "data_quality_issues": {
                "datasets": {
                    "dbo.Customers_Raw": {
                        "issues": [
                            {"type": "invalid_date_format", "severity": "medium", "column": "CreatedDate"},
                            {"type": "numeric_outliers_iqr", "severity": "medium", "column": "CustomerID"}
                        ]
                    }
                }
            }
        }

    def test_dq_gate_calculation(self):
        # 1. Null score (30% weight): average null % is (0 + 0.05 + 0.1)/3 = 0.05. Null score = 100 * (1 - 0.05)^2 = 90.25
        # 2. Type mismatch score (30% weight): 1 issue (invalid_date_format) -> 100 - 10 = 90
        # 3. Duplicate score (20% weight): 0 dup issues -> 100
        # 4. Outlier score (20% weight): 1 outlier issue -> 100 - 10 = 90
        # Weighted score: (0.3*90.25) + (0.3*90) + (0.2*100) + (0.2*90) = 27.075 + 27.0 + 20.0 + 18.0 = 92.08
        res = calculate_dataset_dq_score(self.assessment, "dbo.Customers_Raw")
        self.assertEqual(res["score"], 92.08)
        self.assertEqual(res["details"]["null_score"], 90.25)
        self.assertEqual(res["details"]["type_score"], 90.0)
        self.assertEqual(res["details"]["duplicate_score"], 100.0)
        self.assertEqual(res["details"]["outlier_score"], 90.0)

        gate_res = check_dq_gate(self.assessment, "dbo.Customers_Raw", threshold=95.0)
        self.assertFalse(gate_res["passed"])
        self.assertEqual(gate_res["score"], 92.08)

    def test_phase_classifier_actions(self):
        self.assertEqual(classify_action_phase("trim"), "cleanse")
        self.assertEqual(classify_action_phase("hash_phone"), "transform")
        self.assertEqual(classify_action_phase("mask_phone"), "transform")
        self.assertEqual(classify_action_phase("replace_values"), "transform")
        self.assertEqual(classify_action_phase("parse_dates"), "cleanse")

    def test_split_plan_phases(self):
        plan = {
            "plan_id": "test_plan",
            "datasets": {
                "dbo.Customers_Raw": {
                    "steps": [
                        {"order": 1, "action": "trim", "column": "CustomerName"},
                        {"order": 2, "action": "hash_phone", "column": "Phone"},
                        {"order": 3, "action": "parse_dates", "column": "CreatedDate"},
                    ]
                }
            }
        }
        cleanse_plan, transform_plan = split_plan_phases(plan)
        
        # Verify cleanse plan steps
        cleanse_steps = cleanse_plan["datasets"]["dbo.Customers_Raw"]["steps"]
        self.assertEqual(len(cleanse_steps), 2)
        self.assertEqual(cleanse_steps[0]["action"], "trim")
        self.assertEqual(cleanse_steps[0]["order"], 1)
        self.assertEqual(cleanse_steps[1]["action"], "parse_dates")
        self.assertEqual(cleanse_steps[1]["order"], 2)

        # Verify transform plan steps
        transform_steps = transform_plan["datasets"]["dbo.Customers_Raw"]["steps"]
        self.assertEqual(len(transform_steps), 1)
        self.assertEqual(transform_steps[0]["action"], "hash_phone")
        self.assertEqual(transform_steps[0]["order"], 1)

    def test_planner_generation_mode_warning(self):
        # Set a very high threshold (e.g. 98.0) to force a DQ gate failure warning
        rules = {"dq_threshold": 98.0}
        plan = build_etl_plan(self.assessment, rules, engine="sql", generation_mode="full")
        self.assertEqual(plan["generation_mode"], "full")
        
        # Check that warning is added to manual reviews
        warnings = [m for m in plan["manual_review"] if m.get("issue_type") == "dq_gate_warning"]
        self.assertTrue(len(warnings) > 0)
        self.assertIn("Data quality score (92.08) is below threshold (98.0)", warnings[0]["message"])

    def test_sql_codegen_generation_modes(self):
        plan = {
            "plan_id": "test_modes",
            "generation_mode": "full",
            "business_rules": {},
            "datasets": {
                "dbo.Customers_Raw": {
                    "steps": [
                        {"order": 1, "action": "trim", "column": "CustomerName"},
                        {"order": 2, "action": "hash_phone", "column": "Phone"},
                    ]
                }
            }
        }
        
        # 1. Full Mode: should generate both clean and transform SPs, and main calls both
        sql_full = generate_sql_etl(plan, self.assessment, dialect="tsql")
        self.assertIn("CREATE PROCEDURE dbo.etl_clean_Customers", sql_full)
        self.assertIn("CREATE PROCEDURE dbo.etl_transform_Customers", sql_full)
        self.assertIn("EXEC dbo.etl_clean_Customers", sql_full)
        self.assertIn("EXEC dbo.etl_transform_Customers", sql_full)
        
        # 2. Cleanse Only Mode
        plan["generation_mode"] = "cleanse_only"
        sql_cleanse = generate_sql_etl(plan, self.assessment, dialect="tsql")
        self.assertIn("CREATE PROCEDURE dbo.etl_clean_Customers", sql_cleanse)
        self.assertNotIn("CREATE PROCEDURE dbo.etl_transform_Customers", sql_cleanse)
        self.assertIn("EXEC dbo.etl_clean_Customers", sql_cleanse)
        self.assertNotIn("EXEC dbo.etl_transform_Customers", sql_cleanse)

        # 3. Transform Only Mode
        plan["generation_mode"] = "transform_only"
        sql_transform = generate_sql_etl(plan, self.assessment, dialect="tsql")
        self.assertNotIn("CREATE PROCEDURE dbo.etl_clean_Customers", sql_transform)
        self.assertIn("CREATE PROCEDURE dbo.etl_transform_Customers", sql_transform)
        self.assertNotIn("EXEC dbo.etl_clean_Customers", sql_transform)
        self.assertIn("EXEC dbo.etl_transform_Customers", sql_transform)


if __name__ == "__main__":
    unittest.main()
