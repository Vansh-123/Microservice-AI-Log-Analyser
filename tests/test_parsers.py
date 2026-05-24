from logai.parsers import detect_format, is_error, parse_lines


def test_detects_json() -> None:
    assert detect_format('{"level":"error","message":"boom"}') == "json"


def test_parse_multiline_stack_trace() -> None:
    entries = parse_lines(
        [
            "2026-05-24T10:15:02Z ERROR failed in /srv/app/users.py:88",
            "Traceback (most recent call last):",
            "  File \"/srv/app/users.py\", line 88, in load_user",
            "DatabaseTimeoutError: timed out after 3000ms",
        ]
    )
    assert len(entries) == 1
    assert entries[0].metadata["file_path"].endswith("users.py")
    assert entries[0].metadata["exception"] == "DatabaseTimeoutError"
    assert is_error(entries[0])


def test_access_log_500_is_error() -> None:
    entry = parse_lines(['127.0.0.1 - - [24/May/2026:10:17:11 +0000] "GET /api HTTP/1.1" 500 531'])[0]
    assert entry.format == "access"
    assert is_error(entry)
