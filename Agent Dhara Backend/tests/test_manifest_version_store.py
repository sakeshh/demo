from __future__ import annotations

from pathlib import Path

import pytest

from agent.manifest_version_store import (
    diff_contract_snapshots,
    list_contract_snapshots,
    load_contract_snapshot,
    save_contract_snapshot,
)


def test_save_load_contract_roundtrip(tmp_path: Path) -> None:
    c = {"overall_semantic_confidence": 0.9, "by_dataset": {"d1": {"dataset_name": "d1"}}}
    meta = save_contract_snapshot("run_a", c, storage_path=str(tmp_path), schema_hash="abc123")
    assert meta.get("saved") is True
    assert meta.get("contract_sha256")
    loaded = load_contract_snapshot("run_a", storage_path=str(tmp_path))
    assert loaded == c


def test_list_contract_snapshots(tmp_path: Path) -> None:
    save_contract_snapshot("r1", {"a": 1}, storage_path=str(tmp_path))
    save_contract_snapshot("r2", {"b": 2}, storage_path=str(tmp_path))
    rows = list_contract_snapshots(storage_path=str(tmp_path))
    assert len(rows) >= 2


def test_diff_contract_snapshots(tmp_path: Path) -> None:
    save_contract_snapshot(
        "x",
        {"by_dataset": {"a": {}}, "overall_semantic_confidence": 0.5},
        storage_path=str(tmp_path),
    )
    save_contract_snapshot(
        "y",
        {"by_dataset": {"a": {}, "b": {}}, "overall_semantic_confidence": 0.8},
        storage_path=str(tmp_path),
    )
    d = diff_contract_snapshots("x", "y", storage_path=str(tmp_path))
    assert d.get("ok") is True
    assert "b" in (d.get("datasets_added") or [])


def test_diff_missing_snapshot(tmp_path: Path) -> None:
    save_contract_snapshot("only", {"x": 1}, storage_path=str(tmp_path))
    d = diff_contract_snapshots("only", "missing", storage_path=str(tmp_path))
    assert d.get("ok") is False


def test_save_graceful_when_storage_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("agent.manifest_version_store._ensure_dirs", lambda *_a, **_k: False)
    meta = save_contract_snapshot("z", {"k": 1}, storage_path="/tmp/__should_not_matter__")
    assert meta.get("saved") is False
    assert meta.get("warning") == "storage_unavailable"
