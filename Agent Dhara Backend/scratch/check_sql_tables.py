import sys
import os
from dotenv import load_dotenv

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv()

from agent.azure_sql_executor import get_connection
import pandas as pd

try:
    conn = get_connection()
    print("Successfully connected to Azure SQL Database.")
    
    # List all tables in dbo schema
    query = """
    SELECT table_schema, table_name 
    FROM information_schema.tables 
    WHERE table_schema = 'dbo'
    """
    df_tables = pd.read_sql(query, conn)
    print("\nTables in dbo schema:")
    print(df_tables)
    
    # Try querying students_raw_Clean or students_raw
    for name in ["students_raw_Clean", "students_raw", "students_Clean", "students"]:
        try:
            df = pd.read_sql(f"SELECT COUNT(*) as count FROM [dbo].[{name}]", conn)
            print(f"Table [dbo].[{name}] exists. Row count: {df['count'].iloc[0]}")
        except Exception:
            print(f"Table [dbo].[{name}] does not exist or is not readable.")
            
    conn.close()
except Exception as e:
    print(f"Error: {e}")
