"""Tests for memory/store.py — incident CRUD, patterns, search, and context."""

from __future__ import annotations

import pytest
import memory.db as db_module
from memory.store import (
    get_context,
    get_incident,
    get_recent_incidents,
    get_top_patterns,
    memory_summary,
    save_incident,
    search_incidents,
    set_context,
    update_incident,
)


@pytest.fixture(autouse=True)
def use_in_memory_db(tmp_path, monkeypatch):
    """Redirect DB to a fresh in-memory SQLite for every test."""
    monkeypatch.setattr(db_module, "DB_PATH", tmp_path / "test_memory.db")
    db_module.init_db()
    yield


def test_save_incident_returns_int():
    incident_id = save_incident(title="Test crash", severity="high")
    assert isinstance(incident_id, int)
    assert incident_id > 0


def test_get_incident_returns_correct_fields():
    incident_id = save_incident(
        title="OOMKill in payments",
        severity="critical",
        service="payments",
        namespace="prod",
        symptoms="pod killed",
        root_cause="memory leak",
        resolution="restarted pod",
    )
    inc = get_incident(incident_id)
    assert inc is not None
    assert inc["title"] == "OOMKill in payments"
    assert inc["severity"] == "critical"
    assert inc["service"] == "payments"
    assert inc["namespace"] == "prod"
    assert inc["root_cause"] == "memory leak"
    assert inc["resolution"] == "restarted pod"


def test_update_incident_updates_only_specified_fields():
    incident_id = save_incident(title="Flapping pod", severity="low", service="api")
    update_incident(incident_id, severity="high", resolution="fixed")
    inc = get_incident(incident_id)
    assert inc["severity"] == "high"
    assert inc["resolution"] == "fixed"
    assert inc["service"] == "api"  # unchanged


def test_update_incident_ignores_unknown_fields():
    incident_id = save_incident(title="Ghost incident", severity="low")
    # Should not raise
    update_incident(incident_id, nonexistent_field="value", severity="medium")
    inc = get_incident(incident_id)
    assert inc["severity"] == "medium"


def test_search_incidents_by_query():
    save_incident(title="OOMKill in auth", root_cause="memory leak")
    save_incident(title="Network timeout", root_cause="DNS failure")
    results = search_incidents(query="OOMKill")
    assert any("OOMKill" in r["title"] for r in results)


def test_search_incidents_filter_by_service():
    save_incident(title="Crash A", service="payments")
    save_incident(title="Crash B", service="auth")
    results = search_incidents(service="payments")
    assert all(r["service"] == "payments" for r in results)
    assert len(results) == 1


def test_search_incidents_filter_by_resolved():
    id1 = save_incident(title="Resolved incident", severity="low")
    id2 = save_incident(title="Open incident", severity="high")
    update_incident(id1, resolved=1)

    resolved_results = search_incidents(resolved=True)
    assert all(r["resolved"] == 1 for r in resolved_results)

    open_results = search_incidents(resolved=False)
    assert all(r["resolved"] == 0 for r in open_results)


def test_pattern_frequency_increments():
    root = "Container OOMKilled due to memory limit"
    save_incident(title="OOM 1", root_cause=root)
    save_incident(title="OOM 2", root_cause=root)

    patterns = get_top_patterns()
    matching = [p for p in patterns if p["pattern"] == root[:200]]
    assert matching, "Pattern not found"
    assert matching[0]["frequency"] == 2


def test_get_top_patterns_sorted_by_frequency():
    save_incident(title="A", root_cause="rare failure")
    for i in range(3):
        save_incident(title=f"B{i}", root_cause="common failure")

    patterns = get_top_patterns()
    freqs = [p["frequency"] for p in patterns]
    assert freqs == sorted(freqs, reverse=True)


def test_memory_summary_is_non_empty_string():
    save_incident(title="Test incident", severity="medium")
    summary = memory_summary()
    assert isinstance(summary, str)
    assert len(summary) > 0


def test_memory_summary_contains_incident_title():
    save_incident(title="MyUniqueIncidentTitle", severity="high")
    summary = memory_summary()
    assert "MyUniqueIncidentTitle" in summary


def test_set_get_context_roundtrip():
    set_context("mykey", {"foo": [1, 2, 3], "bar": "baz"})
    value = get_context("mykey")
    assert value == {"foo": [1, 2, 3], "bar": "baz"}


def test_get_context_missing_returns_default():
    result = get_context("does_not_exist", "my_default")
    assert result == "my_default"


def test_tags_field_deserialises_to_list():
    incident_id = save_incident(title="Tagged", tags=["k8s", "oom", "prod"])
    inc = get_incident(incident_id)
    assert isinstance(inc["tags"], list)
    assert "k8s" in inc["tags"]


def test_get_recent_incidents_order():
    for i in range(5):
        save_incident(title=f"Incident {i}")
    incidents = get_recent_incidents(limit=5)
    ids = [inc["id"] for inc in incidents]
    assert ids == sorted(ids, reverse=True)
