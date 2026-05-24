from __future__ import annotations

import asyncio
import argparse
from collections import Counter
from datetime import datetime

from .ai import AIConfigError, enrich_groups
from .grouping import group_errors
from .models import AnalysisResult
from .parsers import is_error, read_entries
from .reporting import render_html, render_json, render_terminal


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="logai", description="Analyze logs, group errors, and suggest fixes.")
    parser.add_argument("--version", action="version", version="logai 0.1.0")
    subparsers = parser.add_subparsers(dest="command", required=True)
    analyze_parser = subparsers.add_parser("analyze", help="Analyze one or more log files. Use '-' to read stdin.")
    analyze_parser.add_argument("paths", nargs="+")
    analyze_parser.add_argument("--format", dest="output_format", choices=["terminal", "json", "html"], default="terminal")
    analyze_parser.add_argument("--output", "-o")
    analyze_parser.add_argument("--ai-provider", choices=["none", "openai", "groq", "ollama", "claude", "gemini", "bedrock"], default="none")
    analyze_parser.add_argument("--ai-model")
    analyze_parser.add_argument("--concurrency", type=int, default=5)
    analyze_parser.add_argument("--max-groups", type=int, default=25)
    args = parser.parse_args(argv)
    if args.command == "analyze":
        analyze(args)


def analyze(args: argparse.Namespace) -> None:
    print("Parsing logs...")
    entries = read_entries(list(args.paths))
    print("Grouping errors...")
    errors = [entry for entry in entries if is_error(entry)]
    groups = group_errors(errors)[: args.max_groups]
    if args.ai_provider != "none" and groups:
        print("Asking AI for suggestions...")
        try:
            asyncio.run(enrich_groups(groups, args.ai_provider, args.ai_model, args.concurrency))
        except AIConfigError as exc:
            raise SystemExit(f"error: {exc}") from exc

    result = AnalysisResult(
        generated_at=datetime.now(),
        total_entries=len(entries),
        error_entries=len(errors),
        groups=groups,
        sources=list(args.paths),
        stats={
            "formats": dict(Counter(entry.format for entry in entries)),
            "severities": dict(Counter(entry.severity or "UNKNOWN" for entry in entries)),
        },
    )

    if args.output_format == "terminal":
        render_terminal(result)
    elif args.output_format == "json":
        render_json(result, args.output)
    else:
        render_html(result, args.output or "logai-report.html")


if __name__ == "__main__":
    main()
