"""
Azure SQL direct execution service for Agent Dhara.
Connects via pyodbc. Supports transaction wrapping, rollback on failure,
approval gates for destructive ops, and structured result metadata.
Never logs or returns connection credentials.
"""

from __future__ import annotations

import os
import re
import time
import uuid
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import pyodbc

logger = logging.getLogger("agent.azure_sql_executor")

# For managed identity
try:
    from azure.identity import DefaultAzureCredential
except ImportError:
    DefaultAzureCredential = None

APPROVAL_REQUIRED_OPS = ["DELETE", "UPDATE", "MERGE", "TRUNCATE", "DROP"]


def _extract_pyodbc_error(exc: Exception) -> str:
    """
    Extract the most informative error string from a pyodbc exception.
    pyodbc sometimes raises HY000 'The driver did not supply an error!' when
    the real SQL Server diagnostic is buried in exc.args or the cursor messages.
    Falls back to str(exc) for non-pyodbc exceptions.
    """
    if not isinstance(exc, pyodbc.Error):
        return str(exc)
    parts: List[str] = []
    for arg in exc.args:
        part = str(arg).strip()
        if part and part not in parts:
            parts.append(part)
    return " | ".join(parts) if parts else str(exc)


def get_connection(connection_string: str | None = None) -> pyodbc.Connection:
    """
    Build connection from env DHARA_AZURE_SQL_CONN_STR or passed string.
    If not provided, falls back to building connection from:
      - AZURE_SQL_SERVER
      - AZURE_SQL_DATABASE
      - AZURE_SQL_USERNAME / AZURE_SQL_USER
      - AZURE_SQL_PASSWORD
    Raises ConnectionError with safe message if missing/invalid.
    Never log the connection string.
    Set autocommit=False.
    Timeout from env DHARA_SQL_CONNECT_TIMEOUT_S (default 30s).
    """
    conn_str = connection_string or os.getenv("DHARA_AZURE_SQL_CONN_STR")
    if not conn_str:
        server = os.getenv("AZURE_SQL_SERVER")
        if server and not server.endswith(".database.windows.net") and "localhost" not in server and "127.0.0.1" not in server and ":" not in server:
            server = server + ".database.windows.net"
        database = os.getenv("AZURE_SQL_DATABASE")
        user = os.getenv("AZURE_SQL_USERNAME") or os.getenv("AZURE_SQL_USER")
        password = os.getenv("AZURE_SQL_PASSWORD")

        if server and database:
            driver = "ODBC Driver 17 for SQL Server"
            try:
                drivers = pyodbc.drivers()
                sql_drivers = [d for d in drivers if "sql server" in d.lower() or "odbc driver" in d.lower()]
                if sql_drivers:
                    for pref in ["ODBC Driver 18 for SQL Server", "ODBC Driver 17 for SQL Server", "SQL Server"]:
                        if any(pref.lower() in d.lower() for d in sql_drivers):
                            match = [d for d in sql_drivers if pref.lower() in d.lower()]
                            if match:
                                driver = match[0]
                                break
                    else:
                        driver = sql_drivers[0]
            except Exception:
                pass

            parts = [
                f"Driver={{{driver}}}",
                f"Server={server}",
                f"Database={database}",
            ]
            if user and password:
                parts.append(f"Uid={user}")
                parts.append(f"Pwd={password}")
            parts.extend([
                "Encrypt=yes",
                "TrustServerCertificate=yes",
            ])
            conn_str = ";".join(parts) + ";"
        else:
            raise ConnectionError(
                "Database connection string is missing. Please set DHARA_AZURE_SQL_CONN_STR or "
                "configure AZURE_SQL_SERVER and AZURE_SQL_DATABASE in environment."
            )

    timeout_str = os.getenv("DHARA_SQL_CONNECT_TIMEOUT_S", "30")
    try:
        timeout_s = int(timeout_str)
    except ValueError:
        timeout_s = 30

    # Ensure timeout is present in the connection string parameters
    if "timeout" not in conn_str.lower():
        if not conn_str.endswith(";"):
            conn_str += ";"
        conn_str += f"Connection Timeout={timeout_s};"

    attrs_before = {}
    # Use Managed Identity via DefaultAzureCredential if no credentials provided in connection string
    is_token_auth = False
    if (
        "uid" not in conn_str.lower()
        and "pwd" not in conn_str.lower()
        and "password" not in conn_str.lower()
    ):
        if DefaultAzureCredential is not None:
            is_token_auth = True

    if is_token_auth:
        try:
            import struct

            credential = DefaultAzureCredential()
            token = credential.get_token("https://database.windows.net/.default")
            token_bytes = token.token.encode("utf-16-le")
            token_struct = struct.pack("<I", len(token_bytes)) + token_bytes
            attrs_before[1256] = token_struct  # SQL_COPT_SS_ACCESS_TOKEN
        except Exception as e:
            raise ConnectionError(
                f"Failed to acquire Managed Identity token: {type(e).__name__}"
            ) from e

    try:
        conn = pyodbc.connect(conn_str, attrs_before=attrs_before, autocommit=False)
        return conn
    except Exception as e:
        raise ConnectionError(f"Database connection failed: {type(e).__name__}") from e


def test_connection(connection_string: str | None = None) -> dict:
    """
    Ping the DB. Return {"ok": bool, "server": str, "latency_ms": float, "error": str|None}.
    """
    t0 = time.perf_counter()
    try:
        conn = get_connection(connection_string)
        cursor = conn.cursor()
        cursor.execute("SELECT @@VERSION")
        row = cursor.fetchone()
        server_version = row[0] if row else "Unknown SQL Server"
        conn.close()
        latency_ms = (time.perf_counter() - t0) * 1000
        return {
            "ok": True,
            "server": server_version,
            "latency_ms": round(latency_ms, 2),
            "error": None,
        }
    except Exception as e:
        latency_ms = (time.perf_counter() - t0) * 1000
        return {
            "ok": False,
            "server": "",
            "latency_ms": round(latency_ms, 2),
            "error": str(e),
        }


def _split_sql_batches(sql: str) -> list[str]:
    """
    Split on GO statements (T-SQL batch separator). Strip empty batches.
    """
    if not sql:
        return []
    # Match GO on a line by itself (case-insensitive, optionally with comments/spaces)
    pattern = r"(?i)^\s*GO\s*(?:--.*)?$"
    batches = re.split(pattern, sql, flags=re.MULTILINE)
    result = []
    for b in batches:
        b_stripped = b.strip()
        if b_stripped:
            result.append(b_stripped)
    return result


def execute_sql_batch(
    cursor: pyodbc.Cursor,
    sql: str,
    *,
    timeout_s: int = 120,
) -> dict:
    """
    Execute a single batch. Return:
    {"rows_affected": int, "messages": list[str], "error": str|None, "duration_ms": float}
    cursor.execute then cursor.rowcount.
    Messages via cursor.messages if available.
    """
    t0 = time.perf_counter()
    try:
        if hasattr(cursor, "connection") and cursor.connection:
            cursor.connection.timeout = timeout_s
        cursor.execute(sql)
        rows = cursor.rowcount

        messages = []
        if hasattr(cursor, "messages"):
            raw_msgs = getattr(cursor, "messages") or []
            for msg in raw_msgs:
                if isinstance(msg, tuple) and len(msg) >= 2:
                    messages.append(str(msg[1]))
                else:
                    messages.append(str(msg))

        duration_ms = (time.perf_counter() - t0) * 1000
        return {
            "rows_affected": rows,
            "messages": messages,
            "error": None,
            "duration_ms": round(duration_ms, 2),
        }
    except Exception as e:
        duration_ms = (time.perf_counter() - t0) * 1000
        error_str = _extract_pyodbc_error(e)
        # Also drain any pending server messages from cursor for extra context
        if isinstance(e, pyodbc.Error):
            try:
                extra_parts = [error_str]
                pending = getattr(cursor, "messages", None) or []
                for msg in pending:
                    part = str(msg[1]).strip() if isinstance(msg, tuple) and len(msg) >= 2 else str(msg).strip()
                    if part and part not in extra_parts:
                        extra_parts.append(part)
                if len(extra_parts) > 1:
                    error_str = " | ".join(extra_parts)
            except Exception:
                pass
        logger.error("execute_sql_batch failed (%.0fms): %s", duration_ms, error_str)
        return {
            "rows_affected": -1,
            "messages": [],
            "error": error_str,
            "duration_ms": round(duration_ms, 2),
        }



def run_transactional_sql(
    sql: str,
    *,
    connection_string: str | None = None,
    dry_run: bool = False,
    approved: bool = False,
    require_approval_for: list[str] | None = None,
    timeout_s: int = 120,
    run_id: str | None = None,
) -> dict:
    """
    Full execution entry point.
    """
    rid = run_id or str(uuid.uuid4())

    if os.getenv("DHARA_SQL_EXECUTION_DISABLED") == "1":
        return {
            "ok": False,
            "run_id": rid,
            "dry_run": dry_run,
            "requires_approval": False,
            "transaction_committed": False,
            "rollback_reason": None,
            "batches_run": 0,
            "total_rows_affected": 0,
            "total_duration_ms": 0.0,
            "batch_results": [],
            "error": "execution_disabled",
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        }

    ops = require_approval_for if require_approval_for is not None else APPROVAL_REQUIRED_OPS
    app_check = check_requires_approval(sql, ops)

    if app_check["requires_approval"] and not dry_run and not approved:
        return {
            "ok": False,
            "run_id": rid,
            "dry_run": False,
            "requires_approval": True,
            "ops_found": app_check["ops_found"],
            "transaction_committed": False,
            "rollback_reason": None,
            "batches_run": 0,
            "total_rows_affected": 0,
            "total_duration_ms": 0.0,
            "batch_results": [],
            "error": "Approval required for destructive operations",
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        }

    if dry_run:
        batches = _split_sql_batches(sql)
        return {
            "ok": True,
            "run_id": rid,
            "dry_run": True,
            "requires_approval": app_check["requires_approval"],
            "ops_found": app_check["ops_found"],
            "transaction_committed": False,
            "rollback_reason": None,
            "batches_run": 0,
            "total_rows_affected": 0,
            "total_duration_ms": 0.0,
            "batches": batches,
            "batch_results": [],
            "error": None,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        }

    batches = _split_sql_batches(sql)
    batch_results = []
    total_rows_affected = 0
    total_duration = 0.0
    conn = None

    try:
        conn = get_connection(connection_string)
        
        # Regex to detect DDL statements that require autocommit
        ddl_pattern = re.compile(r"^\s*(CREATE|ALTER|DROP|TRUNCATE)\b", re.IGNORECASE | re.MULTILINE)
        
        _has_open_dml_txn = False  # track if DML transaction needs committing
        for batch_sql in batches:
            # Check if this specific batch is DDL
            is_ddl = bool(ddl_pattern.search(batch_sql))
            
            # Switch autocommit based on DDL/DML context
            if is_ddl and not conn.autocommit:
                # Commit any pending DML transaction before running DDL
                if _has_open_dml_txn:
                    conn.commit()
                    _has_open_dml_txn = False
                conn.autocommit = True
            elif not is_ddl and conn.autocommit:
                conn.autocommit = False

            cursor = conn.cursor()
            batch_res = execute_sql_batch(cursor, batch_sql, timeout_s=timeout_s)
            batch_results.append(batch_res)
            total_duration += batch_res["duration_ms"]

            if batch_res["error"] is not None:
                # Rollback on failure (only if not in autocommit mode)
                if not conn.autocommit:
                    conn.rollback()
                return {
                    "ok": False,
                    "run_id": rid,
                    "dry_run": False,
                    "requires_approval": app_check["requires_approval"],
                    "ops_found": app_check["ops_found"],
                    "transaction_committed": False,
                    "rollback_reason": batch_res["error"],
                    "batches_run": len(batch_results),
                    "total_rows_affected": total_rows_affected,
                    "total_duration_ms": round(total_duration, 2),
                    "batch_results": batch_results,
                    "error": f"Batch {len(batch_results)} failed: {batch_res['error']}",
                    "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                }

            affected = batch_res["rows_affected"]
            if affected > 0:
                total_rows_affected += affected
            if not is_ddl:
                _has_open_dml_txn = True

        # Commit on success (only if not in autocommit mode)
        if not conn.autocommit:
            try:
                conn.commit()
            except Exception as commit_err:
                # HY000 is often raised here when a stored proc's BEGIN CATCH
                # executed THROW/RAISERROR — the error is deferred to commit time.
                commit_error_str = _extract_pyodbc_error(commit_err)
                logger.error("conn.commit() raised an error — stored proc likely hit BEGIN CATCH: %s", commit_error_str)
                try:
                    conn.rollback()
                except Exception:
                    pass
                return {
                    "ok": False,
                    "run_id": rid,
                    "dry_run": False,
                    "requires_approval": app_check["requires_approval"],
                    "ops_found": app_check["ops_found"],
                    "transaction_committed": False,
                    "rollback_reason": commit_error_str,
                    "batches_run": len(batch_results),
                    "total_rows_affected": total_rows_affected,
                    "total_duration_ms": round(total_duration, 2),
                    "batch_results": batch_results,
                    "error": f"commit() failed: {commit_error_str}",
                    "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                }

        return {
            "ok": True,
            "run_id": rid,
            "dry_run": False,
            "requires_approval": app_check["requires_approval"],
            "ops_found": app_check["ops_found"],
            "transaction_committed": True,  # All batches succeeded
            "rollback_reason": None,
            "batches_run": len(batches),
            "total_rows_affected": total_rows_affected,
            "total_duration_ms": round(total_duration, 2),
            "batch_results": batch_results,
            "error": None,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        }

    except Exception as e:
        error_str = _extract_pyodbc_error(e)
        logger.error("run_transactional_sql outer exception: %s", error_str)
        if conn is not None and not conn.autocommit:
            try:
                conn.rollback()
            except Exception:
                pass
        return {
            "ok": False,
            "run_id": rid,
            "dry_run": False,
            "requires_approval": app_check["requires_approval"],
            "ops_found": app_check["ops_found"],
            "transaction_committed": False,
            "rollback_reason": error_str,
            "batches_run": len(batch_results),
            "total_rows_affected": total_rows_affected,
            "total_duration_ms": round(total_duration, 2),
            "batch_results": batch_results,
            "error": error_str,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        }
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def check_requires_approval(sql: str, ops: list[str] | None = None) -> dict:
    """
    Scan SQL for destructive ops (case-insensitive, skip commented lines).
    Return {"requires_approval": bool, "ops_found": list[str]}.
    """
    if ops is None:
        ops = APPROVAL_REQUIRED_OPS

    if not sql:
        return {"requires_approval": False, "ops_found": []}

    # Strip single-line comments (-- comment)
    cleaned = re.sub(r"--.*$", "", sql, flags=re.MULTILINE)
    # Strip multi-line comments (/* comment */)
    cleaned = re.sub(r"/\*.*?\*/", "", cleaned, flags=re.DOTALL)

    ops_found = []
    cleaned_lower = cleaned.lower()
    for op in ops:
        pattern = rf"\b{re.escape(op.lower())}\b"
        if re.search(pattern, cleaned_lower):
            ops_found.append(op)

    return {"requires_approval": len(ops_found) > 0, "ops_found": ops_found}
