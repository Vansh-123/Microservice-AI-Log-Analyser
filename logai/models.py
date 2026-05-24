from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(slots=True)
class LogEntry:
    raw: str
    source: str
    line_start: int
    line_end: int
    format: str
    timestamp: str | None = None
    severity: str | None = None
    message: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ErrorGroup:
    signature: str
    pattern: str
    severity: str | None
    count: int = 0
    first_seen: str | None = None
    last_seen: str | None = None
    examples: list[LogEntry] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    suggestion: str | None = None


@dataclass(slots=True)
class AnalysisResult:
    generated_at: datetime
    total_entries: int
    error_entries: int
    groups: list[ErrorGroup]
    sources: list[str]
    stats: dict[str, Any]
    overall_rca: str | None = None
