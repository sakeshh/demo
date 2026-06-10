import io
import os
import json
import logging
import re
from typing import Any, Dict, List, Optional
import pandas as pd

from agent.model_config import load_llm_config

try:
    from openai import AzureOpenAI, OpenAI
except ImportError:
    AzureOpenAI = None
    OpenAI = None

logger = logging.getLogger(__name__)


def extract_text_from_file(file_bytes: bytes, filename: str) -> str:
    """Extract raw text from TXT, MD, PDF, or DOCX requirements documents."""
    ext = os.path.splitext(filename)[1].lower()
    text = ""
    if ext in (".txt", ".md"):
        try:
            text = file_bytes.decode("utf-8")
        except UnicodeDecodeError:
            text = file_bytes.decode("latin1", errors="ignore")
    elif ext == ".pdf":
        try:
            import pypdf
            reader = pypdf.PdfReader(io.BytesIO(file_bytes))
            pages_text = []
            for i, page in enumerate(reader.pages):
                page_text = page.extract_text()
                if page_text:
                    pages_text.append(page_text)
            text = "\n".join(pages_text)
        except ImportError:
            logger.warning("pypdf not installed. Falling back to printable ASCII parsing.")
            text = "".join(chr(c) if (32 <= c < 127 or c in (10, 13)) else " " for c in file_bytes)
        except Exception as e:
            logger.error(f"Error parsing PDF: {e}")
            raise ValueError(f"Failed to parse PDF file: {str(e)}")
    elif ext == ".docx":
        try:
            import docx
            doc = docx.Document(io.BytesIO(file_bytes))
            paragraphs = [p.text for p in doc.paragraphs]
            text = "\n".join(paragraphs)
        except ImportError:
            logger.warning("python-docx not installed.")
            raise ImportError("python-docx package is required to parse Word documents (.docx)")
        except Exception as e:
            logger.error(f"Error parsing DOCX: {e}")
            raise ValueError(f"Failed to parse Word document: {str(e)}")
    else:
        # Fallback decode
        try:
            text = file_bytes.decode("utf-8")
        except Exception:
            text = file_bytes.decode("latin1", errors="ignore")
    return text


def get_dataset_schemas(session_id: str) -> Dict[str, List[str]]:
    """Discover dataset table/file names and column list from session location setup."""
    from agent.session_store import load_session
    from agent.mcp_interface import _parse_config_text
    
    sess = load_session(session_id)
    context = sess.get("context") or {}
    
    sources_path = os.environ.get("MCP_SOURCES_PATH") or "config/sources.yaml"
    if not os.path.isfile(sources_path):
        return {}
        
    try:
        with open(sources_path, "r", encoding="utf-8") as f:
            config_text = f.read()
        cfg = _parse_config_text(config_text)
        source_cfg = cfg.get("source", cfg) if isinstance(cfg, dict) else {}
        locations = list(source_cfg.get("locations", []) or [])
    except Exception:
        return {}

    selected_tables = context.get("selected_tables") or context.get("last_table_list")
    selected_blob_files = context.get("selected_blob_files") or context.get("last_blob_list")
    selected_local_files = context.get("selected_local_files") or context.get("last_local_file_list")
    
    schemas: Dict[str, List[str]] = {}
    
    try:
        # SQL Database
        if selected_tables:
            db_locs = [l for l in locations if (l.get("type") or "").lower() == "database"]
            db_idx = int(context.get("selected_db_location_index") or 0)
            if db_locs:
                db_idx = max(0, min(db_idx, len(db_locs) - 1))
                loc = db_locs[db_idx]
                conn = loc.get("connection", {}) or {}
                
                from connectors.azure_sql_pythonnet import AzureSQLPythonNetConnector
                if AzureSQLPythonNetConnector is not None:
                    connector = AzureSQLPythonNetConnector(conn)
                    for t in selected_tables:
                        try:
                            df = connector.load_table(t, max_rows=1)
                            schemas[t] = list(df.columns)
                        except Exception:
                            pass
                        
        # Local Filesystem
        elif selected_local_files:
            fs_locs = [l for l in locations if (l.get("type") or "").lower() in ("filesystem", "local_fs")]
            fs_idx = int(context.get("selected_fs_location_index") or 0)
            if fs_locs:
                fs_idx = max(0, min(fs_idx, len(fs_locs) - 1))
                loc = fs_locs[fs_idx]
                root = loc.get("path") or ""
            else:
                root = context.get("local_files_root") or ""
                
            for name in selected_local_files:
                p = os.path.join(root, name) if root else name
                if os.path.isfile(p):
                    try:
                        low = p.lower()
                        if low.endswith(".csv"):
                            df = pd.read_csv(p, nrows=1)
                        elif low.endswith(".tsv"):
                            df = pd.read_csv(p, sep="\t", nrows=1)
                        elif low.endswith((".xlsx", ".xls")):
                            df = pd.read_excel(p, nrows=1)
                        elif low.endswith(".parquet"):
                            df = pd.read_parquet(p)
                        else:
                            df = pd.read_json(p, nrows=1)
                        schemas[name] = list(df.columns)
                    except Exception:
                        pass
    except Exception as e:
        logger.warning(f"Failed to extract column schemas for parsing: {e}")
        
    return schemas


def _get_llm_client():
    cfg = load_llm_config(purpose="general")
    if not cfg:
        return None, None
    if cfg.provider == "azure_openai" and AzureOpenAI and cfg.endpoint:
        client = AzureOpenAI(
            azure_endpoint=cfg.endpoint,
            api_key=cfg.api_key,
            api_version=cfg.api_version or "2024-02-01",
        )
        return client, cfg.model
    if cfg.provider == "openai" and OpenAI:
        return OpenAI(api_key=cfg.api_key), cfg.model
    return None, None


SYSTEM_PROMPT = """You are a senior data analyst and systems architect. Your task is to extract data quality business rules and constraints from the unstructured requirements document provided.
You will be given the list of selected datasets and their available column schemas. Map the extracted business rules to these exact datasets and columns. If a dataset or column name in the requirements does not exactly match the schema, map it to the closest matching column name from the schema.

Return a JSON object with the following keys. All keys are optional, but you should extract as much information as possible:

1. "never_drop_rows": boolean. Set to true if the requirements specify that rows must never be deleted, dropped, or discarded (e.g. "every transaction must be kept", "no rows should be deleted", "ignore null values").
2. "dq_threshold": float. The target data quality score threshold (0-100) if specified (default to 70.0 if not mentioned).
3. "outlier_strategy": string. One of: "flag" (default), "clip", "cap". Based on how outliers should be handled.
4. "required_columns": list of strings. Column names that are mandatory and must be present.
5. "non_nullable": list of strings. Column names that must not contain null/missing values.
6. "exclude_columns": list of strings. Column names that should be excluded from processing/cleaning (e.g. if the user says "ignore null values on Age", add "Age" to non_nullable if nulls are forbidden, or add "Age" to exclude_columns if they want to ignore null checking on it).
7. "valid_values": object mapping column names to lists of allowed values. E.g., {"Status": ["Active", "Inactive"]}.
8. "custom_assertions": list of objects, each representing a rule or formula constraint. Custom assertions must be valid Python/Pandas expressions (e.g. "Price > 0" or "Age >= 18" or "Email.str.endswith('@capgemini.com')"). Each object must have:
   - "assertion": string. E.g., "Email.str.endswith('@capgemini.com')" or "Price > 0".
   - "severity": string. "high", "medium", or "low".
   - "message": string. User-friendly error message if validation fails (e.g., "Email must end with @capgemini.com").
9. "notes": string. General explanation or context about the business requirements that cannot be captured in the structured fields.

Ensure your output is a valid JSON object only. Do not include markdown formatting or extra text."""


def parse_requirements_to_rules(requirements_text: str, schemas: Dict[str, List[str]]) -> Dict[str, Any]:
    """Invoke the LLM to parse requirements text into structured data quality rules."""
    from agent.etl_pipeline.business_rules import normalize_business_rules

    client, model = _get_llm_client()
    if not client or not model:
        # Return fallback empty rules
        return normalize_business_rules({
            "never_drop_rows": False,
            "dq_threshold": 70.0,
            "outlier_strategy": "flag",
            "required_columns": [],
            "non_nullable": [],
            "exclude_columns": [],
            "valid_values": {},
            "custom_assertions": [],
            "notes": "No LLM configuration available to parse requirements."
        })

    schema_context_str = json.dumps(schemas, indent=2)
    user_prompt = f"Available schemas:\n{schema_context_str}\n\nUnstructured Business Requirements:\n{requirements_text}"

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.0,
            response_format={"type": "json_object"}
        )
        raw = response.choices[0].message.content
        parsed = json.loads(raw)
        return normalize_business_rules(parsed)
    except Exception as e:
        logger.error(f"Error calling LLM to parse requirements: {e}")
        return normalize_business_rules({
            "never_drop_rows": False,
            "dq_threshold": 70.0,
            "outlier_strategy": "flag",
            "required_columns": [],
            "non_nullable": [],
            "exclude_columns": [],
            "valid_values": {},
            "custom_assertions": [],
            "notes": f"Error during parsing: {str(e)}"
        })
