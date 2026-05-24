from urllib.error import HTTPError
from io import BytesIO

from logai.ai import _read_error_body


def test_reads_groq_error_body() -> None:
    body = b'{"error":{"message":"The model `x` is blocked at the project level.","code":"model_blocked"}}'
    exc = HTTPError("https://api.groq.com/openai/v1/chat/completions", 403, "Forbidden", {}, BytesIO(body))
    detail = _read_error_body(exc)
    assert "blocked at the project level" in detail
    assert "model_blocked" in detail
