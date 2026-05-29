import unittest
import re
from agent.etl_pipeline.sql_codegen import generate_sql_etl


class TestSprint3Features(unittest.TestCase):
    def setUp(self):
        self.assessment = {
            "datasets": {
                "dbo.Customers_Raw": {
                    "row_count": 1000,
                    "columns": {
                        "CustomerID": {"dtype": "int", "null_percentage": 0.0, "candidate_primary_key": True},
                        "CustomerName": {"dtype": "varchar", "null_percentage": 0.05},
                        "CreatedDate": {"dtype": "varchar", "null_percentage": 0.1},
                        "OrderStatus": {"dtype": "varchar", "null_percentage": 0.02},
                    }
                }
            }
        }
        
    def test_s3_05_quality_badge_in_header(self):
        plan = {
            "plan_id": "test_s3_05",
            "generation_mode": "full",
            "business_rules": {},
            "datasets": {
                "dbo.Customers_Raw": {
                    "steps": []
                }
            }
        }
        sql = generate_sql_etl(plan, self.assessment, dialect="tsql")
        self.assertIn("SQL QUALITY ASSESSMENT BADGE", sql)
        self.assertIn("Score:", sql)
        self.assertIn("Grade:", sql)
        
    def test_s3_02_preflight_assertions(self):
        plan = {
            "plan_id": "test_s3_02",
            "generation_mode": "full",
            "business_rules": {
                "non_nullable": ["CustomerName"],
                "valid_values": {
                    "OrderStatus": ["Pending", "Shipped", "Delivered"]
                }
            },
            "datasets": {
                "dbo.Customers_Raw": {
                    "steps": []
                }
            }
        }
        sql = generate_sql_etl(plan, self.assessment, dialect="tsql")
        # Check preflight DECLAREs are generated
        self.assertIn("DECLARE @null_count_CustomerName INT", sql)
        self.assertIn("DECLARE @invalid_count_OrderStatus INT", sql)
        self.assertIn("Preflight check: column [CustomerName] has", sql)
        self.assertIn("Preflight check: column [OrderStatus] has", sql)
        self.assertIn("NOT IN (N'Pending', N'Shipped', N'Delivered')", sql)
        
    def test_s3_01_post_load_row_count_assertion(self):
        plan = {
            "plan_id": "test_s3_01",
            "generation_mode": "full",
            "business_rules": {},
            "datasets": {
                "dbo.Customers_Raw": {
                    "steps": []
                }
            }
        }
        sql = generate_sql_etl(plan, self.assessment, dialect="tsql")
        self.assertIn("DECLARE @staging_rows INT = (SELECT COUNT(*) FROM #Customers_Raw_Staging);", sql)
        self.assertIn("DECLARE @target_rows INT = (SELECT COUNT(*) FROM [dbo].[Customers_Clean]);", sql)
        self.assertIn("RAISERROR('Post-load assertion failed: Target table is empty but staging had rows.', 16, 1);", sql)

    def test_s3_03_merge_holdlock(self):
        plan = {
            "plan_id": "test_s3_03",
            "generation_mode": "full",
            "business_rules": {},
            "datasets": {
                "dbo.Customers_Raw": {
                    "steps": []
                }
            }
        }
        sql = generate_sql_etl(plan, self.assessment, dialect="tsql")
        self.assertIn("MERGE INTO dbo.etl_watermark WITH (HOLDLOCK) AS target", sql)

    def test_s3_04_scd_patterns(self):
        # 1. SCD Type 2
        plan_t2 = {
            "plan_id": "test_s3_04_t2",
            "generation_mode": "full",
            "business_rules": {},
            "datasets": {
                "dbo.Customers_Raw": {
                    "scd_type": "type2",
                    "steps": []
                }
            }
        }
        sql_t2 = generate_sql_etl(plan_t2, self.assessment, dialect="tsql")
        self.assertIn("start_date DATETIME DEFAULT GETDATE()", sql_t2)
        self.assertIn("end_date DATETIME DEFAULT '9999-12-31'", sql_t2)
        self.assertIn("is_current BIT DEFAULT 1", sql_t2)
        self.assertIn("CONSTRAINT [PK_Customers_Raw_Clean] PRIMARY KEY ([CustomerID], start_date)", sql_t2)
        self.assertIn("UPDATE target", sql_t2)
        self.assertIn("SET target.end_date = GETDATE(), target.is_current = 0", sql_t2)
        self.assertIn("INSERT INTO [dbo].[Customers_Clean]", sql_t2)
        self.assertIn("GETDATE(), '9999-12-31', 1", sql_t2)

        # 2. Append-only
        plan_app = {
            "plan_id": "test_s3_04_app",
            "generation_mode": "full",
            "business_rules": {},
            "datasets": {
                "dbo.Customers_Raw": {
                    "scd_type": "append",
                    "steps": []
                }
            }
        }
        sql_app = generate_sql_etl(plan_app, self.assessment, dialect="tsql")
        self.assertNotIn("TRUNCATE TABLE [dbo].[Customers_Clean];", sql_app)
        self.assertNotIn("DELETE FROM [dbo].[Customers_Clean]", sql_app)

        # 3. Truncate
        plan_trunc = {
            "plan_id": "test_s3_04_trunc",
            "generation_mode": "full",
            "business_rules": {},
            "datasets": {
                "dbo.Customers_Raw": {
                    "scd_type": "truncate",
                    "steps": []
                }
            }
        }
        sql_trunc = generate_sql_etl(plan_trunc, self.assessment, dialect="tsql")
        self.assertIn("TRUNCATE TABLE [dbo].[Customers_Clean];", sql_trunc)


if __name__ == "__main__":
    unittest.main()
