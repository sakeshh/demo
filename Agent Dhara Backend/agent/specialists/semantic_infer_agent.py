import json
import logging
import pandas as pd
from typing import Any, Dict, List, Optional
from agent.model_config import load_llm_config

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """
You are a data intelligence agent. Analyze the columns of a dataset and determine their exact semantic category.
Assign one of the following five semantic tags to each column:
- 'id': If the column is an identifier, key, primary key, foreign key, email, phone number, SSN, IP address, UUID, URL, zip code, or other unique reference.
- 'metric': If the column is a numerical measure, count, continuous/discrete number, fee, credits, quantity, temperature, or other numeric value on which mathematical operations like mean, standard deviation, outliers (z-score, IQR) make sense.
- 'categorical': If the column is a classification, category status, code, gender, country, or boolean value where unique values are limited.
- 'date': If the column is a date, time, timestamp, or year.
- 'text': If the column is free-form text, descriptions, comments, or general text.

Guidelines:
- Never assign 'metric' to phone numbers, emails, URLs, IDs, zip codes, or other codes. Those must be classified as 'id'.
- Continuous numeric values like price, quantity, fee, credits are 'metric'.
- Return a JSON response with the classified columns.

Format of JSON response:
{
  "columns": [
    {
      "name": "column_name",
      "semantic_tag": "id|metric|categorical|date|text",
      "reasoning": "brief explanation of why this category was selected"
    }
  ]
}
"""

def fallback_infer_semantics(columns: List[str], sample_df: pd.DataFrame) -> Dict[str, str]:
    from agent.intelligent_data_assessment import detect_semantic_type, _is_text_dtype
    res = {}
    for col in columns:
        if col not in sample_df.columns:
            res[col] = "text"
            continue
        series = sample_df[col]
        c_lower = col.lower()
        
        # 1. Check if it's primarily numeric first!
        s_str = series.astype(str).str.strip() if _is_text_dtype(series.dtype) else series
        num = pd.to_numeric(s_str, errors="coerce")
        non_null = int(series.notna().sum())
        parse_ok = int(num.notna().sum())
        is_numeric = parse_ok >= max(1, int(0.5 * non_null)) if non_null > 0 else False
        
        # 2. Identify semantic patterns
        is_id_name = (
            any(x in c_lower for x in ("phone", "email", "ssn", "zip", "postal")) or
            c_lower == "id" or c_lower.endswith("_id") or c_lower.endswith(" id") or
            c_lower.endswith("key") or c_lower.endswith("code") or
            any(x in c_lower for x in ("student_id", "course_id", "instructor_id", "batch_id", "run_id"))
        )
        
        detected = detect_semantic_type(series, col_name=col)
        
        # Refine numeric_id vs continuous metric count (e.g. credits, age)
        is_actual_id = is_id_name or detected in ("email", "uuid", "url", "ip_address", "phone")
        if detected == "numeric_id":
            if is_id_name or any(x in c_lower for x in ("id", "key", "code", "num", "no", "number")):
                is_actual_id = True
        
        if is_actual_id:
            res[col] = "id"
        elif detected == "date" or any(x in c_lower for x in ("date", "time", "dob", "stamp")) or c_lower.endswith("_at"):
            res[col] = "date"
        elif is_numeric:
            res[col] = "metric"
        elif detected in ("boolean_like", "categorical"):
            res[col] = "categorical"
        elif detected == "free_text":
            res[col] = "text"
        else:
            res[col] = "text"
    return res

class SemanticInferAgent:
    def infer_semantics(
        self,
        *,
        table_name: str,
        df: pd.DataFrame,
    ) -> Dict[str, str]:
        """
        Infer semantic categories for all columns in the dataframe.
        Returns a dict: {column_name: semantic_tag}
        """
        columns = list(df.columns)
        # Pull up to 5 sample rows
        sample_df = df.head(5)
        
        cfg = load_llm_config(purpose="semantic_inference")
        if cfg is None:
            logger.info("LLM not configured for semantic inference. Using fallback heuristics.")
            return fallback_infer_semantics(columns, sample_df)
            
        # Build prompt payload
        cols_payload = []
        for col in columns:
            series = sample_df[col]
            cols_payload.append({
                "name": col,
                "dtype": str(series.dtype),
                "sample_values": series.dropna().tolist()
            })
            
        payload = {
            "table_name": table_name,
            "columns": cols_payload
        }
        
        prompt = json.dumps(payload, ensure_ascii=False)
        try:
            if cfg.provider == "azure_openai":
                from openai import AzureOpenAI  # type: ignore
                client = AzureOpenAI(
                    api_key=cfg.api_key,
                    api_version=cfg.api_version or "2024-02-01",
                    azure_endpoint=cfg.endpoint,
                )
            else:
                from openai import OpenAI  # type: ignore
                client = OpenAI(api_key=cfg.api_key)
                
            resp = client.chat.completions.create(
                model=cfg.model,
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": f"Infer column categories for table '{table_name}':\n{prompt}"}
                ],
                temperature=0.0,
                response_format={"type": "json_object"},
            )
            raw = (resp.choices[0].message.content or "").strip()
            obj = json.loads(raw)
            inferred = {}
            for col_obj in obj.get("columns", []):
                name = col_obj.get("name")
                tag = (col_obj.get("semantic_tag") or "").lower().strip()
                if tag in ("id", "metric", "categorical", "date", "text"):
                    inferred[name] = tag
            
            # fill in missing columns using fallback
            missing = [c for c in columns if c not in inferred]
            if missing:
                fallback_res = fallback_infer_semantics(missing, sample_df)
                inferred.update(fallback_res)
                
            return inferred
        except Exception as e:
            logger.error(f"LLM semantic inference failed: {e}. Using fallback heuristics.")
            return fallback_infer_semantics(columns, sample_df)
