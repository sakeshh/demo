import os
import pyodbc
from dotenv import load_dotenv

load_dotenv()

server = os.environ.get("AZURE_SQL_SERVER") + ".database.windows.net"
database = os.environ.get("AZURE_SQL_DATABASE")
username = os.environ.get("AZURE_SQL_USERNAME")
password = os.environ.get("AZURE_SQL_PASSWORD")

driver = '{SQL Server}'
conn_str = f"DRIVER={driver};SERVER={server};PORT=1433;DATABASE={database};UID={username};PWD={password}"

sql_script = """
BEGIN TRY
    BEGIN TRANSACTION;

    -------------------------------------------------------------------
    -- 1. PROCESSING dbo.Orders_Raw
    -------------------------------------------------------------------
    
    -- Drop flag columns if they exist
    IF EXISTS (SELECT 1 FROM sys.columns WHERE object_id = OBJECT_ID('dbo.Orders_Raw') AND name = 'CustomerID_outlier_flagged')
        ALTER TABLE dbo.Orders_Raw DROP COLUMN CustomerID_outlier_flagged;
    IF EXISTS (SELECT 1 FROM sys.columns WHERE object_id = OBJECT_ID('dbo.Orders_Raw') AND name = 'OrderAmount_outlier_flagged')
        ALTER TABLE dbo.Orders_Raw DROP COLUMN OrderAmount_outlier_flagged;

    -- DELETE rows with NULLs, invalid text ('abc', 'N/A'), or negative OrderAmount
    DELETE FROM dbo.Orders_Raw 
    WHERE TRY_CAST(OrderAmount AS FLOAT) IS NULL 
       OR TRY_CAST(OrderAmount AS FLOAT) < 0
       OR CustomerID IS NULL;

    -- Cast CustomerID to BIGINT
    UPDATE dbo.Orders_Raw SET CustomerID = TRY_CAST(CustomerID AS BIGINT);

    -- Clip CustomerID outliers
    DECLARE @q1 FLOAT, @q3 FLOAT, @iqr FLOAT, @lb FLOAT, @ub FLOAT;
    SELECT TOP 1 @q1 = PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY TRY_CAST(CustomerID AS FLOAT)) OVER(),
                 @q3 = PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY TRY_CAST(CustomerID AS FLOAT)) OVER()
    FROM dbo.Orders_Raw;
    
    SET @iqr = @q3 - @q1; 
    SET @lb = @q1 - 1.5*@iqr; 
    SET @ub = @q3 + 1.5*@iqr;
    
    UPDATE dbo.Orders_Raw 
    SET CustomerID = CASE 
                        WHEN TRY_CAST(CustomerID AS FLOAT) < @lb THEN @lb 
                        WHEN TRY_CAST(CustomerID AS FLOAT) > @ub THEN @ub 
                        ELSE CustomerID 
                     END;

    -- Clip OrderAmount outliers
    DECLARE @q1_oa FLOAT, @q3_oa FLOAT, @iqr_oa FLOAT, @lb_oa FLOAT, @ub_oa FLOAT;
    SELECT TOP 1 @q1_oa = PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY TRY_CAST(OrderAmount AS FLOAT)) OVER(),
                 @q3_oa = PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY TRY_CAST(OrderAmount AS FLOAT)) OVER()
    FROM dbo.Orders_Raw;
    
    SET @iqr_oa = @q3_oa - @q1_oa; 
    SET @lb_oa = @q1_oa - 1.5*@iqr_oa; 
    SET @ub_oa = @q3_oa + 1.5*@iqr_oa;
    
    UPDATE dbo.Orders_Raw 
    SET OrderAmount = CASE 
                        WHEN TRY_CAST(OrderAmount AS FLOAT) < @lb_oa THEN @lb_oa 
                        WHEN TRY_CAST(OrderAmount AS FLOAT) > @ub_oa THEN @ub_oa 
                        ELSE OrderAmount 
                      END;


    -------------------------------------------------------------------
    -- 2. PROCESSING dbo.Sales_Raw
    -------------------------------------------------------------------
    
    -- Drop flag columns if they exist
    IF EXISTS (SELECT 1 FROM sys.columns WHERE object_id = OBJECT_ID('dbo.Sales_Raw') AND name = 'OrderID_outlier_flagged')
        ALTER TABLE dbo.Sales_Raw DROP COLUMN OrderID_outlier_flagged;
    IF EXISTS (SELECT 1 FROM sys.columns WHERE object_id = OBJECT_ID('dbo.Sales_Raw') AND name = 'TotalAmount_outlier_flagged')
        ALTER TABLE dbo.Sales_Raw DROP COLUMN TotalAmount_outlier_flagged;

    -- DELETE rows with NULLs, invalid text, or negative TotalAmount
    DELETE FROM dbo.Sales_Raw 
    WHERE TRY_CAST(TotalAmount AS FLOAT) IS NULL 
       OR TRY_CAST(TotalAmount AS FLOAT) < 0
       OR OrderID IS NULL;

    -- Cast OrderID to BIGINT
    UPDATE dbo.Sales_Raw SET OrderID = TRY_CAST(OrderID AS BIGINT);

    -- Clip OrderID outliers
    DECLARE @q1_oid FLOAT, @q3_oid FLOAT, @iqr_oid FLOAT, @lb_oid FLOAT, @ub_oid FLOAT;
    SELECT TOP 1 @q1_oid = PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY TRY_CAST(OrderID AS FLOAT)) OVER(),
                 @q3_oid = PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY TRY_CAST(OrderID AS FLOAT)) OVER()
    FROM dbo.Sales_Raw;
    
    SET @iqr_oid = @q3_oid - @q1_oid; 
    SET @lb_oid = @q1_oid - 1.5*@iqr_oid; 
    SET @ub_oid = @q3_oid + 1.5*@iqr_oid;
    
    UPDATE dbo.Sales_Raw 
    SET OrderID = CASE 
                    WHEN TRY_CAST(OrderID AS FLOAT) < @lb_oid THEN @lb_oid 
                    WHEN TRY_CAST(OrderID AS FLOAT) > @ub_oid THEN @ub_oid 
                    ELSE OrderID 
                  END;

    -- Clip TotalAmount outliers
    DECLARE @q1_ta FLOAT, @q3_ta FLOAT, @iqr_ta FLOAT, @lb_ta FLOAT, @ub_ta FLOAT;
    SELECT TOP 1 @q1_ta = PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY TRY_CAST(TotalAmount AS FLOAT)) OVER(),
                 @q3_ta = PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY TRY_CAST(TotalAmount AS FLOAT)) OVER()
    FROM dbo.Sales_Raw;
    
    SET @iqr_ta = @q3_ta - @q1_ta; 
    SET @lb_ta = @q1_ta - 1.5*@iqr_ta; 
    SET @ub_ta = @q3_ta + 1.5*@iqr_ta;
    
    UPDATE dbo.Sales_Raw 
    SET TotalAmount = CASE 
                        WHEN TRY_CAST(TotalAmount AS FLOAT) < @lb_ta THEN @lb_ta 
                        WHEN TRY_CAST(TotalAmount AS FLOAT) > @ub_ta THEN @ub_ta 
                        ELSE TotalAmount 
                      END;

    -------------------------------------------------------------------
    -- 3. JOIN DATASETS
    -------------------------------------------------------------------
    IF OBJECT_ID('dbo.Joined_Orders_Sales', 'U') IS NOT NULL DROP TABLE dbo.Joined_Orders_Sales;
    
    SELECT o.*, s.TotalAmount
    INTO dbo.Joined_Orders_Sales
    FROM dbo.Orders_Raw o
    INNER JOIN dbo.Sales_Raw s ON o.OrderID = s.OrderID;

    COMMIT;
    PRINT 'ETL Executed Successfully! Dirty rows deleted and outliers clipped.';
END TRY
BEGIN CATCH
    IF @@TRANCOUNT > 0 ROLLBACK;
    DECLARE @ErrorMessage NVARCHAR(4000) = ERROR_MESSAGE();
    RAISERROR(@ErrorMessage, 16, 1);
END CATCH;
"""

print(f"Connecting to {server}...")
try:
    conn = pyodbc.connect(conn_str, autocommit=True)
    cursor = conn.cursor()
    print("Executing strict ETL script (Clipping + Deletions)...")
    cursor.execute(sql_script)
    print("Done! Check your database for the 100% clean data.")
except Exception as e:
    print("Failed to execute:", str(e))
