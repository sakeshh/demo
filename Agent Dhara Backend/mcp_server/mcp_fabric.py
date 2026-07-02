"""
Dedicated MS Fabric OneLake & Compute Execution MCP Server.
Exposes tools for cloud-to-cloud data ingestion and Fabric Spark / Notebook execution.
"""

from __future__ import annotations

import os
import time
import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, Optional
import requests
from mcp.server.fastmcp import FastMCP
from azure.storage.blob import BlobServiceClient, generate_blob_sas, BlobSasPermissions

# Initialize FastMCP Server
mcp = FastMCP("agent-dhara-ms-fabric")

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("mcp_fabric")


def _get_token(scope: str) -> str:
    """
    Acquire Microsoft Entra ID access token for the given scope using ClientSecretCredential
    or DefaultAzureCredential.
    """
    from azure.identity import DefaultAzureCredential, ClientSecretCredential

    client_id = os.environ.get("FABRIC_CLIENT_ID")
    client_secret = os.environ.get("FABRIC_CLIENT_SECRET")
    tenant_id = os.environ.get("FABRIC_TENANT_ID")

    def _is_placeholder(val: str | None) -> bool:
        if not val:
            return True
        s = val.strip().strip("<>").lower()
        if not s or "your-service-principal" in s or "placeholder" in s or "client-secret-value-here" in s or "client-id-here" in s:
            return True
        return False

    is_sp_configured = (
        client_id and client_secret and tenant_id and
        not _is_placeholder(client_id) and
        not _is_placeholder(client_secret) and
        not _is_placeholder(tenant_id)
    )

    if is_sp_configured:
        cred = ClientSecretCredential(
            tenant_id=tenant_id,
            client_id=client_id,
            client_secret=client_secret
        )
    else:
        cred = DefaultAzureCredential()

    token = cred.get_token(scope)
    return token.token


def _get_source_sas_url(account_name: str, account_key: str, container: str, blob_name: str) -> str:
    """
    Generate a read-only Shared Access Signature (SAS) URL for the source blob.
    """
    sas_token = generate_blob_sas(
        account_name=account_name,
        container_name=container,
        blob_name=blob_name,
        account_key=account_key,
        permission=BlobSasPermissions(read=True),
        expiry=datetime.now(timezone.utc) + timedelta(hours=1)
    )
    return f"https://{account_name}.blob.core.windows.net/{container}/{blob_name}?{sas_token}"


@mcp.tool()
def copy_blob_to_onelake(
    src_account_name: str,
    src_container: str,
    src_blob_name: str,
    workspace_id: str,
    lakehouse_id: str,
    dest_path: str,
    src_account_key: Optional[str] = None
) -> str:
    """
    Perform a direct cloud-to-cloud copy from an Azure Blob Storage to MS Fabric OneLake Files.
    No local data downloads occur.
    """
    # 1. Resolve source credentials
    key = src_account_key or os.environ.get("AZURE_STORAGE_ACCOUNT_KEY")
    if not key:
        return "Error: Missing source storage account key."

    try:
        source_url = _get_source_sas_url(src_account_name, key, src_container, src_blob_name)
    except Exception as e:
        return f"Error generating SAS URL for source blob: {str(e)}"

    # 2. Authenticate to Fabric OneLake (ADLS Gen2 / Blob endpoint)
    try:
        fabric_token = _get_token("https://storage.azure.com/.default")
        fabric_client = BlobServiceClient(
            account_url="https://onelake.blob.fabric.microsoft.com",
            credential=fabric_token
        )
    except Exception as e:
        return f"Error authenticating to Fabric OneLake: {str(e)}"

    # 3. Start Copy directly in the cloud
    try:
        dest_blob_name = f"{lakehouse_id}/Files/{dest_path.lstrip('/')}"
        dest_container_client = fabric_client.get_container_client(workspace_id)
        dest_blob_client = dest_container_client.get_blob_client(dest_blob_name)

        dest_blob_client.start_copy_from_url(source_url)

        # Poll status
        for _ in range(10):
            properties = dest_blob_client.get_blob_properties()
            copy_status = properties.copy.status
            if copy_status == "success":
                return f"Success: Cloud copy complete. Target path: {dest_blob_name}"
            if copy_status == "failed":
                return f"Error: Cloud copy failed. Reason: {properties.copy.status_description}"
            time.sleep(1)

        return f"Asynchronous Copy Triggered. Status: {copy_status}"
    except Exception as e:
        return f"Error copying blob to OneLake: {str(e)}"


@mcp.tool()
def copy_local_file_to_onelake(
    local_path: str,
    workspace_id: str,
    lakehouse_id: str,
    dest_path: str
) -> str:
    """
    Upload a local file directly to Fabric OneLake Files.
    """
    if not os.path.exists(local_path):
        return f"Error: Local file {local_path} does not exist."

    try:
        fabric_token = _get_token("https://storage.azure.com/.default")
        fabric_client = BlobServiceClient(
            account_url="https://onelake.blob.fabric.microsoft.com",
            credential=fabric_token
        )
        dest_blob_name = f"{lakehouse_id}/Files/{dest_path.lstrip('/')}"
        dest_container_client = fabric_client.get_container_client(workspace_id)
        dest_blob_client = dest_container_client.get_blob_client(dest_blob_name)

        with open(local_path, "rb") as f:
            dest_blob_client.upload_blob(f, overwrite=True)

        return f"Success: Uploaded local file to {dest_blob_name}"
    except Exception as e:
        return f"Error uploading local file to OneLake: {str(e)}"


@mcp.tool()
def run_fabric_notebook(
    workspace_id: str,
    notebook_id: str,
    parameters: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Trigger execution of a Microsoft Fabric Notebook using Fabric REST API.
    Returns status and job instance ID.
    """
    try:
        token = _get_token("https://api.fabric.microsoft.com/.default")
    except Exception as e:
        return {"ok": False, "error": f"Failed to acquire Fabric API token: {str(e)}"}

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    url = f"https://api.fabric.microsoft.com/v1/workspaces/{workspace_id}/items/{notebook_id}/jobs/instances?jobType=RunNotebook"
    
    body = {}
    if parameters:
        body["executionParameters"] = parameters

    try:
        response = requests.post(url, headers=headers, json=body)
        if response.status_code == 202:
            location = response.headers.get("Location", "")
            job_instance_id = location.split("/")[-1] if location else "unknown"
            return {
                "ok": True,
                "status": "Accepted",
                "job_instance_id": job_instance_id,
                "message": "Fabric Notebook run triggered successfully."
            }
        return {
            "ok": False,
            "status_code": response.status_code,
            "error": response.text
        }
    except Exception as e:
        return {"ok": False, "error": f"Failed to post notebook job request: {str(e)}"}


@mcp.tool()
def run_fabric_spark_job(
    workspace_id: str,
    job_definition_id: str,
    parameters: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Trigger execution of a Microsoft Fabric Spark Job Definition (SJD) via REST API.
    """
    try:
        token = _get_token("https://api.fabric.microsoft.com/.default")
    except Exception as e:
        return {"ok": False, "error": f"Failed to acquire Fabric API token: {str(e)}"}

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    url = f"https://api.fabric.microsoft.com/v1/workspaces/{workspace_id}/items/{job_definition_id}/jobs/instances?jobType=SparkJobDefinition"
    
    body = {}
    if parameters:
        body["executionParameters"] = parameters

    try:
        response = requests.post(url, headers=headers, json=body)
        if response.status_code == 202:
            location = response.headers.get("Location", "")
            job_instance_id = location.split("/")[-1] if location else "unknown"
            return {
                "ok": True,
                "status": "Accepted",
                "job_instance_id": job_instance_id,
                "message": "Fabric Spark Job Definition run triggered."
            }
        return {
            "ok": False,
            "status_code": response.status_code,
            "error": response.text
        }
    except Exception as e:
        return {"ok": False, "error": f"Failed to post Spark job request: {str(e)}"}


@mcp.tool()
def get_fabric_job_status(
    workspace_id: str,
    item_id: str,
    job_instance_id: str
) -> Dict[str, Any]:
    """
    Query the status of an active Microsoft Fabric job instance.
    """
    try:
        token = _get_token("https://api.fabric.microsoft.com/.default")
    except Exception as e:
        return {"ok": False, "error": f"Failed to acquire Fabric API token: {str(e)}"}

    headers = {
        "Authorization": f"Bearer {token}"
    }
    url = f"https://api.fabric.microsoft.com/v1/workspaces/{workspace_id}/items/{item_id}/jobs/instances/{job_instance_id}"

    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            return {
                "ok": True,
                "job_details": response.json()
            }
        return {
            "ok": False,
            "status_code": response.status_code,
            "error": response.text
        }
    except Exception as e:
        return {"ok": False, "error": f"Failed to fetch job instance status: {str(e)}"}


if __name__ == "__main__":
    mcp.run()
