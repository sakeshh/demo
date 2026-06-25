import os
import sys
from azure.identity import DefaultAzureCredential

tenant_id = "8ee51404-402a-48a8-8915-e02c8d224a77"
print(f"Setting AZURE_TENANT_ID={tenant_id}")
os.environ["AZURE_TENANT_ID"] = tenant_id

print("Attempting to fetch token...")
try:
    cred = DefaultAzureCredential()
    token_response = cred.get_token("https://storage.azure.com/.default")
    print("SUCCESS!")
    print(f"Token acquired. Expires on: {token_response.expires_on}")
    print(f"Token prefix: {token_response.token[:30]}...")
except Exception as e:
    print("FAILED!")
    print(f"Error: {e}")
    sys.exit(1)
