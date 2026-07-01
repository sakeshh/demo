import os
import sys
import unittest
from unittest.mock import patch, MagicMock

# Mock deltalake module so the tests can run without the package installed
mock_deltalake = MagicMock()
sys.modules['deltalake'] = mock_deltalake

import pandas as pd
from connectors.fabric_lakehouse_connector import (
    _clean_env_value,
    _is_uuid,
    get_lakehouse_folder,
    is_fabric_mirror_enabled,
    get_fabric_storage_options,
    write_to_lakehouse
)
from agent.etl_handlers import etl_execute_sql

class TestFabricLakehouseConnector(unittest.TestCase):
    def test_clean_env_value(self):
        self.assertIsNone(_clean_env_value(None))
        self.assertEqual(_clean_env_value(' "my-workspace" '), "my-workspace")
        self.assertEqual(_clean_env_value("'my-secret'"), "my-secret")
        self.assertEqual(_clean_env_value("no-quotes"), "no-quotes")

    def test_is_uuid(self):
        self.assertTrue(_is_uuid("12345678-1234-1234-1234-123456789012"))
        self.assertFalse(_is_uuid("Dhara_Lake"))
        self.assertFalse(_is_uuid("12345678-1234-1234-1234-12345678901"))

    def test_get_lakehouse_folder(self):
        self.assertEqual(get_lakehouse_folder("Dhara_Lake"), "Dhara_Lake.Lakehouse")
        self.assertEqual(get_lakehouse_folder("Dhara_Lake.Lakehouse"), "Dhara_Lake.Lakehouse")
        uuid_str = "12345678-1234-1234-1234-123456789012"
        self.assertEqual(get_lakehouse_folder(uuid_str), uuid_str)

    @patch.dict(os.environ, {
        "DHARA_FABRIC_MIRROR_ENABLED": "1"
    })
    def test_is_fabric_mirror_enabled(self):
        self.assertTrue(is_fabric_mirror_enabled())

    @patch.dict(os.environ, {
        "DHARA_FABRIC_MIRROR_ENABLED": "0"
    })
    def test_is_fabric_mirror_disabled(self):
        self.assertFalse(is_fabric_mirror_enabled())

    @patch.dict(os.environ, {
        "FABRIC_TENANT_ID": "tenant-1",
        "FABRIC_CLIENT_ID": "client-1",
        "FABRIC_CLIENT_SECRET": "secret-1"
    })
    def test_get_fabric_storage_options(self):
        opts = get_fabric_storage_options()
        self.assertEqual(opts.get("tenant_id"), "tenant-1")
        self.assertEqual(opts.get("client_id"), "client-1")
        self.assertEqual(opts.get("client_secret"), "secret-1")
        self.assertEqual(opts.get("use_fabric_endpoint"), "true")

    @patch("azure.identity.DefaultAzureCredential")
    @patch.dict(os.environ, {
        "FABRIC_TENANT_ID": "",
        "FABRIC_CLIENT_ID": "",
        "FABRIC_CLIENT_SECRET": ""
    }, clear=True)
    def test_get_fabric_storage_options_token_fallback(self, mock_cred_cls):
        mock_cred = MagicMock()
        mock_token = MagicMock()
        mock_token.token = "mock-token-value"
        mock_cred.get_token.return_value = mock_token
        mock_cred_cls.return_value = mock_cred

        opts = get_fabric_storage_options()
        self.assertEqual(opts.get("bearer_token"), "mock-token-value")
        self.assertEqual(opts.get("use_fabric_endpoint"), "true")
        mock_cred.get_token.assert_called_once_with("https://storage.azure.com/.default")

    @patch.dict(os.environ, {
        "FABRIC_WORKSPACE_ID": "ws-123",
        "FABRIC_LAKEHOUSE_NAME": "Dhara_Lake",
        "FABRIC_TENANT_ID": "tenant-1",
        "FABRIC_CLIENT_ID": "client-1",
        "FABRIC_CLIENT_SECRET": "secret-1"
    })
    def test_write_to_lakehouse_success(self):
        # Reset mock before call
        mock_deltalake.write_deltalake.reset_mock()
        df = pd.DataFrame({"id": [1, 2], "val": ["a", "b"]})
        res = write_to_lakehouse(df, "dbo.Customers_Clean")
        
        self.assertTrue(res["ok"])
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["table"], "Customers_Clean")
        self.assertEqual(res["uri"], "abfss://ws-123@onelake.dfs.fabric.microsoft.com/Dhara_Lake.Lakehouse/Tables/dbo/Customers_Clean")
        
        mock_deltalake.write_deltalake.assert_called_once_with(
            "abfss://ws-123@onelake.dfs.fabric.microsoft.com/Dhara_Lake.Lakehouse/Tables/dbo/Customers_Clean",
            df,
            mode="overwrite",
            storage_options={
                "use_fabric_endpoint": "true",
                "tenant_id": "tenant-1",
                "client_id": "client-1",
                "client_secret": "secret-1"
            },
            schema_mode="overwrite"
        )

    def test_write_to_lakehouse_empty_df(self):
        df = pd.DataFrame()
        res = write_to_lakehouse(df, "dbo.Customers_Clean")
        self.assertTrue(res["ok"])
        self.assertEqual(res["status"], "skipped")


class TestFabricMirrorHandlerHook(unittest.TestCase):
    @patch("agent.etl_handlers.load_session")
    @patch("agent.etl_handlers.save_session")
    @patch("agent.etl_handlers._get_assessment")
    @patch("connectors.fabric_lakehouse_connector.is_fabric_mirror_enabled")
    @patch("connectors.fabric_lakehouse_connector.write_to_lakehouse")
    @patch("agent.azure_sql_executor.get_connection")
    @patch("agent.etl_pipeline.execution_orchestrator.orchestrate_sql_execution")
    @patch("pandas.read_sql")
    def test_etl_execute_sql_with_fabric_mirror_enabled(
        self,
        mock_read_sql,
        mock_orchestrate,
        mock_get_conn,
        mock_write,
        mock_mirror_enabled,
        mock_get_assess,
        mock_save_session,
        mock_load_session
    ):
        # Setup mocks
        mock_mirror_enabled.return_value = True
        
        dummy_flow = {
            "phase": "code_ready",
            "target_engine": "sql",
            "code": "SELECT 1;",
            "approved_plan": {
                "datasets": {
                    "dbo.Customers_Raw": {}
                }
            }
        }
        mock_load_session.return_value = {
            "context": {
                "etl_flow": dummy_flow
            }
        }
        
        mock_orchestrate.return_value = {"ok": True, "post_execution_summary": "Executed OK"}
        mock_get_assess.return_value = {}
        
        # Setup read_sql to return a dummy df
        dummy_df = pd.DataFrame({"id": [1], "name": ["Alice"]})
        mock_read_sql.return_value = dummy_df
        
        # Setup write_to_lakehouse response
        mock_write.return_value = {"ok": True, "table": "Customers_Clean"}

        # Execute handler
        res = etl_execute_sql("session-123", approved=True)
        
        # Assertions
        self.assertTrue(res["ok"])
        mock_orchestrate.assert_called_once()
        mock_get_conn.assert_called_once()
        mock_read_sql.assert_called_once()
        
        # Verify write_to_lakehouse was called with correct clean table name
        mock_write.assert_called_once()
        called_args = mock_write.call_args[0]
        self.assertEqual(called_args[1], "dbo.Customers_Clean") # table name
        pd.testing.assert_frame_equal(called_args[0], dummy_df)
        
        # Verify flow results stored
        self.assertIn("fabric_mirror_result", dummy_flow)
        self.assertTrue(dummy_flow["fabric_mirror_result"]["ok"])
        self.assertEqual(dummy_flow["fabric_mirror_result"]["details"][0]["table"], "Customers_Clean")


if __name__ == "__main__":
    unittest.main()
