"""
Diagnostic: Check Fabric Lakehouse connectivity and list what tables are registered.
Run from: Agent Dhara Backend directory
"""
import sys
import os
from dotenv import load_dotenv

load_dotenv()
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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
    
    from connectors.fabric_lakehouse_connector import get_lakehouse_folder
    lh_folder = get_lakehouse_folder(lakehouse_name)
    target_uri = f"abfss://{workspace_id}@onelake.dfs.fabric.microsoft.com/{lh_folder}/Tables"
    print(f"\nTarget ABFSS URI: {target_uri}")
    
    print("\n" + "=" * 60)
    print("CHECKING AUTHENTICATION")
    print("=" * 60)
    
    try:
        from azure.identity import DefaultAzureCredential
        print("azure-identity is installed [OK]")
        
        def _is_placeholder(val: str | None) -> bool:
            if not val:
                return True
            s = val.strip().strip("<>").lower()
            return not s or "your-service-principal" in s or "placeholder" in s or "client-secret-value-here" in s or "client-id-here" in s

        is_sp_set = client_id and client_secret and not _is_placeholder(client_id) and not _is_placeholder(client_secret)

        if not is_sp_set:
            print("\nNo Service Principal configured or placeholders found. Trying DefaultAzureCredential...")
            try:
                cred = DefaultAzureCredential()
                clean_tenant = tenant_id if (tenant_id and not _is_placeholder(tenant_id)) else None
                if clean_tenant:
                    token = cred.get_token("https://storage.azure.com/.default", tenant_id=clean_tenant)
                else:
                    token = cred.get_token("https://storage.azure.com/.default")
                print(f"[OK] Successfully obtained storage token via DefaultAzureCredential")
                print(f"  Token expires at: {token.expires_on}")
            except Exception as e:
                print(f"[ERROR] DefaultAzureCredential failed: {e}")
                print("\n  To fix: Run 'az login' in your terminal, or configure FABRIC_CLIENT_ID and FABRIC_CLIENT_SECRET")
        else:
            print(f"Service Principal configured (Client ID: {client_id[:8]}...)")
            try:
                from azure.identity import ClientSecretCredential
                cred = ClientSecretCredential(tenant_id=tenant_id, client_id=client_id, client_secret=client_secret)
                token = cred.get_token("https://storage.azure.com/.default")
                print(f"[OK] Successfully obtained token via Service Principal")
            except Exception as e:
                print(f"[ERROR] Service Principal auth failed: {e}")
    except ImportError:
        print("[ERROR] azure-identity is NOT installed. Run: pip install azure-identity")
    
    print("\n" + "=" * 60)
    print("CHECKING DELTALAKE LIBRARY")
    print("=" * 60)
    try:
        import deltalake
        print(f"[OK] deltalake is installed (version: {deltalake.__version__})")
    except ImportError:
        print("[ERROR] deltalake is NOT installed. Run: pip install deltalake")
    
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
                from connectors.fabric_lakehouse_connector import get_lakehouse_folder
                lh_folder = get_lakehouse_folder(lakehouse_name)
                dfs_url = f"https://onelake.dfs.fabric.microsoft.com/{workspace_id}/{lh_folder}/Tables/"
                auth_header = opts.get("bearer_token", "")
                headers = {"Authorization": f"Bearer {auth_header}"} if auth_header else {}
                
                resp = requests.get(dfs_url + "?resource=filesystem&recursive=true", headers=headers, timeout=15)
                if resp.status_code == 200:
                    print(f"[OK] Successfully listed OneLake Tables directory")
                    import json
                    data = resp.json()
                    paths = data.get("paths", [])
                    if paths:
                        print(f"  Found {len(paths)} item(s):")
                        for p in paths[:30]:
                            print(f"  - {p.get('name', p)}")
                    else:
                        print("  Tables directory is empty (no Delta tables written yet)")
                elif resp.status_code == 401:
                    print(f"[ERROR] Authentication failed (401). Token may be expired or insufficient permissions.")
                elif resp.status_code == 403:
                    print(f"[ERROR] Authorization denied (403). Service Principal may lack Fabric workspace permissions.")
                else:
                    print(f"[ERROR] HTTP {resp.status_code}: {resp.text[:300]}")
            except Exception as e:
                print(f"Could not list tables: {e}")
    except Exception as e:
        print(f"Error building storage options: {e}")

if __name__ == "__main__":
    main()
