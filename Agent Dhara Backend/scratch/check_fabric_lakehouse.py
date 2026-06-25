"""
Diagnostic: Check Fabric Lakehouse connectivity and list what tables are registered.
Run from: Agent Dhara Backend directory
"""
import sys
import os
from dotenv import load_dotenv

load_dotenv()
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

def main():
    print("=" * 60)
    print("FABRIC LAKEHOUSE CONFIGURATION")
    print("=" * 60)
    
    workspace_id = os.getenv("FABRIC_WORKSPACE_ID")
    lakehouse_name = os.getenv("FABRIC_LAKEHOUSE_NAME")
    tenant_id = os.getenv("FABRIC_TENANT_ID")
    client_id = os.getenv("FABRIC_CLIENT_ID")
    client_secret = os.getenv("FABRIC_CLIENT_SECRET")
    mirror_enabled = os.getenv("DHARA_FABRIC_MIRROR_ENABLED")

    print(f"Mirror Enabled:   {mirror_enabled}")
    print(f"Workspace ID:     {workspace_id}")
    print(f"Lakehouse ID:     {lakehouse_name}")
    print(f"Tenant ID:        {tenant_id}")
    print(f"Client ID:        {'SET' if client_id else 'NOT SET (will use DefaultAzureCredential)'}")
    print(f"Client Secret:    {'SET' if client_secret else 'NOT SET'}")
    
    target_uri = f"abfss://{workspace_id}@onelake.dfs.fabric.microsoft.com/{lakehouse_name}.Lakehouse/Tables"
    print(f"\nTarget ABFSS URI: {target_uri}")
    
    print("\n" + "=" * 60)
    print("CHECKING AUTHENTICATION")
    print("=" * 60)
    
    try:
        from azure.identity import DefaultAzureCredential
        print("azure-identity is installed ✓")
        
        if not client_id or not client_secret:
            print("\nNo Service Principal configured. Trying DefaultAzureCredential (Azure CLI)...")
            try:
                cred = DefaultAzureCredential()
                token = cred.get_token("https://storage.azure.com/.default", tenant_id=tenant_id)
                print(f"✓ Successfully obtained storage token via DefaultAzureCredential")
                print(f"  Token expires at: {token.expires_on}")
            except Exception as e:
                print(f"✗ DefaultAzureCredential failed: {e}")
                print("\n  To fix: Run 'az login' in your terminal, or configure FABRIC_CLIENT_ID and FABRIC_CLIENT_SECRET")
        else:
            print(f"Service Principal configured (Client ID: {client_id[:8]}...)")
            try:
                from azure.identity import ClientSecretCredential
                cred = ClientSecretCredential(tenant_id=tenant_id, client_id=client_id, client_secret=client_secret)
                token = cred.get_token("https://storage.azure.com/.default")
                print(f"✓ Successfully obtained token via Service Principal")
            except Exception as e:
                print(f"✗ Service Principal auth failed: {e}")
    except ImportError:
        print("✗ azure-identity is NOT installed. Run: pip install azure-identity")
    
    print("\n" + "=" * 60)
    print("CHECKING DELTALAKE LIBRARY")
    print("=" * 60)
    try:
        import deltalake
        print(f"✓ deltalake is installed (version: {deltalake.__version__})")
    except ImportError:
        print("✗ deltalake is NOT installed. Run: pip install deltalake")
    
    print("\n" + "=" * 60)
    print("CHECKING ONELAKE CONNECTIVITY")
    print("=" * 60)
    
    try:
        from connectors.fabric_lakehouse_connector import get_fabric_storage_options
        opts = get_fabric_storage_options()
        has_token = "bearer_token" in opts or ("client_id" in opts and "client_secret" in opts)
        print(f"Storage options built: {list(opts.keys())}")
        print(f"Authentication token present: {has_token}")
        
        if has_token:
            print("\nAttempting to list Lakehouse Tables directory...")
            try:
                from deltalake import DeltaTable
                from deltalake.exceptions import DeltaError
                # Try listing the tables root
                import requests
                
                # Build DFS URL for listing
                dfs_url = f"https://onelake.dfs.fabric.microsoft.com/{workspace_id}/{lakehouse_name}.Lakehouse/Tables/"
                auth_header = opts.get("bearer_token", "")
                headers = {"Authorization": f"Bearer {auth_header}"} if auth_header else {}
                
                resp = requests.get(dfs_url + "?resource=filesystem&recursive=false", headers=headers, timeout=15)
                if resp.status_code == 200:
                    print(f"✓ Successfully listed OneLake Tables directory")
                    import json
                    data = resp.json()
                    paths = data.get("paths", [])
                    if paths:
                        print(f"  Found {len(paths)} item(s):")
                        for p in paths[:20]:
                            print(f"  - {p.get('name', p)}")
                    else:
                        print("  Tables directory is empty (no Delta tables written yet)")
                elif resp.status_code == 401:
                    print(f"✗ Authentication failed (401). Token may be expired or insufficient permissions.")
                elif resp.status_code == 403:
                    print(f"✗ Authorization denied (403). Service Principal may lack Fabric workspace permissions.")
                else:
                    print(f"✗ HTTP {resp.status_code}: {resp.text[:300]}")
            except Exception as e:
                print(f"Could not list tables: {e}")
    except Exception as e:
        print(f"Error building storage options: {e}")

if __name__ == "__main__":
    main()
