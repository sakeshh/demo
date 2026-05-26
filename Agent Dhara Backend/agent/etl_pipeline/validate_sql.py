from __future__ import annotations

import re
from typing import List, Tuple

_DANGEROUS = [
    (r"\bdrop\s+table\s+(?!.*\b\w*(?:_clean|_stg|temp_|_temp)\b|.*#)", "contains DROP TABLE on non-staging/clean table — remove for safety"),
    (r"\btruncate\s+table\s+(?!.*\b\w*(?:_clean|_stg|temp_|_temp)\b|.*#)", "contains TRUNCATE TABLE on non-staging/clean table — remove for safety"),
    (r"\bdelete\s+from\s+(?!.*\b\w*(?:_clean|_stg|_dedup|temp_|etl_log|cte|_temp)\b|.*#)", "contains DELETE FROM on non-staging/clean table — remove for safety"),
]


def _bracket_balance(source: str) -> List[str]:
    issues: List[str] = []
    depth = 0
    for ch in source:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth < 0:
                issues.append("unbalanced parentheses")
                break
    if depth != 0:
        issues.append("unclosed parentheses")
    return issues


def validate_sql_basic_dict(source: str) -> dict:
    """Parse SQL and return structured validation result."""
    if not source or not source.strip():
        return {"valid": False, "error": "Empty SQL", "issues": ["empty sql"]}

    issues: List[str] = []
    low = source.lower()
    for pattern, msg in _DANGEROUS:
        if re.search(pattern, low):
            for line in low.splitlines():
                stripped = line.strip()
                if re.search(pattern, stripped) and not stripped.startswith("--"):
                    issues.append(msg)
                    break

    try:
        import sqlparse  # type: ignore

        parsed = sqlparse.parse(source)
        if not parsed or not parsed[0].tokens:
            return {"valid": False, "error": "Empty or unparseable SQL", "issues": ["Empty or unparseable SQL"]}
    except ImportError:
        pass  # structural checks only when sqlparse unavailable
    except Exception as e:
        return {"valid": False, "error": f"SQL validation error: {str(e)}", "issues": [str(e)]}

    issues.extend(_bracket_balance(source))
    issues.extend(_tsql_transaction_blocks(source))

    if issues:
        return {"valid": False, "issues": issues}
    return {"valid": True, "issues": []}


def _tsql_transaction_blocks(source: str) -> List[str]:
    """Warn when BEGIN TRY appears without END CATCH (cheap structural check)."""
    low = source.lower()
    issues: List[str] = []
    if "begin try" in low and "end catch" not in low:
        issues.append("BEGIN TRY without matching END CATCH")
        
    has_begin_tran = "begin tran" in low or "begin transaction" in low
    has_commit = "commit" in low or "commit transaction" in low
    has_rollback = "rollback" in low or "rollback transaction" in low
    
    if has_begin_tran and not has_commit:
        issues.append("BEGIN TRANSACTION without COMMIT TRANSACTION")
    if (has_commit or has_rollback) and not has_begin_tran:
        issues.append("COMMIT/ROLLBACK TRANSACTION without BEGIN TRANSACTION")
    return issues


def validate_sql_basic(source: str) -> Tuple[bool, List[str]]:
    result = validate_sql_basic_dict(source)
    if result.get("valid"):
        return True, []
    errs = list(result.get("issues") or [])
    if result.get("error") and not errs:
        errs.append(str(result["error"]))
    return False, errs
