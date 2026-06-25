-- Plan ID: plan_1782296210
-- Fixed: replaced MySQL-style "CREATE TABLE IF NOT EXISTS" with T-SQL equivalents,
--        removed LTRIM/RTRIM on DATETIME columns,
--        added GO separators between CREATE PROCEDURE statements,
--        deduplicated (only one copy of schema + procedures).

-- =============================================
-- SCHEMA: Infrastructure tables
-- =============================================

IF NOT EXISTS (SELECT 1 FROM sys.tables WHERE name = 'etl_log' AND schema_id = SCHEMA_ID('dbo'))
CREATE TABLE dbo.etl_log (
    id            INT IDENTITY(1,1) PRIMARY KEY,
    process_name  VARCHAR(100) NOT NULL,
    start_time    DATETIME     NOT NULL,
    end_time      DATETIME     NULL,
    status        VARCHAR(20)  NOT NULL,
    error_message VARCHAR(MAX) NULL
);
GO

IF NOT EXISTS (SELECT 1 FROM sys.tables WHERE name = 'etl_rejects' AND schema_id = SCHEMA_ID('dbo'))
CREATE TABLE dbo.etl_rejects (
    id                INT IDENTITY(1,1) PRIMARY KEY,
    table_name        VARCHAR(100)   NOT NULL,
    rejected_row_data NVARCHAR(MAX)  NOT NULL,
    reject_reason     VARCHAR(255)   NOT NULL,
    etl_batch_id      INT            NOT NULL,
    rejected_at       DATETIME       DEFAULT GETDATE()
);
GO

IF NOT EXISTS (SELECT 1 FROM sys.tables WHERE name = 'etl_watermark' AND schema_id = SCHEMA_ID('dbo'))
CREATE TABLE dbo.etl_watermark (
    process_name  VARCHAR(100) PRIMARY KEY,
    last_run_time DATETIME     NOT NULL
);
GO

-- =============================================
-- SCHEMA: Citizens_Clean target table
-- =============================================

IF NOT EXISTS (SELECT 1 FROM sys.tables WHERE name = 'Citizens_Clean' AND schema_id = SCHEMA_ID('dbo'))
CREATE TABLE dbo.Citizens_Clean (
    CitizenID          INT            NOT NULL,
    FullName           NVARCHAR(255),
    Email              NVARCHAR(255),
    Mobile             NVARCHAR(50),
    RegistrationDate   DATETIME,
    etl_created_at     DATETIME       DEFAULT GETDATE(),
    etl_updated_at     DATETIME       DEFAULT GETDATE(),
    etl_batch_id       INT,
    PRIMARY KEY (CitizenID)
);
GO

IF NOT EXISTS (
    SELECT 1 FROM sys.indexes
    WHERE name = 'IDX_Citizens_Clean'
      AND object_id = OBJECT_ID('dbo.Citizens_Clean')
)
CREATE NONCLUSTERED INDEX IDX_Citizens_Clean ON dbo.Citizens_Clean (CitizenID);
GO

-- =============================================
-- PROCEDURE: dbo.etl_clean_Citizens
-- =============================================

IF OBJECT_ID('dbo.etl_clean_Citizens', 'P') IS NOT NULL
    DROP PROCEDURE dbo.etl_clean_Citizens;
GO

CREATE PROCEDURE dbo.etl_clean_Citizens
    @load_type VARCHAR(20) = 'FULL',
    @last_run  DATETIME    = NULL
AS
BEGIN
    SET NOCOUNT ON;

    DECLARE @run_id INT;
    INSERT INTO dbo.etl_log (process_name, start_time, status)
    VALUES ('dbo.etl_clean_Citizens', GETDATE(), 'RUNNING');
    SET @run_id = SCOPE_IDENTITY();

    BEGIN TRY
        BEGIN TRANSACTION;

        -- Stage source data
        SELECT * INTO #Citizens_Staging FROM dbo.Citizens WHERE 1 = 0;

        INSERT INTO #Citizens_Staging
        SELECT * FROM dbo.Citizens;

        -- Trim whitespace for string columns only (NOT on RegistrationDate which is DATETIME)
        UPDATE #Citizens_Staging
        SET
            Email    = LTRIM(RTRIM(Email)),
            FullName = LTRIM(RTRIM(FullName)),
            Mobile   = LTRIM(RTRIM(Mobile));

        -- Normalize FullName to lowercase
        UPDATE #Citizens_Staging
        SET FullName = LOWER(FullName);

        -- Parse / validate RegistrationDate (try multiple formats)
        UPDATE #Citizens_Staging
        SET RegistrationDate = COALESCE(
            TRY_CONVERT(DATETIME, CONVERT(VARCHAR, RegistrationDate, 120)),
            TRY_CONVERT(DATETIME, CONVERT(VARCHAR, RegistrationDate, 103)),
            TRY_CONVERT(DATETIME, CONVERT(VARCHAR, RegistrationDate, 101)),
            TRY_CONVERT(DATETIME, CONVERT(VARCHAR, RegistrationDate, 111))
        );

        -- Quarantine invalid e-mail addresses
        INSERT INTO dbo.etl_rejects (table_name, rejected_row_data, reject_reason, etl_batch_id)
        SELECT
            'dbo.Citizens',
            (SELECT * FROM #Citizens_Staging r2 WHERE r2.Email = r.Email FOR JSON PATH, WITHOUT_ARRAY_WRAPPER),
            'Invalid email format',
            @run_id
        FROM #Citizens_Staging r
        WHERE r.Email NOT LIKE '%_@_%._%';

        DELETE FROM #Citizens_Staging
        WHERE Email NOT LIKE '%_@_%._%';

        -- Clean and validate Mobile
        UPDATE #Citizens_Staging
        SET Mobile = REPLACE(REPLACE(REPLACE(REPLACE(Mobile, '-', ''), ' ', ''), '(', ''), ')', '');

        INSERT INTO dbo.etl_rejects (table_name, rejected_row_data, reject_reason, etl_batch_id)
        SELECT
            'dbo.Citizens',
            (SELECT * FROM #Citizens_Staging r2 WHERE r2.Mobile = r.Mobile FOR JSON PATH, WITHOUT_ARRAY_WRAPPER),
            'Invalid phone format',
            @run_id
        FROM #Citizens_Staging r
        WHERE LEN(Mobile) < 7 OR Mobile LIKE '%[^0-9]%';

        DELETE FROM #Citizens_Staging
        WHERE LEN(Mobile) < 7 OR Mobile LIKE '%[^0-9]%';

        -- Load cleaned data
        TRUNCATE TABLE dbo.Citizens_Clean;

        INSERT INTO dbo.Citizens_Clean (CitizenID, FullName, Email, Mobile, RegistrationDate, etl_batch_id)
        SELECT CitizenID, FullName, Email, Mobile, RegistrationDate, @run_id
        FROM #Citizens_Staging;

        COMMIT TRANSACTION;

        UPDATE dbo.etl_log SET end_time = GETDATE(), status = 'SUCCESS'
        WHERE id = @run_id;
    END TRY
    BEGIN CATCH
        IF @@TRANCOUNT > 0 ROLLBACK TRANSACTION;
        UPDATE dbo.etl_log
        SET end_time = GETDATE(), status = 'FAILED', error_message = ERROR_MESSAGE()
        WHERE id = @run_id;
    END CATCH;
END;
GO

-- =============================================
-- PROCEDURE: dbo.etl_main
-- =============================================

IF OBJECT_ID('dbo.etl_main', 'P') IS NOT NULL
    DROP PROCEDURE dbo.etl_main;
GO

CREATE PROCEDURE dbo.etl_main
AS
BEGIN
    SET NOCOUNT ON;
    EXEC dbo.etl_clean_Citizens;
END;
GO