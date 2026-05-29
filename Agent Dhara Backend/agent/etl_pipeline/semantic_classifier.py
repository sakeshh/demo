"""
Semantic Classifier: Heuristic-based classification of column semantic types and sub-types.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

# Core regexes for value-based scanning
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
_IP4_RE = re.compile(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$")
_URL_RE = re.compile(r"^https?://[^\s/$.?#].[^\s]*$")
_BOOL_VALS = {"true", "false", "yes", "no", "y", "n", "t", "f", "0", "1"}
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$|^\d{1,2}/\d{1,2}/\d{4}$|^\d{2}-\d{2}-\d{4}$|^\d{4}/\d{2}/\d{2}$")
_ZIP_RE = re.compile(r"^\d{5}(-\d{4})?$|^\d{6}$")
_SSN_RE = re.compile(r"^\d{3}-\d{2}-\d{4}$|^\d{9}$")
_PHONE_RE = re.compile(r"^[+()\-\.\s0-9]{7,25}$")

_PHONE_NAME_HINTS = {
    "phone", "mobile", "cell", "tel", "contact", "whatsapp", "landline", "ph_no", "phno", "phone_no"
}

class SemanticDescriptor(dict):
    """
    A custom dictionary subclass that represents a semantic column descriptor.
    Provides backward compatibility with code that treats semantic_schema as a flat key-to-string dictionary by comparing equal to string semantic types.
    """
    def __eq__(self, other):
        if isinstance(other, str):
            return (
                self.get("semantic_type") == other
                or self.get("sub_type") == other
                or self.get("original_semantic_type") == other
            )
        return super().__eq__(other)

    def __ne__(self, other):
        return not self.__eq__(other)

    def __str__(self):
        return str(self.get("original_semantic_type") or self.get("semantic_type") or "")

    def lower(self):
        return str(self).lower()

    def strip(self):
        return str(self).strip()

    def startswith(self, prefix, *args, **kwargs):
        return str(self).startswith(prefix, *args, **kwargs)


def classify_column_semantic(
    col_name: str,
    col_meta: dict,
    sample_values: list = None,
) -> dict:
    """
    Classifies a column to compute its semantic_type, sub_type, pii_level, fill_strategy, etc.
    This replaces duplicate heuristics and acts as Layer 1 (Heuristics).
    """
    col_lower = str(col_name or "").lower().strip()
    dtype = str(col_meta.get("dtype") or col_meta.get("inferred_type") or "").lower()
    
    # Defaults
    semantic_type = "string"
    sub_type = "unknown"
    pii_level = "none"
    allowed_domain = None
    valid_range = None
    expected_format = None
    fill_strategy = "fill_mode"
    transform_hints = []
    confidence = 0.50

    # Read samples
    samples = sample_values or col_meta.get("raw_samples") or []
    samples = [str(s).strip() for s in samples if s is not None and str(s).strip()]
    total_samples = len(samples)

    # 1. Direct metadata checks
    is_metadata = col_lower in (
        "etl_batch_id", "run_id", "etl_created_at", "etl_updated_at",
        "_rn", "_dedup_rn", "etl_run_id", "etl_created_date", "etl_updated_date"
    ) or col_lower.startswith("etl_")

    if is_metadata:
        return {
            "semantic_type": "string" if "char" in dtype or "str" in dtype else "metric",
            "sub_type": "metadata",
            "pii_level": "none",
            "allowed_domain": None,
            "valid_range": None,
            "expected_format": None,
            "fill_strategy": "none",
            "transform_hints": [],
            "confidence": 1.0,
            "inferred_by": "heuristic",
        }

    # 2. Check value-based heuristics first if we have enough samples
    matched_type = None
    if total_samples > 0:
        email_matches = sum(1 for s in samples if _EMAIL_RE.match(s))
        uuid_matches = sum(1 for s in samples if _UUID_RE.match(s))
        ip_matches = sum(1 for s in samples if _IP4_RE.match(s))
        url_matches = sum(1 for s in samples if _URL_RE.match(s))
        date_matches = sum(1 for s in samples if _DATE_RE.match(s))
        zip_matches = sum(1 for s in samples if _ZIP_RE.match(s))
        ssn_matches = sum(1 for s in samples if _SSN_RE.match(s))
        phone_matches = sum(1 for s in samples if _PHONE_RE.match(s))
        bool_matches = sum(1 for s in samples if s.lower() in _BOOL_VALS)

        if email_matches / total_samples >= 0.5:
            matched_type = "email"
        elif uuid_matches / total_samples >= 0.7:
            matched_type = "uuid"
        elif ip_matches / total_samples >= 0.7:
            matched_type = "ip_address"
        elif url_matches / total_samples >= 0.6:
            matched_type = "url"
        elif date_matches / total_samples >= 0.5:
            matched_type = "date"
        elif ssn_matches / total_samples >= 0.7:
            matched_type = "ssn"
        elif zip_matches / total_samples >= 0.7:
            matched_type = "zip_code"
        elif phone_matches / total_samples >= 0.6 and any(hint in col_lower for hint in _PHONE_NAME_HINTS):
            matched_type = "phone"
        elif bool_matches / total_samples >= 0.8:
            matched_type = "boolean_int"

    # 3. Match by name keyword rules if value-scan didn't yield high certainty
    name_matched_subtype = None
    if not matched_type:
        if "email" in col_lower or "mail" in col_lower:
            name_matched_subtype = "email"
        elif any(hint in col_lower for hint in _PHONE_NAME_HINTS):
            name_matched_subtype = "phone"
        elif "ssn" in col_lower or "social" in col_lower or "sin" in col_lower:
            name_matched_subtype = "ssn"
        elif "zip" in col_lower or "postal" in col_lower or "pincode" in col_lower:
            name_matched_subtype = "zip_code"
        elif "uuid" in col_lower or "guid" in col_lower:
            name_matched_subtype = "uuid"
        elif any(kw in col_lower for kw in ("amount", "price", "fee", "cost", "revenue", "sales", "income", "salary", "balance")):
            name_matched_subtype = "currency"
        elif "age" in col_lower or "years" in col_lower:
            name_matched_subtype = "age"
        elif any(kw in col_lower for kw in ("rate", "pct", "percent", "percentage")):
            name_matched_subtype = "percentage"
        elif any(kw in col_lower for kw in ("status", "state", "active", "flag", "is_", "has_")):
            name_matched_subtype = "status_flag"
        elif "country" in col_lower or "nation" in col_lower:
            name_matched_subtype = "country"
        elif "gender" in col_lower or "sex" in col_lower:
            name_matched_subtype = "gender"

    # Resolve finalized subtype and confidence
    final_sub = matched_type or name_matched_subtype or "unknown"
    if matched_type:
        confidence = 0.90
    elif name_matched_subtype:
        confidence = 0.70
    else:
        # Fallback to dtype classification
        if "int" in dtype or "float" in dtype or "decimal" in dtype or "double" in dtype or "numeric" in dtype:
            semantic_type = "metric"
            sub_type = "unknown"
            fill_strategy = "fill_zero"
            transform_hints = ["coerce_numeric"]
            confidence = 0.50
        elif "date" in dtype or "time" in dtype or "timestamp" in dtype:
            semantic_type = "date"
            sub_type = "unknown"
            fill_strategy = "none"
            transform_hints = ["parse_dates"]
            confidence = 0.60
        else:
            semantic_type = "string"
            sub_type = "unknown"
            fill_strategy = "fill_mode"
            transform_hints = ["trim"]
            confidence = 0.50

    # 4. Fill in properties based on resolved sub_type
    if final_sub == "email":
        semantic_type = "id"
        sub_type = "email"
        pii_level = "high"
        expected_format = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
        fill_strategy = "flag"
        transform_hints = ["trim", "lowercase", "sanitize_email"]
    elif final_sub == "phone":
        semantic_type = "id"
        sub_type = "phone"
        pii_level = "high"
        fill_strategy = "flag"
        transform_hints = ["trim", "normalize_phone"]
    elif final_sub == "ssn":
        semantic_type = "id"
        sub_type = "ssn"
        pii_level = "high"
        fill_strategy = "flag"
        transform_hints = ["trim"]
    elif final_sub == "zip_code":
        semantic_type = "id"
        sub_type = "zip_code"
        pii_level = "medium"
        fill_strategy = "fill_mode"
        transform_hints = ["trim"]
    elif final_sub == "uuid":
        semantic_type = "id"
        sub_type = "uuid"
        pii_level = "none"
        fill_strategy = "flag"
        transform_hints = ["trim"]
    elif final_sub == "currency":
        semantic_type = "metric"
        sub_type = "currency"
        pii_level = "none"
        fill_strategy = "fill_zero"
        transform_hints = ["coerce_numeric"]
    elif final_sub == "age":
        semantic_type = "metric"
        sub_type = "age"
        pii_level = "low"
        valid_range = {"min": 0, "max": 120}
        fill_strategy = "fill_median"
        transform_hints = ["coerce_numeric"]
    elif final_sub == "percentage":
        semantic_type = "metric"
        sub_type = "percentage"
        pii_level = "none"
        valid_range = {"min": 0.0, "max": 100.0}
        fill_strategy = "fill_zero"
        transform_hints = ["coerce_numeric"]
    elif final_sub == "status_flag":
        semantic_type = "categorical"
        sub_type = "status_flag"
        pii_level = "none"
        fill_strategy = "fill_mode"
        transform_hints = ["trim", "uppercase"]
    elif final_sub == "country":
        semantic_type = "categorical"
        sub_type = "country"
        pii_level = "none"
        fill_strategy = "fill_mode"
        transform_hints = ["trim"]
    elif final_sub == "gender":
        semantic_type = "categorical"
        sub_type = "gender"
        pii_level = "low"
        allowed_domain = ["M", "F", "Other", "Unknown"]
        fill_strategy = "fill_mode"
        transform_hints = ["trim", "uppercase"]
    elif final_sub == "boolean_int":
        semantic_type = "categorical"
        sub_type = "boolean_int"
        pii_level = "none"
        fill_strategy = "fill_zero"
        transform_hints = ["standardize_boolean"]
    elif final_sub == "date":
        semantic_type = "date"
        sub_type = "unknown"
        pii_level = "none"
        fill_strategy = "none"
        transform_hints = ["parse_dates"]
    elif final_sub == "ip_address":
        semantic_type = "id"
        sub_type = "ip_address"
        pii_level = "low"
        fill_strategy = "flag"
        transform_hints = ["trim"]
    elif final_sub == "url":
        semantic_type = "string"
        sub_type = "url"
        pii_level = "none"
        fill_strategy = "flag"
        transform_hints = ["trim"]

    # Adjust default primary key check if it is unique & looks like an ID
    if col_meta.get("candidate_primary_key") and semantic_type == "id":
        sub_type = "pk"

    # Adjust foreign keys if column name ends with id and table is not this dataset
    if col_lower.endswith("_id") or col_lower.endswith("id") or col_lower.endswith("key"):
        if semantic_type == "id" and sub_type != "pk":
            sub_type = "fk"

    return SemanticDescriptor({
        "semantic_type": semantic_type,
        "sub_type": sub_type,
        "pii_level": pii_level,
        "allowed_domain": allowed_domain,
        "valid_range": valid_range,
        "expected_format": expected_format,
        "fill_strategy": fill_strategy,
        "transform_hints": transform_hints,
        "confidence": round(confidence, 2),
        "inferred_by": "heuristic",
        "original_semantic_type": col_meta.get("semantic_type"),
    })
