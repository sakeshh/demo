"""
fabric_lakehouse_connector.py - Fabric OneLake Delta Lake Connector

Writes pandas DataFrames directly to Microsoft Fabric Lakehouse (OneLake)
as Delta Tables using the `deltalake` library (delta-rs).
"""

import os
import re
import logging
from typing import Dict, Any, Optional
import pandas as pd

logger = logging.getLogger("connectors.fabric_lakehouse_connector")

def _clean_env_value(v: Optional[str]) -> Optional[str]:
    """
    Be resilient to env var quoting/pasting issues:
    - trim whitespace/newlines
    - remove surrounding quotes
    """
    if v is None:
        return None
    s = str(v).strip()
    if len(s) >= 2 and ((s[0] == s[-1] == '"') or (s[0] == s[-1] == "'")):
        s = s[1:-1].strip()
    return s

def _is_uuid(val: str) -> bool:
    """Check if the string is a valid UUID."""
    val_clean = val.lower().strip()
    return bool(re.match(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", val_clean))

def _is_placeholder(val: Optional[str]) -> bool:
    """Check if the string is a default template/placeholder value."""
    if not val:
        return True
    s = val.strip().strip("<>").lower()
    if not s or "your-service-principal" in s or "placeholder" in s or "client-secret-value-here" in s or "client-id-here" in s:
        return True
    return False

def get_lakehouse_folder(lakehouse: str) -> str:
    """
    Determine the physical directory name of the Lakehouse.
    Names (like 'Dhara_Lake') are postfixed with '.Lakehouse' in OneLake.
    UUIDs are used as-is.
    """
    lh = lakehouse.strip()
    if not lh.lower().endswith(".lakehouse") and not _is_uuid(lh):
        return f"{lh}.Lakehouse"
    return lh

def is_fabric_mirror_enabled() -> bool:
    """Check if Fabric mirroring is explicitly enabled in env."""
    enabled_val = _clean_env_value(os.getenv("DHARA_FABRIC_MIRROR_ENABLED"))
    return enabled_val in ("1", "true", "TRUE", "yes", "YES")

def get_fabric_storage_options() -> Dict[str, str]:
    """
    Build the storage options dictionary for delta-rs.
    If Service Principal credentials are provided in env, use them.
    Otherwise, fall back to DefaultAzureCredential (e.g. Azure CLI 'az login' credentials).
    """
    tenant_id = _clean_env_value(os.getenv("FABRIC_TENANT_ID"))
    client_id = _clean_env_value(os.getenv("FABRIC_CLIENT_ID"))
    client_secret = _clean_env_value(os.getenv("FABRIC_CLIENT_SECRET"))

    options = {
        "use_fabric_endpoint": "true"
    }

    # If Service Principal is configured, use it
    if client_id and client_secret and not _is_placeholder(client_id) and not _is_placeholder(client_secret):
        logger.info("Using Service Principal authentication for Fabric OneLake.")
        options["client_id"] = client_id
        options["client_secret"] = client_secret
        if tenant_id and not _is_placeholder(tenant_id):
            options["tenant_id"] = tenant_id
        return options

    # Fallback: Try fetching bearer token using DefaultAzureCredential (e.g. Azure CLI)
    logger.info("Service Principal credentials not fully configured or are placeholders. Attempting token-based authentication via DefaultAzureCredential...")
    try:
        from azure.identity import DefaultAzureCredential
        clean_tenant = tenant_id if (tenant_id and not _is_placeholder(tenant_id)) else None
        if clean_tenant:
            os.environ["AZURE_TENANT_ID"] = clean_tenant
            cred = DefaultAzureCredential()
            token_response = cred.get_token("https://storage.azure.com/.default", tenant_id=clean_tenant)
        else:
            cred = DefaultAzureCredential()
            token_response = cred.get_token("https://storage.azure.com/.default")
        options["bearer_token"] = token_response.token
        logger.info("Successfully acquired storage access token via DefaultAzureCredential.")
    except Exception as e:
        logger.warning(f"Could not acquire token via DefaultAzureCredential: {e}. "
                       f"Please ensure you have configured Azure CLI and executed 'az login' in your shell.")

    return options

def write_to_lakehouse(df: pd.DataFrame, table_name: str, mode: str = "overwrite") -> Dict[str, Any]:
    """
    Writes a pandas DataFrame to Fabric OneLake as a Delta table.
    
    Args:
        df: The pandas DataFrame to write.
        table_name: The target table name (becomes folder in Tables/ zone).
        mode: Write mode ('overwrite' or 'append').
        
    Returns:
        A dictionary summarizing the result of the write operation.
    """
    if df.empty:
        logger.warning(f"DataFrame is empty, skipping Fabric mirror for table {table_name}")
        return {"ok": True, "status": "skipped", "message": "DataFrame is empty"}

    workspace = _clean_env_value(os.getenv("FABRIC_WORKSPACE_ID") or os.getenv("FABRIC_WORKSPACE_NAME"))
    lakehouse = _clean_env_value(os.getenv("FABRIC_LAKEHOUSE_NAME") or os.getenv("FABRIC_LAKEHOUSE_ID"))

    if not workspace or not lakehouse:
        err_msg = "Fabric Workspace ID/Name or Lakehouse Name/ID is not configured in environment."
        logger.error(err_msg)
        return {"ok": False, "error": "MISSING_CONFIG", "message": err_msg}

    # Parse schema and table name (default schema is 'dbo')
    parts = table_name.split(".", 1)
    if len(parts) == 2:
        schema = re.sub(r'[^a-zA-Z0-9_]', '_', parts[0])
        safe_table_name = re.sub(r'[^a-zA-Z0-9_]', '_', parts[1])
    else:
        schema = "dbo"
        safe_table_name = re.sub(r'[^a-zA-Z0-9_]', '_', parts[0])

    lakehouse_folder = get_lakehouse_folder(lakehouse)

    # Build the ABFSS target URI preserving the schema
    target_uri = f"abfss://{workspace}@onelake.dfs.fabric.microsoft.com/{lakehouse_folder}/Tables/{schema}/{safe_table_name}"
    
    logger.info(f"Preparing to write to Fabric Lakehouse: {target_uri}")

    try:
        from deltalake import write_deltalake
    except ImportError as ie:
        err_msg = "The 'deltalake' library is not installed. Run 'pip install deltalake'."
        logger.error(err_msg, exc_info=ie)
        return {"ok": False, "error": "LIBRARY_NOT_FOUND", "message": err_msg}

    storage_options = get_fabric_storage_options()

    try:
        write_deltalake(
            target_uri,
            df,
            mode=mode,
            storage_options=storage_options,
            schema_mode="overwrite" if mode == "overwrite" else None
        )
        logger.info(f"Successfully mirrored table {safe_table_name} to Fabric Lakehouse in {mode} mode.")
        return {
            "ok": True,
            "status": "success",
            "table": safe_table_name,
            "uri": target_uri,
            "mode": mode,
            "rows": len(df)
        }
    except Exception as e:
        logger.exception(f"Failed to write Delta table {safe_table_name} to Fabric OneLake: {e}")
        return {
            "ok": False,
            "error": "WRITE_FAILED",
            "message": str(e),
            "table": safe_table_name,
            "uri": target_uri
        }
