from __future__ import annotations

import pandas as pd

from agent.assessment_governance import enrich_assessment_with_governance
from agent.cross_field_rules import evaluate_cross_field_rules
from agent.drift_analyzer import aggregate_drift
from agent.drift_detector import compare_snapshots
from agent.metadata_registry import validate_manifest_against_schema
from agent.profile_snapshot_store import build_profile_fingerprint
from agent.reconciliation_tracker import build_reconciliation_from_profile
from agent.semantic_context_builder import build_semantic_context_for_dataset


def test_aggregate_drift():
    agg = aggregate_drift(
        {
            "a": {"severity": "medium", "signals": [{"kind": "x"}], "has_baseline": True},
        }
    )
    assert agg["worst_severity"] == "medium"
    assert agg["total_signal_count"] == 1


def test_reconciliation_balanced():
    r = build_reconciliation_from_profile("t1", 100, parse_failures=0)
    assert r["dataset"] == "t1"
    assert r["stages"]["source"] == 100
    assert r["balanced"] is True


def test_cross_field_non_negative():
    df = pd.DataFrame({"amount": [1.0, -2.0, 3.0]})
    issues = evaluate_cross_field_rules(
        "orders",
        df,
        [{"dataset": "orders", "type": "non_negative", "column": "amount", "severity": "high"}],
    )
    assert len(issues) == 1
    assert issues[0]["type"] == "cross_field_non_negative"


def test_manifest_validation_errors():
    entry = {"primary_key": ["missing_col"], "columns": {}}
    errs = validate_manifest_against_schema(entry, ["a", "b"])
    assert any("missing_col" in e for e in errs)


def test_drift_no_baseline():
    fp = build_profile_fingerprint(
        {
            "row_count": 10,
            "column_count": 2,
            "columns": {"a": {"dtype": "int64", "null_percentage": 0.1, "unique_count": 5, "semantic_type": "x"}},
        }
    )
    d = compare_snapshots(None, fp)
    assert d["has_baseline"] is False


def test_semantic_context_basic():
    ds_meta = {
        "row_count": 5,
        "columns": {
            "order_id": {
                "dtype": "int64",
                "null_percentage": 0,
                "unique_count": 5,
                "semantic_type": "numeric_id",
                "candidate_primary_key": True,
            },
        },
    }
    ctx = build_semantic_context_for_dataset("orders", ds_meta, manifest_entry={}, glossary={})
    assert "order_id" in ctx["critical_columns"]


def test_enrich_assessment_minimal(tmp_path, monkeypatch):
    monkeypatch.setenv("DHARA_MANIFEST_HISTORY_DIR", str(tmp_path))
    df = pd.DataFrame({"x": [1, 2, 3]})
    assess = {
        "datasets": {
            "t": {
                "row_count": 3,
                "column_count": 1,
                "columns": {
                    "x": {
                        "dtype": "int64",
                        "null_percentage": 0.0,
                        "unique_count": 3,
                        "semantic_type": "integer",
                    },
                },
            }
        },
        "relationships": [],
        "data_quality_issues": {
            "datasets": {
                "t": {
                    "issues": [],
                    "summary": {
                        "issue_count": 0,
                        "high_severity": 0,
                        "medium_severity": 0,
                        "low_severity": 0,
                    },
                }
            },
            "global_issues": {},
        },
        "executive_summary_items": [],
    }
    out = enrich_assessment_with_governance(assess, {"t": df}, business_rules={})
    assert "semantic_context" in out
    assert "contract" in (out.get("semantic_context") or {})
    assert "governance" in out
    gov = out.get("governance") or {}
    assert "contract_snapshot" in gov
    assert gov["contract_snapshot"].get("saved") is True
    assert "reconciliation" in out
    assert "drift_analysis" in out
    assert "reconciliation_analysis" in out
