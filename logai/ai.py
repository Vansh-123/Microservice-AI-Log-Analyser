from __future__ import annotations

import asyncio
import hashlib
import json
import os
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .env import load_project_env
from .models import ErrorGroup

load_project_env()


class AIConfigError(RuntimeError):
    pass


class AIRequestError(RuntimeError):
    def __init__(self, message: str, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


class SuggestionCache:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or Path.home() / ".cache" / "logai" / "suggestions.json"
        self.data: dict[str, str] = {}
        if self.path.exists():
            try:
                self.data = json.loads(self.path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                self.data = {}

    def get(self, key: str) -> str | None:
        return self.data.get(key)

    def set(self, key: str, value: str) -> None:
        self.data[key] = value
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, indent=2), encoding="utf-8")


async def enrich_groups(
    groups: list[ErrorGroup],
    provider: str,
    model: str | None,
    concurrency: int = 5,
    cache: SuggestionCache | None = None,
) -> None:
    if provider == "none":
        return
    cache = cache or SuggestionCache()
    semaphore = asyncio.Semaphore(max(1, min(concurrency, 20)))

    async def worker(group: ErrorGroup) -> None:
        key = _cache_key(provider, model, group)
        cached = cache.get(key)
        if cached and not _is_failure(cached):
            group.suggestion = cached
            return
        async with semaphore:
            suggestion = await _suggest_with_retry(provider, model, group)
            if not _is_failure(suggestion):
                cache.set(key, suggestion)
            group.suggestion = suggestion

    await asyncio.gather(*(worker(group) for group in groups))


async def analyze_overall_rca(
    groups: list[ErrorGroup],
    provider: str,
    model: str | None,
    total_entries: int,
    error_entries: int,
    max_groups: int = 20,
) -> str | None:
    if provider == "none" or not groups:
        return None
    prompt = _build_overall_prompt(groups[:max_groups], total_entries, error_entries)
    try:
        return await _complete(provider, model, prompt)
    except AIRequestError as exc:
        return f"AI analysis failed: {exc}"
    except (HTTPError, URLError, TimeoutError) as exc:
        return f"AI analysis failed after retries: {exc}"


async def _suggest_with_retry(provider: str, model: str | None, group: ErrorGroup) -> str:
    delay = 1.0
    for attempt in range(3):
        try:
            return await _suggest(provider, model, group)
        except AIRequestError as exc:
            if not exc.retryable or attempt == 2:
                return f"AI analysis failed: {exc}"
            await asyncio.sleep(delay)
            delay *= 2
        except (HTTPError, URLError, TimeoutError) as exc:
            if attempt == 2:
                return f"AI analysis failed after retries: {exc}"
            await asyncio.sleep(delay)
            delay *= 2


async def _suggest(provider: str, model: str | None, group: ErrorGroup) -> str:
    prompt = _build_prompt(group)
    return await _complete(provider, model, prompt)


async def _complete(provider: str, model: str | None, prompt: str) -> str:
    if provider == "openai":
        return await _openai_compatible(
            base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
            api_key=os.getenv("OPENAI_API_KEY"),
            model=model or "gpt-4.1-mini",
            prompt=prompt,
            provider_name="openai",
        )
    if provider == "groq":
        return await _groq(model, prompt)
    if provider == "ollama":
        return await _ollama(model or "llama3.1", prompt)
    if provider in {"claude", "gemini", "bedrock"}:
        raise AIConfigError(f"{provider} support is planned; use openai, groq, or ollama in this MVP.")
    raise AIConfigError(f"Unknown AI provider: {provider}")


async def _groq(model: str | None, prompt: str) -> str:
    base_url = os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1")
    api_key = os.getenv("GROQ_API_KEY")
    if model:
        return await _openai_compatible(base_url, api_key, model, prompt, "groq")

    models = [
        os.getenv("GROQ_MODEL", ""),
        "llama-3.3-70b-versatile",
        "llama-3.1-8b-instant",
    ]
    last_error: Exception | None = None
    for candidate in [item for item in models if item]:
        try:
            return await _openai_compatible(base_url, api_key, candidate, prompt, "groq")
        except AIRequestError as exc:
            last_error = exc
            if "403" not in str(exc):
                raise
    raise AIRequestError(f"Groq request failed for all fallback models. Last error: {last_error}")


async def _openai_compatible(base_url: str, api_key: str | None, model: str, prompt: str, provider_name: str) -> str:
    if not api_key:
        env_name = "GROQ_API_KEY" if provider_name == "groq" else "OPENAI_API_KEY"
        raise AIConfigError(f"{env_name} is required for --ai-provider {provider_name}.")
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "LogAI/0.1 (+https://localhost)",
    }
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "You are a senior incident response engineer. Be concise and practical."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.2,
    }
    data = await asyncio.to_thread(_post_json, f"{base_url.rstrip('/')}/chat/completions", payload, headers, 45)
    return data["choices"][0]["message"]["content"].strip()


async def _ollama(model: str, prompt: str) -> str:
    payload = {"model": model, "prompt": prompt, "stream": False}
    data = await asyncio.to_thread(_post_json, "http://localhost:11434/api/generate", payload, {}, 120)
    return data.get("response", "").strip()


def _post_json(url: str, payload: dict, headers: dict[str, str], timeout: int) -> dict:
    body = json.dumps(payload).encode("utf-8")
    request = Request(url, data=body, headers={"Content-Type": "application/json", **headers}, method="POST")
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = _read_error_body(exc)
        retryable = exc.code == 429 or exc.code >= 500
        raise AIRequestError(f"HTTP {exc.code}: {detail}", retryable=retryable) from exc


def _read_error_body(exc: HTTPError) -> str:
    try:
        raw = exc.read().decode("utf-8", errors="replace")
    except Exception:
        return str(exc)
    if not raw:
        return str(exc)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return raw[:1000]
    error = data.get("error") if isinstance(data, dict) else None
    if isinstance(error, dict):
        message = error.get("message") or error.get("code") or raw
        code = error.get("code")
        return f"{message} (code: {code})" if code else str(message)
    return raw[:1000]


def _build_prompt(group: ErrorGroup) -> str:
    examples = "\n\n".join(entry.raw[:1200] for entry in group.examples)
    return (
        "Analyze this recurring log error. Return likely root cause, immediate triage steps, "
        "and a durable fix. Include code/config examples only when useful.\n\n"
        f"Pattern: {group.pattern}\nCount: {group.count}\nSeverity: {group.severity}\n"
        f"Metadata: {group.metadata}\nExamples:\n{examples}"
    )


def _build_overall_prompt(groups: list[ErrorGroup], total_entries: int, error_entries: int) -> str:
    group_summaries = []
    for index, group in enumerate(groups, start=1):
        examples = "\n".join(entry.raw.splitlines()[0][:300] for entry in group.examples[:2])
        group_summaries.append(
            f"{index}. Count: {group.count}\n"
            f"Severity: {group.severity}\n"
            f"Pattern: {group.pattern}\n"
            f"Metadata: {group.metadata}\n"
            f"Examples:\n{examples}"
        )
    return (
        "You are analyzing an application incident from grouped logs. Do not explain each error one by one. "
        "Infer the most likely system-level root cause across all groups, then give a concise action plan.\n\n"
        "Return this structure:\n"
        "1. Executive summary\n"
        "2. Most likely root cause\n"
        "3. Evidence from logs\n"
        "4. Impact and scope\n"
        "5. Priority fix plan\n"
        "6. What to check next\n\n"
        f"Total log entries: {total_entries}\nError entries: {error_entries}\n"
        f"Grouped error patterns:\n\n{chr(10).join(group_summaries)}"
    )


def _cache_key(provider: str, model: str | None, group: ErrorGroup) -> str:
    digest = hashlib.sha1(f"{provider}|{model}|{group.pattern}|{group.count}".encode("utf-8")).hexdigest()
    return f"{int(time.time() // 86400)}:{digest}"


def _is_failure(suggestion: str) -> bool:
    return suggestion.startswith("AI analysis failed")
