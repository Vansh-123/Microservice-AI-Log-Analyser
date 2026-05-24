from __future__ import annotations

import asyncio
import json
import os
import tempfile
from collections import Counter
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

import streamlit as st

from logai.ai import AIConfigError, analyze_overall_rca, enrich_groups
from logai.env import load_project_env
from logai.grouping import group_errors
from logai.models import AnalysisResult
from logai.parsers import is_error, parse_lines
from logai.reporting import render_html


st.set_page_config(page_title="LogAI", page_icon="LA", layout="wide")
load_project_env()


def analyze_text(
    text: str,
    source: str,
    max_groups: int,
    ai_provider: str,
    ai_model: str | None,
    concurrency: int,
    ai_mode: str,
) -> AnalysisResult:
    entries = parse_lines(text.splitlines(), source)
    errors = [entry for entry in entries if is_error(entry)]
    groups = group_errors(errors)[:max_groups]

    overall_rca = None
    if ai_provider != "none" and groups:
        load_provider_secret(ai_provider)
        if ai_mode == "Overall RCA":
            overall_rca = asyncio.run(
                analyze_overall_rca(groups, ai_provider, ai_model or None, len(entries), len(errors), max_groups)
            )
        else:
            asyncio.run(enrich_groups(groups, ai_provider, ai_model or None, concurrency))

    return AnalysisResult(
        generated_at=datetime.now(),
        total_entries=len(entries),
        error_entries=len(errors),
        groups=groups,
        sources=[source],
        stats={
            "formats": dict(Counter(entry.format for entry in entries)),
            "severities": dict(Counter(entry.severity or "UNKNOWN" for entry in entries)),
        },
        overall_rca=overall_rca,
    )


def result_json(result: AnalysisResult) -> str:
    return json.dumps(asdict(result), indent=2, default=str)


def result_html(result: AnalysisResult) -> str:
    with tempfile.NamedTemporaryFile("r+", suffix=".html", delete=False, encoding="utf-8") as handle:
        path = handle.name
    render_html(result, path)
    html = Path(path).read_text(encoding="utf-8")
    Path(path).unlink(missing_ok=True)
    return html


def metric_card(label: str, value: object) -> None:
    st.metric(label, value)


def render_metadata(metadata: dict) -> None:
    simple_items = {
        key: value
        for key, value in metadata.items()
        if key != "json" and not isinstance(value, (dict, list))
    }
    ranked_items = {
        key: value
        for key, value in metadata.items()
        if key != "json" and isinstance(value, list)
    }

    if simple_items:
        for key, value in simple_items.items():
            st.write(f"**{key.replace('_', ' ').title()}**: `{value}`")
    if ranked_items:
        for key, values in ranked_items.items():
            formatted = ", ".join(f"{item} ({count})" for item, count in values[:3])
            st.write(f"**{key.replace('_', ' ').title()}**: {formatted}")
    if "json" in metadata:
        with st.expander("Raw JSON metadata", expanded=False):
            st.json(metadata["json"])


def summarize_metadata(metadata: dict) -> str:
    parts: list[str] = []
    for key, value in metadata.items():
        if key == "json":
            continue
        label = key.replace("_", " ").title()
        if isinstance(value, list) and value:
            top = value[0]
            if isinstance(top, (list, tuple)) and len(top) == 2:
                parts.append(f"{label}: {top[0]} ({top[1]})")
            else:
                parts.append(f"{label}: {top}")
        elif not isinstance(value, dict):
            parts.append(f"{label}: {value}")
    return ", ".join(parts) or "-"


def load_provider_secret(provider: str) -> None:
    load_project_env()
    secret_names = {
        "groq": "GROQ_API_KEY",
        "openai": "OPENAI_API_KEY",
    }
    env_name = secret_names.get(provider)
    if not env_name or os.getenv(env_name):
        return
    try:
        value = st.secrets.get(env_name)
    except Exception:
        value = None
    if value:
        os.environ[env_name] = str(value)


def provider_key_status(provider: str) -> str:
    load_provider_secret(provider)
    env_names = {
        "groq": "GROQ_API_KEY",
        "openai": "OPENAI_API_KEY",
    }
    env_name = env_names.get(provider)
    if not env_name:
        return "No API key needed for this provider."
    if os.getenv(env_name):
        return f"{env_name} configured."
    return f"{env_name} missing. Add it to .env and restart or rerun the app."


st.title("LogAI")
st.caption("Analyze application logs, group recurring errors, and get practical fix suggestions.")

with st.sidebar:
    st.header("Analysis")
    max_groups = st.slider("Max groups", min_value=5, max_value=100, value=25, step=5)
    ai_provider = st.selectbox("AI provider", ["none", "openai", "groq", "ollama", "claude", "gemini", "bedrock"])
    ai_mode = st.radio("AI mode", ["Overall RCA", "Per-group fixes"], horizontal=False)
    ai_model = st.text_input("AI model", placeholder="llama-3.3-70b-versatile, gpt-4.1-mini, or llama3.1")
    concurrency = st.slider("AI concurrency", min_value=1, max_value=20, value=5)
    st.divider()
    if ai_provider != "none":
        status = provider_key_status(ai_provider)
        if "configured" in status:
            st.success(status)
        else:
            st.warning(status)
    st.caption("AI keys are loaded from .env, environment variables, or Streamlit secrets. Ollama expects localhost:11434.")

uploaded = st.file_uploader("Upload a log file", type=["log", "txt", "json"], accept_multiple_files=False)
sample_path = Path("examples/sample.log")
sample_text = sample_path.read_text(encoding="utf-8") if sample_path.exists() else ""

default_text = ""
source = "pasted-log"
if uploaded is not None:
    default_text = uploaded.getvalue().decode("utf-8", errors="replace")
    source = uploaded.name
elif st.toggle("Use bundled sample log", value=True):
    default_text = sample_text
    source = "examples/sample.log"

if "log_text" not in st.session_state or st.session_state.get("active_source") != source:
    st.session_state["log_text"] = default_text
    st.session_state["active_source"] = source

with st.form("analysis_form", clear_on_submit=False):
    log_text = st.text_area("Log input", key="log_text", height=280, placeholder="Paste logs here...")
    run = st.form_submit_button("Analyze logs", type="primary", use_container_width=True)

if run:
    if not log_text.strip():
        st.warning("Paste or upload logs before running analysis.")
        st.stop()

    st.session_state.pop("result", None)
    with st.spinner("Doing the detective work..."):
        try:
            result = analyze_text(log_text, source, max_groups, ai_provider, ai_model, concurrency, ai_mode)
        except AIConfigError as exc:
            st.error(str(exc))
            st.stop()
        except Exception as exc:  # Streamlit should show a friendly top-level failure.
            st.exception(exc)
            st.stop()

    st.session_state["result"] = result
    st.session_state["last_analyzed_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

result = st.session_state.get("result")
if result:
    st.success(f"Analysis refreshed at {st.session_state.get('last_analyzed_at', 'now')}.")
    left, middle, right, last = st.columns(4)
    with left:
        metric_card("Total entries", result.total_entries)
    with middle:
        metric_card("Error entries", result.error_entries)
    with right:
        metric_card("Error groups", len(result.groups))
    with last:
        metric_card("Formats", len(result.stats.get("formats", {})))

    if result.overall_rca:
        st.subheader("Overall RCA")
        st.info(result.overall_rca)

    st.subheader("Error Pattern Summary")
    summary_rows = [
        {
            "Count": group.count,
            "Severity": group.severity or "UNKNOWN",
            "Pattern": group.pattern,
            "Top metadata": summarize_metadata(group.metadata),
        }
        for group in result.groups
    ]
    st.dataframe(summary_rows, use_container_width=True, hide_index=True)

    show_details = st.toggle("Show detailed groups and examples", value=not bool(result.overall_rca))
    if show_details:
        query = st.text_input("Filter groups", placeholder="Search pattern, severity, suggestion, metadata")

        visible_groups = []
        for group in result.groups:
            haystack = f"{group.pattern} {group.severity} {group.suggestion} {group.metadata}".lower()
            if query.lower() in haystack:
                visible_groups.append(group)

        for group in visible_groups:
            with st.expander(f"{group.count}x - {group.severity or 'UNKNOWN'} - {group.pattern}", expanded=group is visible_groups[0] and not result.overall_rca):
                cols = st.columns([1, 3])
                with cols[0]:
                    st.write("Signature")
                    st.code(group.signature)
                    st.write("First seen")
                    st.write(group.first_seen or "-")
                    st.write("Last seen")
                    st.write(group.last_seen or "-")
                with cols[1]:
                    if group.metadata:
                        st.write("Metadata")
                        render_metadata(group.metadata)
                    if group.suggestion:
                        st.write("Suggestion")
                        st.info(group.suggestion)
                    st.write("Examples")
                    for entry in group.examples:
                        st.code(entry.raw, language="text")

    json_data = result_json(result)
    html_data = result_html(result)
    export_left, export_right = st.columns(2)
    with export_left:
        st.download_button("Download JSON", json_data, file_name="logai-report.json", mime="application/json")
    with export_right:
        st.download_button("Download HTML", html_data, file_name="logai-report.html", mime="text/html")
else:
    st.info("Upload a log file or use the bundled sample, then click Analyze logs.")
