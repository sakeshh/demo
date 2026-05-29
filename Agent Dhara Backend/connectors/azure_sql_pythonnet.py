"""
Azure SQL connector using pythonnet (Microsoft.Data.SqlClient or System.Data.SqlClient).
"""

import os
import sys
import re
import clr_loader
import pythonnet

# Force .NET Framework runtime if possible (fixes ModuleNotFoundError: No module named 'System.Data')
try:
    rt = clr_loader.get_netfx()
    pythonnet.set_runtime(rt)
except Exception:
    pass

import clr
import pandas as pd
import csv
from typing import Any, Dict, List, Optional

clr.AddReference("System.Data")

# Force .NET SecurityProtocol to support modern TLS versions (TLS 1.1/1.2/1.3)
# Azure SQL blocks legacy TLS 1.0/SSL3 which older .NET runtimes default to.
try:
    clr.AddReference("System.Net")
    from System.Net import ServicePointManager
    # 768 = Tls11, 3072 = Tls12, 12288 = Tls13
    ServicePointManager.SecurityProtocol |= 768 | 3072 | 12288
except Exception:
    pass

SQLCLIENT_PROVIDER = None


def _try_load_microsoft_sqlclient():
    asm_dir = os.environ.get("SQLCLIENT_ASSEMBLY_DIR")
    if asm_dir and asm_dir not in sys.path:
        sys.path.append(asm_dir)
    try:
        clr.AddReference("Microsoft.Data.SqlClient")
        from Microsoft.Data.SqlClient import SqlConnection, SqlCommand  # type: ignore
        return SqlConnection, SqlCommand
    except Exception:
        return None


_ms = _try_load_microsoft_sqlclient()
if _ms:
    SqlConnection, SqlCommand = _ms
    SQLCLIENT_PROVIDER = "Microsoft.Data.SqlClient"
else:
    from System.Data.SqlClient import SqlConnection, SqlCommand  # type: ignore
    SQLCLIENT_PROVIDER = "System.Data.SqlClient"

print(f"[INFO] Using SQL Client provider: {SQLCLIENT_PROVIDER}")


def _first_present(d: Dict[str, str], keys: List[str], default=None):
    for k in keys:
        if k in d and d[k] is not None:
            return d[k]
    return default


class AzureSQLPythonNetConnector:
    def __init__(self, conn_cfg: Dict[str, str]):
        self.cfg = conn_cfg

    def _connect(self):
        server = _first_present(self.cfg, ["server", "Server", "host", "hostname"]) or os.environ.get("AZURE_SQL_SERVER")
        database = _first_present(self.cfg, ["database", "Database", "db"]) or os.environ.get("AZURE_SQL_DATABASE")
        user = (
            _first_present(self.cfg, ["user", "username", "User Id", "UserID", "uid"])
            or os.environ.get("AZURE_SQL_USERNAME")
            or os.environ.get("AZURE_SQL_USER")
        )
        password = _first_present(self.cfg, ["password", "Password", "pwd"]) or os.environ.get("AZURE_SQL_PASSWORD")

        if not server or not database:
            raise ValueError("Missing required connection keys: 'server' and 'database'.")

        parts = [
            f"Server={server};",
            f"Database={database};",
        ]
        if user and password:
            parts.append(f"User Id={user};")
            parts.append(f"Password={password};")
        parts.extend([
            "Encrypt=True;",
            "TrustServerCertificate=True;",
            "MultipleActiveResultSets=False;",
            "Connection Timeout=30;",
        ])
        conn_str = "".join(parts)
        return SqlConnection(conn_str)

    def discover_tables(self) -> List[str]:
        sql = """
        SELECT TABLE_SCHEMA, TABLE_NAME
        FROM INFORMATION_SCHEMA.TABLES
        WHERE TABLE_TYPE='BASE TABLE'
        ORDER BY TABLE_SCHEMA, TABLE_NAME
        """
        conn = self._connect()
        try:
            conn.Open()
            cmd = SqlCommand(sql, conn)
            reader = cmd.ExecuteReader()
            tables: List[str] = []
            while reader.Read():
                schema = reader.GetString(0)
                table = reader.GetString(1)
                tables.append(f"{schema}.{table}")
            return tables
        finally:
            conn.Close()

    def _quote_two_part_name(self, two_part: str) -> str:
        parts = two_part.split(".", 1)
        if len(parts) == 2:
            return f"[{parts[0]}].[{parts[1]}]"
        return f"[{two_part}]"

    def _read_reader_to_df(self, reader) -> pd.DataFrame:
        columns = [reader.GetName(i) for i in range(reader.FieldCount)]
        rows = []
        while reader.Read():
            row = [
                (None if reader.IsDBNull(i) else reader.GetValue(i))
                for i in range(reader.FieldCount)
            ]
            rows.append(row)
        return pd.DataFrame(rows, columns=columns)

    def export_table_to_csv(
        self,
        table: str,
        output_path: str,
        *,
        include_header: bool = True,
    ) -> str:
        """
        Export a full table to CSV without storing all rows in memory.

        Notes:
        - Uses a forward-only reader and writes each row to disk.
        - Values are written as-is; non-primitive .NET values are stringified.
        """
        output_path = os.path.abspath(output_path)
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        conn = self._connect()
        try:
            conn.Open()
            table_quoted = self._quote_two_part_name(table)
            cmd = SqlCommand(f"SELECT * FROM {table_quoted}", conn)
            reader = cmd.ExecuteReader()
            cols = [reader.GetName(i) for i in range(reader.FieldCount)]
            with open(output_path, "w", encoding="utf-8", newline="") as f:
                w = csv.writer(f)
                if include_header:
                    w.writerow(cols)
                while reader.Read():
                    row: List[Optional[Any]] = [
                        (None if reader.IsDBNull(i) else reader.GetValue(i))
                        for i in range(reader.FieldCount)
                    ]
                    # Make sure values are CSV-writable
                    w.writerow([v if isinstance(v, (str, int, float, bool)) or v is None else str(v) for v in row])
            return output_path
        finally:
            conn.Close()

    def load_table(self, table: str, max_rows: Optional[int] = None) -> pd.DataFrame:
        conn = self._connect()
        try:
            conn.Open()
            table_quoted = self._quote_two_part_name(table)
            limit = ""
            if max_rows and int(max_rows) > 0:
                limit = f"TOP {int(max_rows)} "
            cmd = SqlCommand(f"SELECT {limit}* FROM {table_quoted}", conn)
            reader = cmd.ExecuteReader()
            return self._read_reader_to_df(reader)
        finally:
            conn.Close()

    def preview_table(self, table: str, rows: int = 5) -> pd.DataFrame:
        rows = int(rows) if rows and rows > 0 else 5
        rows = max(1, min(rows, 10000))
        conn = self._connect()
        try:
            conn.Open()
            table_quoted = self._quote_two_part_name(table)
            cmd = SqlCommand(f"SELECT TOP {rows} * FROM {table_quoted}", conn)
            reader = cmd.ExecuteReader()
            return self._read_reader_to_df(reader)
        finally:
            conn.Close()

    def get_table_schema(self, table: str) -> List[Dict[str, Any]]:
        """
        Return column schema using INFORMATION_SCHEMA.COLUMNS.
        """
        if "." in table:
            schema, name = table.split(".", 1)
        else:
            schema, name = "dbo", table
        sql = """
        SELECT COLUMN_NAME, DATA_TYPE, IS_NULLABLE, CHARACTER_MAXIMUM_LENGTH, NUMERIC_PRECISION, NUMERIC_SCALE
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = @schema AND TABLE_NAME = @table
        ORDER BY ORDINAL_POSITION
        """
        conn = self._connect()
        try:
            conn.Open()
            cmd = SqlCommand(sql, conn)
            cmd.Parameters.AddWithValue("@schema", schema)
            cmd.Parameters.AddWithValue("@table", name)
            reader = cmd.ExecuteReader()
            cols: List[Dict[str, Any]] = []
            while reader.Read():
                cols.append(
                    {
                        "name": reader.GetString(0),
                        "type": reader.GetString(1),
                        "nullable": reader.GetString(2),
                        "max_length": (None if reader.IsDBNull(3) else int(reader.GetValue(3))),
                        "precision": (None if reader.IsDBNull(4) else int(reader.GetValue(4))),
                        "scale": (None if reader.IsDBNull(5) else int(reader.GetValue(5))),
                    }
                )
            return cols
        finally:
            conn.Close()

    def execute_select(self, sql: str, max_rows: Optional[int] = None) -> pd.DataFrame:
        """
        Execute a SELECT query (read-only). Reject non-SELECT statements.
        """
        q = (sql or "").strip()
        # Basic hardening: single statement, SELECT-only (CTE allowed), no dangerous keywords.
        # Allow a *trailing* semicolon, but reject multi-statement queries.
        q = q.rstrip().rstrip(";").rstrip()
        if ";" in q:
            raise ValueError("Only a single SELECT statement is allowed.")
        q_norm = q.lower()
        # SQL Server batch separator can also be used for multi-statement scripts.
        if re.search(r"(?im)^[ \t]*go[ \t]*$", q):
            raise ValueError("Only a single SELECT statement is allowed.")
        # Allow common-table-expressions: WITH ... SELECT ...
        if not (q_norm.startswith("select") or q_norm.startswith("with")):
            raise ValueError("Only SELECT queries are allowed.")
        banned = ("insert", "update", "delete", "merge", "drop", "alter", "create", "exec", "execute", "truncate")
        if any(re.search(rf"\\b{kw}\\b", q_norm) for kw in banned):
            raise ValueError("Query contains forbidden keywords.")
        if max_rows is not None:
            max_rows = int(max_rows) if max_rows and max_rows > 0 else 0
            if max_rows > 0 and " top " not in q_norm[:120]:
                q = f"SELECT TOP {max_rows} * FROM ({q}) AS q"
        conn = self._connect()
        try:
            conn.Open()
            cmd = SqlCommand(q, conn)
            reader = cmd.ExecuteReader()
            return self._read_reader_to_df(reader)
        finally:
            conn.Close()

    def compute_column_stats(self, table: str) -> Dict[str, Any]:
        """
        S4-02: SQL Server Pushdown — compute per-column aggregate stats directly
        on the server to avoid pulling all rows into memory.

        Returns:
        {
            "row_count": int,
            "columns": {
                "<col>": {
                    "null_count": int,
                    "null_percentage": float,
                    "distinct_count": int,
                    "min_value": str | None,
                    "max_value": str | None,
                },
                ...
            }
        }
        """
        table_quoted = self._quote_two_part_name(table)

        # Step 1: Get column names from schema
        if "." in table:
            schema, name = table.split(".", 1)
        else:
            schema, name = "dbo", table

        conn = self._connect()
        try:
            conn.Open()

            # Get column list
            schema_sql = """
            SELECT COLUMN_NAME, DATA_TYPE
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = @schema AND TABLE_NAME = @table
            ORDER BY ORDINAL_POSITION
            """
            cmd = SqlCommand(schema_sql, conn)
            cmd.Parameters.AddWithValue("@schema", schema)
            cmd.Parameters.AddWithValue("@table", name)
            reader = cmd.ExecuteReader()
            col_info: List[Dict[str, str]] = []
            while reader.Read():
                col_info.append({
                    "name": reader.GetString(0),
                    "data_type": reader.GetString(1),
                })
            reader.Close()

            if not col_info:
                return {"row_count": 0, "columns": {}}

            # Step 2: Build a single aggregate query for all columns
            # Use CAST to NVARCHAR for min/max to handle all types uniformly
            agg_parts = ["COUNT(*) AS [__row_count__]"]
            for ci in col_info:
                cname = ci["name"]
                quoted = f"[{cname}]"
                agg_parts.append(f"SUM(CASE WHEN {quoted} IS NULL THEN 1 ELSE 0 END) AS [{cname}__null_count]")
                agg_parts.append(f"COUNT(DISTINCT {quoted}) AS [{cname}__distinct_count]")
                # min/max: cast to NVARCHAR for uniform output
                agg_parts.append(f"CAST(MIN({quoted}) AS NVARCHAR(MAX)) AS [{cname}__min_value]")
                agg_parts.append(f"CAST(MAX({quoted}) AS NVARCHAR(MAX)) AS [{cname}__max_value]")

            agg_sql = f"SELECT {', '.join(agg_parts)} FROM {table_quoted}"
            cmd2 = SqlCommand(agg_sql, conn)
            reader2 = cmd2.ExecuteReader()

            result: Dict[str, Any] = {"row_count": 0, "columns": {}}
            if reader2.Read():
                row_count = int(reader2.GetValue(0)) if not reader2.IsDBNull(0) else 0
                result["row_count"] = row_count

                for ci in col_info:
                    cname = ci["name"]
                    null_count_idx = reader2.GetOrdinal(f"{cname}__null_count")
                    distinct_idx = reader2.GetOrdinal(f"{cname}__distinct_count")
                    min_idx = reader2.GetOrdinal(f"{cname}__min_value")
                    max_idx = reader2.GetOrdinal(f"{cname}__max_value")

                    null_count = int(reader2.GetValue(null_count_idx)) if not reader2.IsDBNull(null_count_idx) else 0
                    distinct_count = int(reader2.GetValue(distinct_idx)) if not reader2.IsDBNull(distinct_idx) else 0
                    min_val = str(reader2.GetValue(min_idx)) if not reader2.IsDBNull(min_idx) else None
                    max_val = str(reader2.GetValue(max_idx)) if not reader2.IsDBNull(max_idx) else None

                    null_pct = (null_count / row_count) if row_count > 0 else 0.0

                    result["columns"][cname] = {
                        "null_count": null_count,
                        "null_percentage": round(null_pct, 6),
                        "distinct_count": distinct_count,
                        "min_value": min_val,
                        "max_value": max_val,
                        "sql_data_type": ci["data_type"],
                    }

            reader2.Close()
            return result
        finally:
            conn.Close()