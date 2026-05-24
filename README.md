# LogAI

LogAI is a CLI tool that analyzes application logs, groups similar errors, and provides practical suggestions for fixes.

## Quick Start

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
logai analyze examples/sample.log
```

No third-party packages are required for normal CLI usage. Installing the project only gives you the `logai` command shortcut; you can also run `python -m logai.cli analyze examples/sample.log`.

You can also pipe logs:

```powershell
Get-Content examples/sample.log | logai analyze -
```

## Examples

Terminal summary:

```powershell
logai analyze examples/sample.log
```

JSON output:

```powershell
logai analyze examples/sample.log --format json
```

HTML report:

```powershell
logai analyze examples/sample.log --format html --output report.html
```

Streamlit UI:

```powershell
pip install streamlit
streamlit run streamlit_app.py
```

For Groq in the UI, create a `.env` file in the project root:

```powershell
Copy-Item .env.example .env
```

Then edit `.env`:

```text
GROQ_API_KEY=your_groq_key_here
```

Start Streamlit:

```powershell
.\.venv\Scripts\python.exe -m streamlit run streamlit_app.py
```

You can also use environment variables or copy `.streamlit/secrets.toml.example` to `.streamlit/secrets.toml`. Do not commit real secret files.

AI suggestions with OpenAI-compatible APIs:

```powershell
$env:OPENAI_API_KEY = "..."
logai analyze examples/sample.log --ai-provider openai --ai-model gpt-4.1-mini
```

Groq:

```powershell
$env:GROQ_API_KEY = "..."
logai analyze examples/sample.log --ai-provider groq --ai-model llama-3.3-70b-versatile
```

If Groq returns `HTTP 403`, rotate the key if it was exposed, verify the key belongs to the correct Groq project, and check whether the selected model is allowed in GroqCloud model permissions. Leave the UI model field blank to let LogAI try its Groq fallback models.

Local Ollama:

```powershell
logai analyze examples/sample.log --ai-provider ollama --ai-model llama3.1
```

## Current Capabilities

- Auto-detects JSON, Apache/Nginx access logs, syslog, and plain text.
- Preserves multiline stack traces and JSON objects.
- Extracts severity, timestamps, paths, line numbers, request IDs, functions, and exception names.
- Groups similar errors by normalizing dynamic values such as IDs, UUIDs, IPs, paths, and quoted strings.
- Produces one overall RCA across grouped errors, so large log files do not require reading every error individually.
- Emits terminal output, JSON, or an interactive HTML report.
- Supports OpenAI-compatible APIs, Groq, and Ollama, with retries, concurrency control, and response caching.

## Project Status

This is a strong MVP foundation. Provider stubs for Claude, Gemini, and AWS Bedrock are represented as configuration errors until their SDK/API integrations are added.
