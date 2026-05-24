from __future__ import annotations

import hashlib
import re
from collections import Counter, defaultdict

from .models import ErrorGroup, LogEntry

NORMALIZERS = [
    (re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I), "<uuid>"),
    (re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b"), "<ip>"),
    (re.compile(r"\b0x[0-9a-f]+\b", re.I), "<hex>"),
    (re.compile(r"\b\d{4}-\d{2}-\d{2}[T ][\d:.]+(?:Z|[+-]\d\d:?\d\d)?\b"), "<timestamp>"),
    (re.compile(r"(['\"])(?:\\.|(?!\1).)*\1"), "<string>"),
    (re.compile(r"(?<=/)[A-Za-z0-9_.-]{12,}(?=/|\s|$)"), "<token>"),
    (re.compile(r"\b\d+\b"), "<num>"),
]


def group_errors(entries: list[LogEntry], max_examples: int = 3) -> list[ErrorGroup]:
    groups: dict[str, ErrorGroup] = {}
    metadata_values: dict[str, Counter[str]] = defaultdict(Counter)

    for entry in entries:
        pattern = normalize_message(_group_basis(entry))
        signature = hashlib.sha1(f"{entry.severity}|{pattern}".encode("utf-8")).hexdigest()[:12]
        group = groups.setdefault(signature, ErrorGroup(signature=signature, pattern=pattern, severity=entry.severity))
        group.count += 1
        group.first_seen = min(filter(None, [group.first_seen, entry.timestamp]), default=entry.timestamp)
        group.last_seen = max(filter(None, [group.last_seen, entry.timestamp]), default=entry.timestamp)
        if len(group.examples) < max_examples:
            group.examples.append(entry)
        for key in ("exception", "file_path", "function", "status", "process"):
            if key in entry.metadata:
                metadata_values[f"{signature}:{key}"][str(entry.metadata[key])] += 1

    for signature, group in groups.items():
        group.metadata = {
            key.split(":", 1)[1]: values.most_common(5)
            for key, values in metadata_values.items()
            if key.startswith(f"{signature}:")
        }
    return sorted(groups.values(), key=lambda item: (-item.count, item.severity or "", item.pattern))


def normalize_message(message: str) -> str:
    text = " ".join(message.split())
    text = re.sub(r"\b(?:request[_-]?id|req[_-]?id|trace[_-]?id|correlation[_-]?id)[=:]\s*[A-Za-z0-9_.:-]+", r"request_id=<id>", text, flags=re.I)
    for regex, replacement in NORMALIZERS:
        text = regex.sub(replacement, text)
    text = re.sub(r"([?&][A-Za-z0-9_.-]+)=([^&\s]+)", r"\1=<value>", text)
    return text[:500]


def _group_basis(entry: LogEntry) -> str:
    first_line = (entry.message or entry.raw).splitlines()[0]
    exception = entry.metadata.get("exception")
    file_path = entry.metadata.get("file_path")
    line_number = entry.metadata.get("line_number")
    if exception:
        location = f" {file_path}:{line_number}" if file_path and line_number else ""
        return f"{first_line} {exception}{location}"
    return first_line
