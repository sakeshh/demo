"""
Test OneLake connectivity using the token from Azure CLI DefaultAzureCredential.
"""
import sys
import os
os.environ["PYTHONIOENCODING"] = "utf-8"
from dotenv import load_dotenv
load_dotenv()
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

WORKSPACE_ID = os.getenv("FABRIC_WORKSPACE_ID", "04a585ce-f0ec-4a3a-9db2-e237711fd9e7")
LAKEHOUSE_ID = os.getenv("FABRIC_LAKEHOUSE_NAME", "abd8c72d-b5aa-4b58-83bd-fb97587de47e")
TENANT_ID    = os.getenv("FABRIC_TENANT_ID", "8ee51404-402a-48a8-8915-e02c8d224a77")

print("=== OneLake Connectivity Test ===")
print(f"Workspace : {WORKSPACE_ID}")
print(f"Lakehouse : {LAKEHOUSE_ID}")

# 1. Get bearer token
print("\n[1] Acquiring storage token via DefaultAzureCredential...")
try:
    from azure.identity import DefaultAzureCredential
    cred = DefaultAzureCredential()
    token_obj = cred.get_token("https://storage.azure.com/.default", tenant_id=TENANT_ID)
    token = token_obj.token
    print(f"    Token acquired OK (length={len(token)})")
except Exception as e:
    print(f"    FAILED: {e}")
    sys.exit(1)

# 2. List Tables in the Lakehouse via OneLake DFS API
print("\n[2] Listing Lakehouse Tables via OneLake DFS REST API...")
import urllib.request
import json

url = (
    f"https://onelake.dfs.fabric.microsoft.com/"
    f"{WORKSPACE_ID}/{LAKEHOUSE_ID}/Tables"
    f"?resource=directory&recursive=false"
)

req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
try:
    with urllib.request.urlopen(req, timeout=20) as resp:
        body = resp.read().decode()
        data = json.loads(body)
        paths = data.get("paths", [])
        if paths:
            print(f"    Found {len(paths)} table(s) in OneLake:")
            for p in paths:
                print(f"      - {p.get('name', p)}")
        else:
            print("    Tables directory is EMPTY (no Delta tables yet).")
except urllib.error.HTTPError as e:
    body = e.read().decode()
    print(f"    HTTP {e.code}: {body[:400]}")
except Exception as e:
    print(f"    Error: {e}")

# 3. Write a small test DataFrame to the Lakehouse
print("\n[3] Writing a small test Delta table to OneLake...")
try:
    import pandas as pd
    from deltalake import write_deltalake

    df = pd.DataFrame({
        "test_id":   [1, 2, 3],
        "message":   ["hello from Dhara", "OneLake write test", "success"],
        "created_at": pd.to_datetime(["2026-06-24", "2026-06-24", "2026-06-24"]),
    })

    target = (
        f"abfss://{WORKSPACE_ID}@onelake.dfs.fabric.microsoft.com"
        f"/{LAKEHOUSE_ID}/Tables/dbo/dhara_connectivity_test"
    )

    storage_opts = {
        "use_fabric_endpoint": "true",
        "bearer_token": token,
    }

    write_deltalake(target, df, mode="overwrite", storage_options=storage_opts, schema_mode="overwrite")
    print(f"    SUCCESS - wrote {len(df)} rows to 'dhara_connectivity_test' table")
    print(f"    URI: {target}")
    print("\n    Check your Fabric Lakehouse - refresh the Tables section to see it!")
except ImportError:
    print("    deltalake library not installed. Run: pip install deltalake")
except Exception as e:
    print(f"    FAILED: {e}")
