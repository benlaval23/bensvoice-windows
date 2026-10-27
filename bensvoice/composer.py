"""Turns a spoken instruction into finished text using Claude Haiku.

Uses an API key from config.json if present (fastest), otherwise the logged-in `claude` CLI (your subscription).
"""
import json
import os
import shutil
import subprocess
import urllib.error
import urllib.request

from .config import APP_DIR, load_config

SYSTEM_PROMPT = """\
You are a writing assistant that drafts text the user will insert directly into whatever app they are typing in.
The user speaks an instruction such as "reply saying I can do Thursday but not Friday" or "write a short description of X, Y and Z".
Rules:
- Output ONLY the final text to insert. No preamble, no quotes, no explanations, no markdown headings.
- Write in first person as the user. Match the register of the app: casual and brief for chat apps (Slack, Teams, WhatsApp, Discord), \
clear and professional for email (Outlook, Gmail), precise and technical for coding tools and AI assistants (Terminal, PowerShell, VS Code, Claude, ChatGPT).
- If selected text is provided, treat it as context: the message being replied to, or the text to rewrite if the user asks for a rewrite.
- If the user is dictating the message itself rather than giving an instruction, just clean it up.
- Keep it as short as the request allows. Never invent facts the user did not give."""


def compose(instruction, selected_text=None, app_name=None):
    prompt = f"App: {app_name or 'unknown'}\n"
    if selected_text:
        prompt += f"Selected text:\n<<<\n{selected_text}\n>>>\n"
    prompt += f"Instruction: {instruction}"

    config = load_config()
    key = config.get("anthropicApiKey") or os.environ.get("ANTHROPIC_API_KEY")
    if key:
        result = _via_api(prompt, key, config.get("model", "claude-haiku-5-5"))
    else:
        result = _via_cli(prompt, config.get("cliModel", "haiku"))
    return result.strip()


def _via_api(prompt, key, model):
    body = json.dumps({
        "model": model,
        "max_tokens": 1024,
        "system": SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": prompt}],
    }).encode()
    req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=body, method="POST", headers={
        "x-api-key": key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.load(r)
    except urllib.error.HTTPError as e:
        try:
            msg = json.load(e)["error"]["message"]
        except Exception:
            msg = f"API error {e.code}"
        raise RuntimeError(msg) from None
    return "".join(block.get("text", "") for block in data.get("content", []))


def _via_cli(prompt, model):
    claude = find_claude()
    if not claude:
        raise RuntimeError("Couldn't find the `claude` CLI")
    # The system prompt goes through a file: newlines and quotes don't survive Windows command lines reliably.
    APP_DIR.mkdir(parents=True, exist_ok=True)
    prompt_file = APP_DIR / "system-prompt.txt"
    prompt_file.write_text(SYSTEM_PROMPT, encoding="utf-8")
    p = subprocess.run(
        [claude, "-p", "--model", model, "--system-prompt-file", str(prompt_file),
         "--tools", "", "--no-session-persistence", "--strict-mcp-config",
         "--setting-sources", "", "--disable-slash-commands"],
        input=prompt, capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=APP_DIR, timeout=120, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if p.returncode != 0:
        raise RuntimeError((p.stderr or p.stdout).strip() or f"claude exited with {p.returncode}")
    return p.stdout


def find_claude():
    home = os.path.expanduser("~")
    appdata = os.environ.get("APPDATA", "")
    candidates = [
        os.path.join(home, ".local", "bin", "claude.exe"),
        os.path.join(home, ".claude", "local", "claude.exe"),
        shutil.which("claude"),
        os.path.join(appdata, "npm", "claude.cmd"),
    ]
    return next((c for c in candidates if c and os.path.isfile(c)), None)
