from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
import yaml

logger = logging.getLogger(__name__)

DEFAULT_RULES = Path(__file__).resolve().parent.parent / "config" / "cross_field_rules.yaml"


def load_cross_field_rules(path: Optional[str] = None) -> List[Dict[str, Any]]:
    p = Path(path or os.getenv("DHARA_CROSS_FIELD_RULES", str(DEFAULT_RULES)))
    if not p.is_file():
        return []
    try:
        with open(p, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
        rules = raw.get("rules") or []
        return rules if isinstance(rules, list) else []
    except Exception as e:
        logger.warning("cross_field_rules load failed: %s", e)
        return []


def _match_dataset(rule_ds: str, actual: str) -> bool:
    r = (rule_ds or "*").lower()
    a = actual.lower()
    return r == "*" or r == a or r in a


def evaluate_cross_field_rules(
    dataset_name: str,
    df: pd.DataFrame,
    rules: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    rules = rules if rules is not None else load_cross_field_rules()
    issues: List[Dict[str, Any]] = []
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        if not _match_dataset(str(rule.get("dataset") or "*"), dataset_name):
            continue
        rtype = str(rule.get("type") or "").lower()
        sev = str(rule.get("severity") or "medium").lower()
        try:
            if rtype == "date_order":
                sc, ec = rule.get("start_column"), rule.get("end_column")
                if not sc or not ec or sc not in df.columns or ec not in df.columns:
                    continue
                s = pd.to_datetime(df[sc], errors="coerce")
                e = pd.to_datetime(df[ec], errors="coerce")
                bad = (s.notna() & e.notna() & (s > e)).sum()
                if int(bad) > 0:
                    issues.append(
                        {
                            "type": "cross_field_date_order",
                            "severity": sev if sev in ("high", "medium", "low") else "medium",
                            "column": f"{sc},{ec}",
                            "count": int(bad),
                            "message": f"{sc} > {ec} on {bad} row(s)",
                            "recommendation": "Fix source dates or filter invalid ranges before ETL.",
                        }
                    )
            elif rtype == "non_negative":
                col = rule.get("column")
                if not col or col not in df.columns:
                    continue
                num = pd.to_numeric(df[col], errors="coerce")
                bad = (num.notna() & (num < 0)).sum()
                if int(bad) > 0:
                    issues.append(
                        {
                            "type": "cross_field_non_negative",
                            "severity": sev,
                            "column": str(col),
                            "count": int(bad),
                            "message": f"Negative values in {col}: {bad} row(s)",
                            "recommendation": "Clip, nullify, or reject negatives per business policy.",
                        }
                    )
            elif rtype == "allowed_pairs":
                # region column + customer_type allowed map
                reg_col = rule.get("region_column")
                typ_col = rule.get("type_column")
                allowed = rule.get("allowed") or {}
                if not reg_col or not typ_col or reg_col not in df.columns or typ_col not in df.columns:
                    continue
                if not isinstance(allowed, dict):
                    continue
                bad = 0
                for _, row in df[[reg_col, typ_col]].dropna().iterrows():
                    rgn = str(row[reg_col]).strip().lower()
                    typ = str(row[typ_col]).strip().lower()
                    ok_set = {str(x).lower() for x in (allowed.get(rgn) or allowed.get("*") or [])}
                    if ok_set and typ not in ok_set:
                        bad += 1
                if bad:
                    issues.append(
                        {
                            "type": "cross_field_allowed_pairs",
                            "severity": sev,
                            "column": f"{reg_col},{typ_col}",
                            "count": bad,
                            "message": f"Invalid (region,type) combinations: {bad} row(s)",
                            "recommendation": "Align lookup tables or restrict types per region.",
                        }
                    )
        except Exception as ex:
            logger.debug("rule eval skip: %s", ex)
    return issues
