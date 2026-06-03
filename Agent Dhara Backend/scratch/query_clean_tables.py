import os
import sys
from dotenv import load_dotenv

backend_dir = r"c:\Users\ssakesh\Documents\DHARA-GX\Agent Dhara Backend"
dotenv_path = os.path.join(backend_dir, ".env")
load_dotenv(dotenv_path)

sys.path.append(backend_dir)
from agent.azure_sql_executor import get_connection

try:
    conn = get_connection()
    cursor = conn.cursor()
    
    # Check Customers_Clean
    try:
        cursor.execute("SELECT COUNT(*) FROM dbo.Customers_Clean")
        cnt = cursor.fetchone()[0]
        print(f"dbo.Customers_Clean row count: {cnt}")
        
        cursor.execute("SELECT TOP 5 CustomerID, CustomerName, City, Email, Phone, etl_created_at FROM dbo.Customers_Clean")
        rows = cursor.fetchall()
        print("Sample rows from dbo.Customers_Clean:")
        for r in rows:
            print("  ", r)
    except Exception as e:
        print("Error reading dbo.Customers_Clean:", e)

    # Check Orders_Clean
    try:
        cursor.execute("SELECT COUNT(*) FROM dbo.Orders_Clean")
        cnt = cursor.fetchone()[0]
        print(f"dbo.Orders_Clean row count: {cnt}")
        
        cursor.execute("SELECT TOP 5 OrderID, CustomerID, OrderAmount, OrderDate, OrderStatus FROM dbo.Orders_Clean")
        rows = cursor.fetchall()
        print("Sample rows from dbo.Orders_Clean:")
        for r in rows:
            print("  ", r)
    except Exception as e:
        print("Error reading dbo.Orders_Clean:", e)

except Exception as e:
    print("Database connection failed:", e)
