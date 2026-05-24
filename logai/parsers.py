from __future__ import annotations

import json
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from .models import LogEntry

SEVERITIES = ("FATAL", "CRITICAL", "ERROR", "ERR", "WARN", "WARNING", "EXCEPTION", "TRACEBACK")

APACHE_RE = re.compile(
    r'(?P<ip>\S+) \S+ \S+ \[(?P<timestamp>[^\]]+)\] "(?P<method>[A-Z]+) (?P<path>\S+) (?P<protocol>[^"]+)" (?P<status>\d{3}) (?P<size>\S+)(?: "(?P<referrer>[^"]*)" "(?P<agent>[^"]*)")?'
)
SYSLOG_RE = re.compile(
    r"(?P<timestamp>[A-Z][a-z]{2}\s+\d{1,2}\s+\d\d:\d\d:\d\d) (?P<host>\S+) (?P<process>[\w./-]+)(?:\[(?P<pid>\d+)\])?: (?P<message>.*)"
)
LEVEL_RE = re.compile(r"\b(FATAL|CRITICAL|ERROR|ERR|WARN|WARNING|INFO|DEBUG|TRACE|EXCEPTION)\b", re.I)
ISO_TS_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}[T ][\d:.]+(?:Z|[+-]\d\d:?\d\d)?\b")
REQUEST_ID_RE = re.compile(r"\b(?:request[_-]?id|req[_-]?id|trace[_-]?id|correlation[_-]?id)[=:]\s*([A-Za-z0-9_.:-]+)", re.I)
FILE_LINE_RE = re.compile(r'(?P<path>(?:[A-Za-z]:)?[\\/][\w .\-\\/]+\.\w+|[\w.\-/]+\.\w+):(?P<line>\d+)')
FUNC_RE = re.compile(r"\b(?:at|in)\s+([A-Za-z_][\w.<>$-]*)\s*\(")
EXCEPTION_RE = re.compile(r"\b([A-Za-z_][\w.]*?(?:Exception|Error))\b")


def read_entries(paths: list[str]) -> list[LogEntry]:
    entries: list[LogEntry] = []
    for source in paths:
        if source == "-":
            import sys

            lines = sys.stdin.read().splitlines()
        else:
            lines = Path(source).read_text(encoding="utf-8", errors="replace").splitlines()
        entries.extend(parse_lines(lines, source))
    return entries


def parse_lines(lines: Iterable[str], source: str = "<memory>") -> list[LogEntry]:
    blocks = _coalesce_multiline(list(lines))
    entries: list[LogEntry] = []
    for start, end, text in blocks:
        fmt = detect_format(text)
        parsed = _parse_by_format(text, fmt)
        metadata = extract_metadata(text, parsed)
        entries.append(
            LogEntry(
                raw=text,
                source=source,
                line_start=start,
                line_end=end,
                format=fmt,
                timestamp=parsed.get("timestamp"),
                severity=parsed.get("severity"),
                message=parsed.get("message") or text,
                metadata=metadata,
            )
        )
    return entries


def detect_format(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("{"):
        try:
            json.loads(stripped)
            return "json"
        except json.JSONDecodeError:
            pass
    if APACHE_RE.match(stripped):
        return "access"
    if SYSLOG_RE.match(stripped):
        return "syslog"
    return "plain"


def is_error(entry: LogEntry) -> bool:
    level = (entry.severity or "").upper()
    if level in {"FATAL", "CRITICAL", "ERROR", "ERR", "EXCEPTION"}:
        return True
    if entry.format == "access":
        status = int(entry.metadata.get("status", 0) or 0)
        return status >= 500
    raw_upper = entry.raw.upper()
    return any(token in raw_upper for token in ("ERROR", "EXCEPTION", "TRACEBACK", "FAILED", "FATAL"))


def _coalesce_multiline(lines: list[str]) -> list[tuple[int, int, str]]:
    blocks: list[tuple[int, int, list[str]]] = []
    current: list[str] = []
    start = 1
    json_depth = 0

    for idx, line in enumerate(lines, start=1):
        begins = _looks_like_new_entry(line)
        stripped = line.strip()
        if current and begins and json_depth <= 0:
            blocks.append((start, idx - 1, current))
            current = []
            start = idx
        if not current:
            start = idx
        current.append(line)
        json_depth += stripped.count("{") - stripped.count("}")
        if stripped.endswith("\\") or line.startswith((" ", "\t", "Traceback", "Caused by:", "at ")):
            continue
    if current:
        blocks.append((start, start + len(current) - 1, current))
    return [(s, e, "\n".join(parts)) for s, e, parts in blocks if any(part.strip() for part in parts)]


def _looks_like_new_entry(line: str) -> bool:
    stripped = line.strip()
    return bool(
        stripped.startswith("{")
        or ISO_TS_RE.search(stripped)
        or SYSLOG_RE.match(stripped)
        or APACHE_RE.match(stripped)
        or LEVEL_RE.search(stripped[:60])
    )


def _parse_by_format(text: str, fmt: str) -> dict[str, Any]:
    if fmt == "json":
        try:
            obj = json.loads(text)
        except json.JSONDecodeError:
            obj = {}
        message = _first_value(obj, "message", "msg", "error", "exception", "detail") or text
        severity = _first_value(obj, "level", "severity", "log.level", "status")
        timestamp = _first_value(obj, "timestamp", "time", "@timestamp", "ts")
        return {"message": str(message), "severity": str(severity).upper() if severity else None, "timestamp": timestamp, "json": obj}
    if fmt == "access":
        match = APACHE_RE.match(text.strip())
        data = match.groupdict() if match else {}
        severity = "ERROR" if int(data.get("status") or 0) >= 500 else "INFO"
        message = f'{data.get("method", "")} {data.get("path", "")} returned {data.get("status", "")}'.strip()
        return {"message": message, "severity": severity, "timestamp": data.get("timestamp"), **data}
    if fmt == "syslog":
        match = SYSLOG_RE.match(text.strip())
        data = match.groupdict() if match else {}
        severity = _find_level(data.get("message", text))
        return {"message": data.get("message", text), "severity": severity, "timestamp": data.get("timestamp"), **data}
    return {"message": text, "severity": _find_level(text), "timestamp": _find_timestamp(text)}


def extract_metadata(text: str, parsed: dict[str, Any]) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    for key in ("ip", "method", "path", "protocol", "status", "host", "process", "pid"):
        if parsed.get(key) is not None:
            metadata[key] = parsed[key]
    request = REQUEST_ID_RE.search(text)
    if request:
        metadata["request_id"] = request.group(1)
    file_line = FILE_LINE_RE.search(text)
    if file_line:
        metadata["file_path"] = file_line.group("path")
        metadata["line_number"] = int(file_line.group("line"))
    function = FUNC_RE.search(text)
    if function:
        metadata["function"] = function.group(1)
    exception = EXCEPTION_RE.search(text)
    if exception:
        metadata["exception"] = exception.group(1)
    if parsed.get("json"):
        metadata["json"] = parsed["json"]
    return metadata


def _first_value(obj: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        current: Any = obj
        for part in key.split("."):
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                current = None
                break
        if current is not None:
            return current
    return None


def _find_level(text: str) -> str | None:
    match = LEVEL_RE.search(text)
    return match.group(1).upper() if match else None


def _find_timestamp(text: str) -> str | None:
    match = ISO_TS_RE.search(text)
    return match.group(0) if match else None
