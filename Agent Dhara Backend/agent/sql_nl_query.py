from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Tuple

from agent.openai_usage import usage_dict_from_response


def _azure_openai_cfg() -> Optional[Dict[str, str]]:
    endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT")
    key = os.environ.get("AZURE_OPENAI_API_KEY")
    deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT") or os.environ.get("AZURE_OPENAI_DEPLOYMENT_NAME")
    api_version = os.environ.get("AZURE_OPENAI_API_VERSION", "2024-02-01")
    if not endpoint or not key or not deployment:
        return None
    return {
        "endpoint": endpoint.rstrip("/"),
        "key": key,
        "deployment": deployment,
        "api_version": api_version,
    }


def _openai_cfg() -> Optional[Dict[str, str]]:
    key = os.environ.get("OPENAI_API_KEY")
    model = os.environ.get("OPENAI_MODEL") or "gpt-4o-mini"
    if not key:
        return None
    return {"key": key, "model": model}


_SYSTEM = """You translate user questions into a single safe T-SQL SELECT query.
Rules:
- Output ONLY SQL, no commentary.
- Must be a single SELECT statement.
- Never modify data (no INSERT/UPDATE/DELETE/MERGE/DDL/EXEC).
- Use only the provided table and columns.
"""


def nl_to_sql_select(
    *,
    question: str,
    table: str,
    columns: List[Dict[str, Any]],
    max_rows: Optional[int] = None,
) -> Tuple[str, Optional[Dict[str, int]]]:
    """
    Use OpenAI (or Azure OpenAI) to translate question → SELECT query for one table.
    Returns (sql, usage_dict_or_none).
    """
    # Prefer central config.
    try:
        from agent.model_config import load_llm_config
    except Exception:
        load_llm_config = None  # type: ignore

    llm = load_llm_config(purpose="nl_to_sql") if load_llm_config else None
    cfg_az = _azure_openai_cfg()
    cfg_oai = _openai_cfg()
    if llm:
        if llm.provider == "azure_openai":
            cfg_az = {"endpoint": llm.endpoint or "", "key": llm.api_key, "deployment": llm.model, "api_version": llm.api_version or "2024-02-01"}
            cfg_oai = None
        else:
            cfg_oai = {"key": llm.api_key, "model": llm.model}
            cfg_az = None

    if not cfg_az and not cfg_oai:
        raise RuntimeError(
            "LLM not configured for NL→SQL. Set either OPENAI_API_KEY (and optional OPENAI_MODEL) "
            "or AZURE_OPENAI_ENDPOINT/AZURE_OPENAI_API_KEY/AZURE_OPENAI_DEPLOYMENT."
        )

    cols_compact = ", ".join([f"{c.get('name')}({c.get('type')})" for c in columns[:80]])
    limit_line = f"Row limit: {max_rows}" if max_rows is not None else "Row limit: no enforced limit"
    user = f"""Table: {table}
Columns: {cols_compact}
{limit_line}

User question: {question}
"""

    if cfg_az:
        from openai import AzureOpenAI  # type: ignore

        client = AzureOpenAI(api_key=cfg_az["key"], api_version=cfg_az["api_version"], azure_endpoint=cfg_az["endpoint"])
        resp = client.chat.completions.create(
            model=cfg_az["deployment"],
            messages=[
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": user},
            ],
            temperature=0.0,
            max_tokens=600,
        )
    else:
        from openai import OpenAI  # type: ignore

        client = OpenAI(api_key=cfg_oai["key"])
        resp = client.chat.completions.create(
            model=cfg_oai["model"],
            messages=[
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": user},
            ],
            temperature=0.0,
            max_tokens=600,
        )
    sql = (resp.choices[0].message.content or "").strip()
    return sql, usage_dict_from_response(resp)

