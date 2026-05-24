from __future__ import annotations

import json
from dataclasses import asdict
from html import escape
from pathlib import Path

from .models import AnalysisResult


def render_terminal(result: AnalysisResult) -> None:
    print("LogAI")
    print("=" * 80)
    print(f"Entries: {result.total_entries}   Errors: {result.error_entries}   Groups: {len(result.groups)}")
    print()
    if result.overall_rca:
        print("Overall RCA")
        print("-" * 80)
        print(result.overall_rca)
        print()
    for group in result.groups:
        meta = ", ".join(f"{key}={values[0][0]}" for key, values in group.metadata.items() if values)
        print(f"[{group.count:>4}] {group.severity or '-':<9} {group.pattern}")
        if meta:
            print(f"       metadata: {meta}")
        if group.suggestion:
            print(f"       suggestion: {group.suggestion}")
        print()


def render_json(result: AnalysisResult, output: str | None) -> None:
    data = json.dumps(asdict(result), indent=2, default=str)
    if output:
        Path(output).write_text(data, encoding="utf-8")
    else:
        print(data)


def render_html(result: AnalysisResult, output: str) -> None:
    group_html = "\n".join(_group_html(group) for group in result.groups)
    html = HTML_TEMPLATE.format(
        generated_at=escape(str(result.generated_at)),
        sources=escape(", ".join(result.sources)),
        total_entries=result.total_entries,
        error_entries=result.error_entries,
        group_count=len(result.groups),
        formats=escape(str(result.stats.get("formats", {}))),
        overall_rca=_overall_rca_html(result.overall_rca),
        groups=group_html,
    )
    Path(output).write_text(html, encoding="utf-8")


def _group_html(group) -> str:
    suggestion = f"<p>{escape(group.suggestion)}</p>" if group.suggestion else ""
    examples = "\n".join(f"<pre>{escape(entry.raw)}</pre>" for entry in group.examples)
    searchable = escape(f"{group.pattern} {group.severity} {group.suggestion or ''}".lower(), quote=True)
    return f"""
      <article class="group" data-text="{searchable}">
        <div class="head">
          <div>
            <span class="badge">{escape(group.severity or "UNKNOWN")}</span>
            <h2>{escape(group.pattern)}</h2>
          </div>
          <strong>{group.count} occurrences</strong>
        </div>
        {suggestion}
        <details>
          <summary>Examples</summary>
          {examples}
        </details>
      </article>
    """


def _overall_rca_html(overall_rca: str | None) -> str:
    if not overall_rca:
        return ""
    return f"""
      <section class="overall">
        <h2>Overall RCA</h2>
        <pre>{escape(overall_rca)}</pre>
      </section>
    """


HTML_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>LogAI Report</title>
  <style>
    :root {{ color-scheme: light; font-family: Inter, Segoe UI, Arial, sans-serif; }}
    body {{ margin: 0; background: #f7f8fa; color: #18202a; }}
    header {{ background: #12343b; color: white; padding: 28px 36px; }}
    main {{ padding: 24px 36px 40px; max-width: 1180px; margin: auto; }}
    .metrics {{ display: grid; grid-template-columns: repeat(4, minmax(140px, 1fr)); gap: 12px; margin: 20px 0; }}
    .metric, .group, .overall {{ background: white; border: 1px solid #dde3ea; border-radius: 8px; padding: 16px; }}
    .metric strong {{ display: block; font-size: 28px; }}
    .toolbar {{ margin: 16px 0; display: flex; gap: 10px; }}
    input {{ width: min(520px, 100%); padding: 10px 12px; border: 1px solid #bbc7d4; border-radius: 6px; }}
    .group {{ margin-bottom: 12px; }}
    .head {{ display: flex; justify-content: space-between; gap: 16px; align-items: start; }}
    .badge {{ background: #e8f1f2; color: #12343b; padding: 3px 8px; border-radius: 999px; font-size: 12px; }}
    pre {{ white-space: pre-wrap; overflow-wrap: anywhere; background: #101820; color: #f4f7fb; padding: 12px; border-radius: 6px; }}
    details {{ margin-top: 10px; }}
    @media (max-width: 720px) {{ header, main {{ padding-left: 16px; padding-right: 16px; }} .metrics {{ grid-template-columns: 1fr 1fr; }} .head {{ flex-direction: column; }} }}
  </style>
</head>
<body>
  <header>
    <h1>LogAI Report</h1>
    <p>{generated_at} · {sources}</p>
  </header>
  <main>
    <section class="metrics">
      <div class="metric"><strong>{total_entries}</strong><span>Total entries</span></div>
      <div class="metric"><strong>{error_entries}</strong><span>Error entries</span></div>
      <div class="metric"><strong>{group_count}</strong><span>Error groups</span></div>
      <div class="metric"><strong>{formats}</strong><span>Formats</span></div>
    </section>
    <div class="toolbar"><input id="filter" placeholder="Filter groups by pattern, severity, or suggestion"></div>
    {overall_rca}
    <section id="groups">
      {groups}
    </section>
  </main>
  <script>
    const filter = document.querySelector("#filter");
    const groups = [...document.querySelectorAll(".group")];
    filter.addEventListener("input", () => {{
      const needle = filter.value.toLowerCase();
      groups.forEach(group => group.style.display = group.dataset.text.includes(needle) ? "" : "none");
    }});
  </script>
</body>
</html>
"""
