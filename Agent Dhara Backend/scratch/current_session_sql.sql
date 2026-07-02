-- ============================================================
-- SQL QUALITY ASSESSMENT BADGE
-- Score: 100/100
-- Grade: A
-- No issues detected. Fully production ready!
-- ============================================================
-- ETL SQL — Agent Dhara — plan_id=plan_1782912586
-- dialect=tsql — review before executing against production.

-- ============================================================
-- Create configuration, watermark and logging tables if not exists
-- ============================================================
IF OBJECT_ID('dbo.etl_log', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.etl_log (
        id INT IDENTITY(1,1) PRIMARY KEY,
        process_name VARCHAR(100) NOT NULL,
        start_time DATETIME NOT NULL,
        end_time DATETIME NULL,
        status VARCHAR(20) NOT NULL,
        error_message VARCHAR(MAX) NULL
    );
END;
GO

IF OBJECT_ID('dbo.etl_default_values', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.etl_default_values (
        column_name VARCHAR(256) PRIMARY KEY,
        default_value VARCHAR(256) NOT NULL,
        data_type VARCHAR(50) NOT NULL
    );
END;
GO

IF OBJECT_ID('dbo.etl_invalid_values', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.etl_invalid_values (
        column_name VARCHAR(256),
        invalid_value VARCHAR(256),
        PRIMARY KEY (column_name, invalid_value)
    );
END;
GO

IF OBJECT_ID('dbo.etl_watermark', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.etl_watermark (
        process_name VARCHAR(256) PRIMARY KEY,
        last_run_time DATETIME NOT NULL
    );
END;
GO

-- Seed ETL default configuration values
IF NOT EXISTS (SELECT 1 FROM dbo.etl_default_values WHERE column_name = 'EmployeeData_Clean.Department')
    INSERT INTO dbo.etl_default_values (column_name, default_value, data_type) VALUES ('EmployeeData_Clean.Department', N'', 'NVARCHAR(MAX)');
IF NOT EXISTS (SELECT 1 FROM dbo.etl_default_values WHERE column_name = 'EmployeeData_Clean.EmployeeID')
    INSERT INTO dbo.etl_default_values (column_name, default_value, data_type) VALUES ('EmployeeData_Clean.EmployeeID', N'', 'NVARCHAR(255)');
IF NOT EXISTS (SELECT 1 FROM dbo.etl_default_values WHERE column_name = 'EmployeeData_Clean.EmployeeName')
    INSERT INTO dbo.etl_default_values (column_name, default_value, data_type) VALUES ('EmployeeData_Clean.EmployeeName', N'', 'NVARCHAR(255)');
IF NOT EXISTS (SELECT 1 FROM dbo.etl_default_values WHERE column_name = 'EmployeeData_Clean.JobTitle')
    INSERT INTO dbo.etl_default_values (column_name, default_value, data_type) VALUES ('EmployeeData_Clean.JobTitle', N'', 'NVARCHAR(MAX)');
IF NOT EXISTS (SELECT 1 FROM dbo.etl_default_values WHERE column_name = 'EmployeeData_Clean.Location')
    INSERT INTO dbo.etl_default_values (column_name, default_value, data_type) VALUES ('EmployeeData_Clean.Location', N'', 'NVARCHAR(MAX)');
IF NOT EXISTS (SELECT 1 FROM dbo.etl_default_values WHERE column_name = 'EmployeeData_Clean.Salary')
    INSERT INTO dbo.etl_default_values (column_name, default_value, data_type) VALUES ('EmployeeData_Clean.Salary', N'0', 'NVARCHAR(MAX)');
IF NOT EXISTS (SELECT 1 FROM dbo.etl_default_values WHERE column_name = 'EmployeeData_Clean.Status')
    INSERT INTO dbo.etl_default_values (column_name, default_value, data_type) VALUES ('EmployeeData_Clean.Status', N'', 'NVARCHAR(255)');
GO

-- ============================================================
-- Initialize Clean Tables if not exists
-- ============================================================
IF OBJECT_ID('dbo.EmployeeData_Clean', 'U') IS NULL
BEGIN
    CREATE TABLE [dbo].[EmployeeData_Clean] (
    [JobTitle] NVARCHAR(MAX) NULL,
    [Phone] NVARCHAR(50) NULL,
    [Department] NVARCHAR(MAX) NULL,
    [EmployeeID] NVARCHAR(255) NOT NULL,
    [EmployeeName] NVARCHAR(255) NULL,
    [HireDate] DATE NULL,
    [Email] NVARCHAR(255) NULL,
    [Status] NVARCHAR(255) NULL,
    [Location] NVARCHAR(MAX) NULL,
    [Salary] NVARCHAR(MAX) NULL,
    etl_created_at DATETIME DEFAULT GETDATE(),
    etl_updated_at DATETIME DEFAULT GETDATE(),
    etl_batch_id INT NULL,
    CONSTRAINT [PK_EmployeeData_Clean] PRIMARY KEY ([EmployeeID])
    );
    CREATE NONCLUSTERED INDEX idx_EmployeeData_Clean_HireDate ON [dbo].[EmployeeData_Clean]([HireDate]);
END;
GO

-- === dataset: dbo.EmployeeData === 
IF OBJECT_ID('dbo.etl_clean_EmployeeData', 'P') IS NOT NULL DROP PROCEDURE dbo.etl_clean_EmployeeData;
GO
CREATE PROCEDURE dbo.etl_clean_EmployeeData
    @load_type VARCHAR(20) = 'FULL',
    @last_run DATETIME = NULL
AS BEGIN
    SET NOCOUNT ON;
    -- Retrieve last run watermark if not provided
    IF @load_type = 'INCREMENTAL' AND @last_run IS NULL
    BEGIN
        SELECT @last_run = last_run_time FROM dbo.etl_watermark WHERE process_name = 'etl_clean_EmployeeData';
    END;

    INSERT INTO dbo.etl_log (process_name, start_time, status)
    VALUES ('etl_clean_EmployeeData', GETDATE(), 'RUNNING');
    DECLARE @run_id INT = SCOPE_IDENTITY();

    BEGIN TRY
        BEGIN TRAN;

        -- Initialize Clean Table Structure
        IF OBJECT_ID('dbo.EmployeeData_Clean', 'U') IS NULL
        BEGIN
            CREATE TABLE [dbo].[EmployeeData_Clean] (
                [JobTitle] NVARCHAR(MAX) NULL,
        [Phone] NVARCHAR(50) NULL,
        [Department] NVARCHAR(MAX) NULL,
        [EmployeeID] NVARCHAR(255) NOT NULL,
        [EmployeeName] NVARCHAR(255) NULL,
        [HireDate] DATE NULL,
        [Email] NVARCHAR(255) NULL,
        [Status] NVARCHAR(255) NULL,
        [Location] NVARCHAR(MAX) NULL,
        [Salary] NVARCHAR(MAX) NULL,
        etl_created_at DATETIME DEFAULT GETDATE(),
        etl_updated_at DATETIME DEFAULT GETDATE(),
        etl_batch_id INT NULL,
        CONSTRAINT [PK_EmployeeData_Clean] PRIMARY KEY ([EmployeeID])
            );
            CREATE NONCLUSTERED INDEX idx_EmployeeData_Clean_HireDate ON [dbo].[EmployeeData_Clean]([HireDate]);
        END

        -- Create Staging Table with raw column types to preserve raw strings
        IF OBJECT_ID('tempdb..#EmployeeData_Staging') IS NOT NULL DROP TABLE #EmployeeData_Staging;
        CREATE TABLE #EmployeeData_Staging ([JobTitle] NVARCHAR(MAX) NULL, [Phone] NVARCHAR(MAX) NULL, [Department] NVARCHAR(MAX) NULL, [EmployeeID] NVARCHAR(MAX) NULL, [EmployeeName] NVARCHAR(MAX) NULL, [HireDate] NVARCHAR(MAX) NULL, [Email] NVARCHAR(MAX) NULL, [Status] NVARCHAR(MAX) NULL, [Location] NVARCHAR(MAX) NULL, [Salary] NVARCHAR(MAX) NULL, etl_batch_id INT NULL);

        -- Copy data from Raw to Staging
        IF @load_type = 'FULL' OR @last_run IS NULL
        BEGIN
            INSERT INTO #EmployeeData_Staging ([JobTitle], [Phone], [Department], [EmployeeID], [EmployeeName], [HireDate], [Email], [Status], [Location], [Salary], etl_batch_id)
            SELECT [JobTitle], [Phone], [Department], [EmployeeID], [EmployeeName], [HireDate], [Email], [Status], [Location], [Salary], @run_id FROM [dbo].[EmployeeData];
        END
        ELSE
        BEGIN
            INSERT INTO #EmployeeData_Staging ([JobTitle], [Phone], [Department], [EmployeeID], [EmployeeName], [HireDate], [Email], [Status], [Location], [Salary], etl_batch_id)
            SELECT [JobTitle], [Phone], [Department], [EmployeeID], [EmployeeName], [HireDate], [Email], [Status], [Location], [Salary], @run_id FROM [dbo].[EmployeeData] WHERE COALESCE(TRY_CONVERT(datetime, [HireDate], 120), TRY_CONVERT(datetime, [HireDate], 103), TRY_CONVERT(datetime, [HireDate], 101), TRY_CONVERT(datetime, [HireDate], 111)) > @last_run;
        END

        -- Single-Pass expression updates on #EmployeeData_Staging
        UPDATE #EmployeeData_Staging
        SET [Department] = LOWER(LTRIM(RTRIM(CAST([Department] AS NVARCHAR(MAX))))),
            [Email] = LOWER(LTRIM(RTRIM(LTRIM(RTRIM(CAST([Email] AS NVARCHAR(MAX))))))),
            [EmployeeID] = LOWER(LTRIM(RTRIM(CAST([EmployeeID] AS NVARCHAR(MAX))))),
            [EmployeeName] = LOWER(LTRIM(RTRIM(CAST([EmployeeName] AS NVARCHAR(MAX))))),
            [JobTitle] = LOWER(LTRIM(RTRIM(CAST([JobTitle] AS NVARCHAR(MAX))))),
            [Location] = LOWER(LTRIM(RTRIM(CAST([Location] AS NVARCHAR(MAX))))),
            [Status] = LOWER(LTRIM(RTRIM(CAST([Status] AS NVARCHAR(MAX))))),
            [Phone] = REPLACE(REPLACE(REPLACE(REPLACE(CAST([Phone] AS NVARCHAR(200)), N'-', N''), N' ', N''), N'(', N''), N')', N'')
        WHERE 1=1;

        -- Grouped config and null updates on #EmployeeData_Staging
        UPDATE c
        SET c.[Department] = COALESCE(c.[Department], TRY_CAST(dv_Department.default_value AS NVARCHAR(MAX))),
            c.[EmployeeID] = COALESCE(c.[EmployeeID], TRY_CAST(dv_EmployeeID.default_value AS NVARCHAR(255))),
            c.[EmployeeName] = COALESCE(c.[EmployeeName], TRY_CAST(dv_EmployeeName.default_value AS NVARCHAR(255))),
            c.[JobTitle] = COALESCE(c.[JobTitle], TRY_CAST(dv_JobTitle.default_value AS NVARCHAR(MAX))),
            c.[Location] = COALESCE(c.[Location], TRY_CAST(dv_Location.default_value AS NVARCHAR(MAX))),
            c.[Salary] = COALESCE(c.[Salary], TRY_CAST(dv_Salary.default_value AS NVARCHAR(MAX))),
            c.[Status] = COALESCE(c.[Status], TRY_CAST(dv_Status.default_value AS NVARCHAR(255)))
        FROM #EmployeeData_Staging c
        LEFT JOIN dbo.etl_default_values dv_Department ON dv_Department.column_name = 'EmployeeData_Clean.Department'
        LEFT JOIN dbo.etl_default_values dv_EmployeeID ON dv_EmployeeID.column_name = 'EmployeeData_Clean.EmployeeID'
        LEFT JOIN dbo.etl_default_values dv_EmployeeName ON dv_EmployeeName.column_name = 'EmployeeData_Clean.EmployeeName'
        LEFT JOIN dbo.etl_default_values dv_JobTitle ON dv_JobTitle.column_name = 'EmployeeData_Clean.JobTitle'
        LEFT JOIN dbo.etl_default_values dv_Location ON dv_Location.column_name = 'EmployeeData_Clean.Location'
        LEFT JOIN dbo.etl_default_values dv_Salary ON dv_Salary.column_name = 'EmployeeData_Clean.Salary'
        LEFT JOIN dbo.etl_default_values dv_Status ON dv_Status.column_name = 'EmployeeData_Clean.Status'
        WHERE c.[Department] IS NULL OR c.[EmployeeID] IS NULL OR c.[EmployeeName] IS NULL OR c.[JobTitle] IS NULL OR c.[Location] IS NULL OR c.[Salary] IS NULL OR c.[Status] IS NULL;

        -- Normalize empty strings and placeholders to NULL before validation
        UPDATE #EmployeeData_Staging
        SET [JobTitle] = CASE WHEN LOWER(LTRIM(RTRIM([JobTitle]))) IN ('', 'n/a', 'na', 'null', 'unknown') THEN NULL ELSE [JobTitle] END,
    [Phone] = CASE WHEN LOWER(LTRIM(RTRIM([Phone]))) IN ('', 'n/a', 'na', 'null', 'unknown') THEN NULL ELSE [Phone] END,
    [Department] = CASE WHEN LOWER(LTRIM(RTRIM([Department]))) IN ('', 'n/a', 'na', 'null', 'unknown') THEN NULL ELSE [Department] END,
    [EmployeeID] = CASE WHEN LOWER(LTRIM(RTRIM([EmployeeID]))) IN ('', 'n/a', 'na', 'null', 'unknown') THEN NULL ELSE [EmployeeID] END,
    [EmployeeName] = CASE WHEN LOWER(LTRIM(RTRIM([EmployeeName]))) IN ('', 'n/a', 'na', 'null', 'unknown') THEN NULL ELSE [EmployeeName] END,
    [HireDate] = CASE WHEN LOWER(LTRIM(RTRIM([HireDate]))) IN ('', 'n/a', 'na', 'null', 'unknown') THEN NULL ELSE [HireDate] END,
    [Email] = CASE WHEN LOWER(LTRIM(RTRIM([Email]))) IN ('', 'n/a', 'na', 'null', 'unknown') THEN NULL ELSE [Email] END,
    [Status] = CASE WHEN LOWER(LTRIM(RTRIM([Status]))) IN ('', 'n/a', 'na', 'null', 'unknown') THEN NULL ELSE [Status] END,
    [Location] = CASE WHEN LOWER(LTRIM(RTRIM([Location]))) IN ('', 'n/a', 'na', 'null', 'unknown') THEN NULL ELSE [Location] END,
    [Salary] = CASE WHEN LOWER(LTRIM(RTRIM([Salary]))) IN ('', 'n/a', 'na', 'null', 'unknown') THEN NULL ELSE [Salary] END;

        -- Nullify invalid email format for optional column [Email]
        UPDATE #EmployeeData_Staging SET [Email] = NULL WHERE [Email] IS NOT NULL AND (NOT (CAST([Email] AS NVARCHAR(MAX)) LIKE '%_@_%._%') OR CAST([Email] AS NVARCHAR(MAX)) LIKE '%@%@%');

        -- Nullify invalid phone format for optional column [Phone]
        UPDATE #EmployeeData_Staging SET [Phone] = NULL WHERE [Phone] IS NOT NULL AND (LEN(REPLACE(REPLACE(REPLACE(REPLACE(CAST([Phone] AS NVARCHAR(200)), N'-', N''), N' ', N''), N'(', N''), N')', N'')) < 7 OR REPLACE(REPLACE(REPLACE(REPLACE(CAST([Phone] AS NVARCHAR(200)), N'-', N''), N' ', N''), N'(', N''), N')', N'') LIKE '%[^0-9]%');

        -- Post-validation date/type parsing on #EmployeeData_Staging
        UPDATE #EmployeeData_Staging
        SET [HireDate] = COALESCE(TRY_CONVERT(date, [HireDate], 120), TRY_CONVERT(date, [HireDate], 103), TRY_CONVERT(date, [HireDate], 101), TRY_CONVERT(date, [HireDate], 111))
        WHERE 1=1;

        -- Deduplicate staging table by partition key(s)
        ;WITH _staging_dedup AS (
            SELECT ROW_NUMBER() OVER (PARTITION BY LOWER(LTRIM(RTRIM(CAST([EmployeeID] AS NVARCHAR(400))))) ORDER BY [HireDate] DESC) AS _rn
            FROM #EmployeeData_Staging
        )
        DELETE FROM _staging_dedup WHERE _rn > 1;

        -- Copy fully transformed data from Staging to target Clean table (SCD Type 1)
        IF @load_type = 'FULL' OR @last_run IS NULL
        BEGIN
            TRUNCATE TABLE [dbo].[EmployeeData_Clean];
            INSERT INTO [dbo].[EmployeeData_Clean] ([Department], [Email], [EmployeeID], [EmployeeName], [HireDate], [JobTitle], [Location], [Phone], [Salary], [Status], etl_batch_id, etl_created_at, etl_updated_at)
            SELECT [Department], TRY_CAST([Email] AS NVARCHAR(255)), TRY_CAST([EmployeeID] AS NVARCHAR(255)), TRY_CAST([EmployeeName] AS NVARCHAR(255)), TRY_CAST([HireDate] AS DATE), [JobTitle], [Location], TRY_CAST([Phone] AS NVARCHAR(50)), [Salary], TRY_CAST([Status] AS NVARCHAR(255)), etl_batch_id, GETDATE(), GETDATE() FROM #EmployeeData_Staging;
        END
        ELSE
        BEGIN
            DELETE FROM [dbo].[EmployeeData_Clean] WHERE [EmployeeID] IN (SELECT [EmployeeID] FROM #EmployeeData_Staging);
            INSERT INTO [dbo].[EmployeeData_Clean] ([Department], [Email], [EmployeeID], [EmployeeName], [HireDate], [JobTitle], [Location], [Phone], [Salary], [Status], etl_batch_id, etl_created_at, etl_updated_at)
            SELECT [Department], TRY_CAST([Email] AS NVARCHAR(255)), TRY_CAST([EmployeeID] AS NVARCHAR(255)), TRY_CAST([EmployeeName] AS NVARCHAR(255)), TRY_CAST([HireDate] AS DATE), [JobTitle], [Location], TRY_CAST([Phone] AS NVARCHAR(50)), [Salary], TRY_CAST([Status] AS NVARCHAR(255)), etl_batch_id, GETDATE(), GETDATE() FROM #EmployeeData_Staging;
        END;

        DECLARE @staging_rows INT = (SELECT COUNT(*) FROM #EmployeeData_Staging);
        DECLARE @target_rows INT = (SELECT COUNT(*) FROM [dbo].[EmployeeData_Clean]);
        IF @staging_rows > 0 AND @target_rows = 0
        BEGIN
            RAISERROR('Post-load assertion failed: Target table is empty but staging had rows.', 16, 1);
        END;

        DECLARE @max_watermark DATETIME = COALESCE((SELECT MAX(TRY_CAST([HireDate] AS DATETIME)) FROM #EmployeeData_Staging), @last_run, GETDATE());

        IF OBJECT_ID('tempdb..#EmployeeData_Staging') IS NOT NULL DROP TABLE #EmployeeData_Staging;


        -- Update process watermark
        IF @load_type = 'INCREMENTAL' OR @last_run IS NULL
        BEGIN
            MERGE INTO dbo.etl_watermark WITH (HOLDLOCK) AS target
            USING (SELECT 'etl_clean_EmployeeData' AS process_name) AS source
            ON target.process_name = source.process_name
            WHEN MATCHED THEN
                UPDATE SET last_run_time = @max_watermark
            WHEN NOT MATCHED THEN
                INSERT (process_name, last_run_time) VALUES (source.process_name, @max_watermark);
        END
        COMMIT;

        -- Log success
        UPDATE dbo.etl_log
        SET end_time = GETDATE(), status = 'SUCCESS'
        WHERE id = @run_id;
    END TRY
    BEGIN CATCH
        IF @@TRANCOUNT > 0 ROLLBACK;
        DECLARE @err VARCHAR(MAX) = ERROR_MESSAGE();
        UPDATE dbo.etl_log
        SET end_time = GETDATE(), status = 'FAILED', error_message = @err
        WHERE id = @run_id;
        THROW;
    END CATCH;
END;
GO

-- ============================================================
-- Master Orchestrator Stored Procedure
-- ============================================================
IF OBJECT_ID('dbo.etl_main', 'P') IS NOT NULL DROP PROCEDURE dbo.etl_main;
GO
CREATE PROCEDURE dbo.etl_main
    @load_type VARCHAR(20) = 'FULL',
    @last_run DATETIME = NULL
AS BEGIN
    SET NOCOUNT ON;
    -- Retrieve last run watermark if not provided
    IF @load_type = 'INCREMENTAL' AND @last_run IS NULL
    BEGIN
        SELECT @last_run = last_run_time FROM dbo.etl_watermark WHERE process_name = 'etl_main';
    END;

    INSERT INTO dbo.etl_log (process_name, start_time, status)
    VALUES ('etl_main', GETDATE(), 'RUNNING');
    DECLARE @run_id INT = SCOPE_IDENTITY();

    BEGIN TRY
        EXEC dbo.etl_clean_EmployeeData @load_type = @load_type, @last_run = @last_run;
        -- Update master process watermark
        IF @load_type = 'INCREMENTAL' OR @last_run IS NULL
        BEGIN
            MERGE INTO dbo.etl_watermark WITH (HOLDLOCK) AS target
            USING (SELECT 'etl_main' AS process_name) AS source
            ON target.process_name = source.process_name
            WHEN MATCHED THEN
                UPDATE SET last_run_time = COALESCE((SELECT MAX(last_run_time) FROM dbo.etl_watermark WHERE process_name LIKE 'etl_clean_%' OR process_name LIKE 'etl_transform_%'), GETDATE())
            WHEN NOT MATCHED THEN
                INSERT (process_name, last_run_time) VALUES (source.process_name, COALESCE((SELECT MAX(last_run_time) FROM dbo.etl_watermark WHERE process_name LIKE 'etl_clean_%' OR process_name LIKE 'etl_transform_%'), GETDATE()));
        END

        UPDATE dbo.etl_log
        SET end_time = GETDATE(), status = 'SUCCESS'
        WHERE id = @run_id;
    END TRY
    BEGIN CATCH
        DECLARE @err VARCHAR(MAX) = ERROR_MESSAGE();
        UPDATE dbo.etl_log
        SET end_time = GETDATE(), status = 'FAILED', error_message = @err
        WHERE id = @run_id;
        THROW;
    END CATCH;
END;
GO

-- ============================================================
-- Auto-Execute: Run ETL pipeline to populate Clean tables
-- ============================================================
PRINT 'Starting ETL pipeline execution...';
EXEC dbo.etl_main @load_type = 'FULL';
PRINT 'ETL pipeline execution complete.';
GO

GO

-- ============================================================
-- SQL QUALITY ASSESSMENT BADGE
-- Score: 55/100
-- Grade: F
-- Issues Detected (3):
--   - Email column detected but missing format check constraint (e.g. Email LIKE '%_@_%._%')
--   - Phone column detected but missing symbol cleaning operations (nested REPLACE for spaces/dashes)
--   - Phone column detected but missing validation checks (length >= 7 or only numeric digits)
-- ============================================================
-- ETL SQL — Agent Dhara — plan_id=plan_1782912586
-- dialect=tsql — review before executing against production.

-- ============================================================
-- Create configuration, watermark and logging tables if not exists
-- ============================================================
IF OBJECT_ID('dbo.etl_log', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.etl_log (
        id INT IDENTITY(1,1) PRIMARY KEY,
        process_name VARCHAR(100) NOT NULL,
        start_time DATETIME NOT NULL,
        end_time DATETIME NULL,
        status VARCHAR(20) NOT NULL,
        error_message VARCHAR(MAX) NULL
    );
END;
GO


IF OBJECT_ID('dbo.etl_invalid_values', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.etl_invalid_values (
        column_name VARCHAR(256),
        invalid_value VARCHAR(256),
        PRIMARY KEY (column_name, invalid_value)
    );
END;
GO

IF OBJECT_ID('dbo.etl_watermark', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.etl_watermark (
        process_name VARCHAR(256) PRIMARY KEY,
        last_run_time DATETIME NOT NULL
    );
END;
GO



-- ============================================================
-- Initialize Clean Tables if not exists
-- ============================================================
IF OBJECT_ID('dbo.EmployeeData_Transformed', 'U') IS NULL
BEGIN
    CREATE TABLE [dbo].[EmployeeData_Transformed] (
    [JobTitle] NVARCHAR(MAX) NULL,
    [Phone] NVARCHAR(50) NULL,
    [Department] NVARCHAR(MAX) NULL,
    [EmployeeID] NVARCHAR(255) NOT NULL,
    [EmployeeName] NVARCHAR(255) NULL,
    [HireDate] DATE NULL,
    [Email] NVARCHAR(255) NULL,
    [Status] NVARCHAR(255) NULL,
    [Location] NVARCHAR(MAX) NULL,
    [Salary] NVARCHAR(MAX) NULL,
    etl_created_at DATETIME DEFAULT GETDATE(),
    etl_updated_at DATETIME DEFAULT GETDATE(),
    etl_batch_id INT NULL,
    CONSTRAINT [PK_EmployeeData_Transformed] PRIMARY KEY ([EmployeeID])
    );
    CREATE NONCLUSTERED INDEX idx_EmployeeData_Transformed_HireDate ON [dbo].[EmployeeData_Transformed]([HireDate]);
END;
GO

-- === dataset: dbo.EmployeeData === 
IF OBJECT_ID('dbo.etl_transform_EmployeeData', 'P') IS NOT NULL DROP PROCEDURE dbo.etl_transform_EmployeeData;
GO
CREATE PROCEDURE dbo.etl_transform_EmployeeData
    @load_type VARCHAR(20) = 'FULL',
    @last_run DATETIME = NULL
AS BEGIN
    SET NOCOUNT ON;
    -- Retrieve last run watermark if not provided
    IF @load_type = 'INCREMENTAL' AND @last_run IS NULL
    BEGIN
        SELECT @last_run = last_run_time FROM dbo.etl_watermark WHERE process_name = 'etl_transform_EmployeeData';
    END;

    INSERT INTO dbo.etl_log (process_name, start_time, status)
    VALUES ('etl_transform_EmployeeData', GETDATE(), 'RUNNING');
    DECLARE @run_id INT = SCOPE_IDENTITY();

    BEGIN TRY
        BEGIN TRAN;

        -- Initialize Clean Table Structure
        IF OBJECT_ID('dbo.EmployeeData_Transformed', 'U') IS NULL
        BEGIN
            CREATE TABLE [dbo].[EmployeeData_Transformed] (
                [JobTitle] NVARCHAR(MAX) NULL,
        [Phone] NVARCHAR(50) NULL,
        [Department] NVARCHAR(MAX) NULL,
        [EmployeeID] NVARCHAR(255) NOT NULL,
        [EmployeeName] NVARCHAR(255) NULL,
        [HireDate] DATE NULL,
        [Email] NVARCHAR(255) NULL,
        [Status] NVARCHAR(255) NULL,
        [Location] NVARCHAR(MAX) NULL,
        [Salary] NVARCHAR(MAX) NULL,
        etl_created_at DATETIME DEFAULT GETDATE(),
        etl_updated_at DATETIME DEFAULT GETDATE(),
        etl_batch_id INT NULL,
        CONSTRAINT [PK_EmployeeData_Transformed] PRIMARY KEY ([EmployeeID])
            );
            CREATE NONCLUSTERED INDEX idx_EmployeeData_Transformed_HireDate ON [dbo].[EmployeeData_Transformed]([HireDate]);
        END

        -- Create Staging Table with raw column types to preserve raw strings
        IF OBJECT_ID('tempdb..#EmployeeData_Transform_Staging') IS NOT NULL DROP TABLE #EmployeeData_Transform_Staging;
        CREATE TABLE #EmployeeData_Transform_Staging ([JobTitle] NVARCHAR(MAX) NULL, [Phone] NVARCHAR(MAX) NULL, [Department] NVARCHAR(MAX) NULL, [EmployeeID] NVARCHAR(MAX) NULL, [EmployeeName] NVARCHAR(MAX) NULL, [HireDate] NVARCHAR(MAX) NULL, [Email] NVARCHAR(MAX) NULL, [Status] NVARCHAR(MAX) NULL, [Location] NVARCHAR(MAX) NULL, [Salary] NVARCHAR(MAX) NULL, etl_batch_id INT NULL);

        -- Copy data from Raw to Staging
        IF @load_type = 'FULL' OR @last_run IS NULL
        BEGIN
            INSERT INTO #EmployeeData_Transform_Staging ([JobTitle], [Phone], [Department], [EmployeeID], [EmployeeName], [HireDate], [Email], [Status], [Location], [Salary], etl_batch_id)
            SELECT [JobTitle], [Phone], [Department], [EmployeeID], [EmployeeName], [HireDate], [Email], [Status], [Location], [Salary], @run_id FROM [dbo].[EmployeeData_Clean];
        END
        ELSE
        BEGIN
            INSERT INTO #EmployeeData_Transform_Staging ([JobTitle], [Phone], [Department], [EmployeeID], [EmployeeName], [HireDate], [Email], [Status], [Location], [Salary], etl_batch_id)
            SELECT [JobTitle], [Phone], [Department], [EmployeeID], [EmployeeName], [HireDate], [Email], [Status], [Location], [Salary], @run_id FROM [dbo].[EmployeeData_Clean] WHERE COALESCE(TRY_CONVERT(datetime, [HireDate], 120), TRY_CONVERT(datetime, [HireDate], 103), TRY_CONVERT(datetime, [HireDate], 101), TRY_CONVERT(datetime, [HireDate], 111)) > @last_run;
        END

        -- Normalize empty strings and placeholders to NULL before validation
        UPDATE #EmployeeData_Transform_Staging
        SET [JobTitle] = CASE WHEN LOWER(LTRIM(RTRIM([JobTitle]))) IN ('', 'n/a', 'na', 'null', 'unknown') THEN NULL ELSE [JobTitle] END,
    [Phone] = CASE WHEN LOWER(LTRIM(RTRIM([Phone]))) IN ('', 'n/a', 'na', 'null', 'unknown') THEN NULL ELSE [Phone] END,
    [Department] = CASE WHEN LOWER(LTRIM(RTRIM([Department]))) IN ('', 'n/a', 'na', 'null', 'unknown') THEN NULL ELSE [Department] END,
    [EmployeeID] = CASE WHEN LOWER(LTRIM(RTRIM([EmployeeID]))) IN ('', 'n/a', 'na', 'null', 'unknown') THEN NULL ELSE [EmployeeID] END,
    [EmployeeName] = CASE WHEN LOWER(LTRIM(RTRIM([EmployeeName]))) IN ('', 'n/a', 'na', 'null', 'unknown') THEN NULL ELSE [EmployeeName] END,
    [HireDate] = CASE WHEN LOWER(LTRIM(RTRIM([HireDate]))) IN ('', 'n/a', 'na', 'null', 'unknown') THEN NULL ELSE [HireDate] END,
    [Email] = CASE WHEN LOWER(LTRIM(RTRIM([Email]))) IN ('', 'n/a', 'na', 'null', 'unknown') THEN NULL ELSE [Email] END,
    [Status] = CASE WHEN LOWER(LTRIM(RTRIM([Status]))) IN ('', 'n/a', 'na', 'null', 'unknown') THEN NULL ELSE [Status] END,
    [Location] = CASE WHEN LOWER(LTRIM(RTRIM([Location]))) IN ('', 'n/a', 'na', 'null', 'unknown') THEN NULL ELSE [Location] END,
    [Salary] = CASE WHEN LOWER(LTRIM(RTRIM([Salary]))) IN ('', 'n/a', 'na', 'null', 'unknown') THEN NULL ELSE [Salary] END;

        -- Copy fully transformed data from Staging to target Clean table (SCD Type 1)
        IF @load_type = 'FULL' OR @last_run IS NULL
        BEGIN
            TRUNCATE TABLE [dbo].[EmployeeData_Transformed];
            INSERT INTO [dbo].[EmployeeData_Transformed] ([Department], [Email], [EmployeeID], [EmployeeName], [HireDate], [JobTitle], [Location], [Phone], [Salary], [Status], etl_batch_id, etl_created_at, etl_updated_at)
            SELECT [Department], TRY_CAST([Email] AS NVARCHAR(255)), TRY_CAST([EmployeeID] AS NVARCHAR(255)), TRY_CAST([EmployeeName] AS NVARCHAR(255)), TRY_CAST([HireDate] AS DATE), [JobTitle], [Location], TRY_CAST([Phone] AS NVARCHAR(50)), [Salary], TRY_CAST([Status] AS NVARCHAR(255)), etl_batch_id, GETDATE(), GETDATE() FROM #EmployeeData_Transform_Staging;
        END
        ELSE
        BEGIN
            DELETE FROM [dbo].[EmployeeData_Transformed] WHERE [EmployeeID] IN (SELECT [EmployeeID] FROM #EmployeeData_Transform_Staging);
            INSERT INTO [dbo].[EmployeeData_Transformed] ([Department], [Email], [EmployeeID], [EmployeeName], [HireDate], [JobTitle], [Location], [Phone], [Salary], [Status], etl_batch_id, etl_created_at, etl_updated_at)
            SELECT [Department], TRY_CAST([Email] AS NVARCHAR(255)), TRY_CAST([EmployeeID] AS NVARCHAR(255)), TRY_CAST([EmployeeName] AS NVARCHAR(255)), TRY_CAST([HireDate] AS DATE), [JobTitle], [Location], TRY_CAST([Phone] AS NVARCHAR(50)), [Salary], TRY_CAST([Status] AS NVARCHAR(255)), etl_batch_id, GETDATE(), GETDATE() FROM #EmployeeData_Transform_Staging;
        END;

        DECLARE @staging_rows INT = (SELECT COUNT(*) FROM #EmployeeData_Transform_Staging);
        DECLARE @target_rows INT = (SELECT COUNT(*) FROM [dbo].[EmployeeData_Transformed]);
        IF @staging_rows > 0 AND @target_rows = 0
        BEGIN
            RAISERROR('Post-load assertion failed: Target table is empty but staging had rows.', 16, 1);
        END;

        DECLARE @max_watermark DATETIME = COALESCE((SELECT MAX(TRY_CAST([HireDate] AS DATETIME)) FROM #EmployeeData_Transform_Staging), @last_run, GETDATE());

        IF OBJECT_ID('tempdb..#EmployeeData_Transform_Staging') IS NOT NULL DROP TABLE #EmployeeData_Transform_Staging;


        -- Update process watermark
        IF @load_type = 'INCREMENTAL' OR @last_run IS NULL
        BEGIN
            MERGE INTO dbo.etl_watermark WITH (HOLDLOCK) AS target
            USING (SELECT 'etl_transform_EmployeeData' AS process_name) AS source
            ON target.process_name = source.process_name
            WHEN MATCHED THEN
                UPDATE SET last_run_time = @max_watermark
            WHEN NOT MATCHED THEN
                INSERT (process_name, last_run_time) VALUES (source.process_name, @max_watermark);
        END
        COMMIT;

        -- Log success
        UPDATE dbo.etl_log
        SET end_time = GETDATE(), status = 'SUCCESS'
        WHERE id = @run_id;
    END TRY
    BEGIN CATCH
        IF @@TRANCOUNT > 0 ROLLBACK;
        DECLARE @err VARCHAR(MAX) = ERROR_MESSAGE();
        UPDATE dbo.etl_log
        SET end_time = GETDATE(), status = 'FAILED', error_message = @err
        WHERE id = @run_id;
        THROW;
    END CATCH;
END;
GO

-- ============================================================
-- Master Orchestrator Stored Procedure
-- ============================================================
IF OBJECT_ID('dbo.etl_main', 'P') IS NOT NULL DROP PROCEDURE dbo.etl_main;
GO
CREATE PROCEDURE dbo.etl_main
    @load_type VARCHAR(20) = 'FULL',
    @last_run DATETIME = NULL
AS BEGIN
    SET NOCOUNT ON;
    -- Retrieve last run watermark if not provided
    IF @load_type = 'INCREMENTAL' AND @last_run IS NULL
    BEGIN
        SELECT @last_run = last_run_time FROM dbo.etl_watermark WHERE process_name = 'etl_main';
    END;

    INSERT INTO dbo.etl_log (process_name, start_time, status)
    VALUES ('etl_main', GETDATE(), 'RUNNING');
    DECLARE @run_id INT = SCOPE_IDENTITY();

    BEGIN TRY
        EXEC dbo.etl_transform_EmployeeData @load_type = @load_type, @last_run = @last_run;
        -- Update master process watermark
        IF @load_type = 'INCREMENTAL' OR @last_run IS NULL
        BEGIN
            MERGE INTO dbo.etl_watermark WITH (HOLDLOCK) AS target
            USING (SELECT 'etl_main' AS process_name) AS source
            ON target.process_name = source.process_name
            WHEN MATCHED THEN
                UPDATE SET last_run_time = COALESCE((SELECT MAX(last_run_time) FROM dbo.etl_watermark WHERE process_name LIKE 'etl_clean_%' OR process_name LIKE 'etl_transform_%'), GETDATE())
            WHEN NOT MATCHED THEN
                INSERT (process_name, last_run_time) VALUES (source.process_name, COALESCE((SELECT MAX(last_run_time) FROM dbo.etl_watermark WHERE process_name LIKE 'etl_clean_%' OR process_name LIKE 'etl_transform_%'), GETDATE()));
        END

        UPDATE dbo.etl_log
        SET end_time = GETDATE(), status = 'SUCCESS'
        WHERE id = @run_id;
    END TRY
    BEGIN CATCH
        DECLARE @err VARCHAR(MAX) = ERROR_MESSAGE();
        UPDATE dbo.etl_log
        SET end_time = GETDATE(), status = 'FAILED', error_message = @err
        WHERE id = @run_id;
        THROW;
    END CATCH;
END;
GO

-- ============================================================
-- Auto-Execute: Run ETL pipeline to populate Clean tables
-- ============================================================
PRINT 'Starting ETL pipeline execution...';
EXEC dbo.etl_main @load_type = 'FULL';
PRINT 'ETL pipeline execution complete.';
GO


-- ============================================================
-- Phase 2: Joined Views over Clean Tables
-- ============================================================
-- ── Staging / load order (connector manifest) ──
-- dbo.EmployeeData_Clean: -- Source table/view: dbo.EmployeeData_Clean
-- dbo.EmployeeData_Clean: SELECT * FROM dbo.EmployeeData_Clean;
