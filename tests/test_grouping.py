from logai.grouping import group_errors, normalize_message
from logai.models import LogEntry


def test_normalizes_dynamic_values() -> None:
    first = normalize_message("failed user 123 at 2026-05-24T10:00:00Z")
    second = normalize_message("failed user 456 at 2026-05-24T11:00:00Z")
    assert first == second


def test_groups_similar_errors() -> None:
    entries = [
        LogEntry(raw="a", source="x", line_start=1, line_end=1, format="plain", severity="ERROR", message="failed user 123"),
        LogEntry(raw="b", source="x", line_start=2, line_end=2, format="plain", severity="ERROR", message="failed user 456"),
    ]
    groups = group_errors(entries)
    assert len(groups) == 1
    assert groups[0].count == 2
