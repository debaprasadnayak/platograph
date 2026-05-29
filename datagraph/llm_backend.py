"""Shared LLM backend detection and invocation for platograph.

Auto-discovers available LLM providers in this priority order:
  1. Anthropic  — ANTHROPIC_API_KEY env var (also set by Claude Code CLI)
  2. Azure OpenAI — AZURE_OPENAI_API_KEY + AZURE_OPENAI_ENDPOINT
  3. OpenAI      — OPENAI_API_KEY env var (also used by Codex CLI)
  4. GitHub      — GITHUB_TOKEN / GH_TOKEN / gh CLI / Copilot config file
                   → calls GitHub Models API (OpenAI-compatible endpoint)
                   Works automatically in GitHub Codespaces, GitHub Actions,
                   and any machine where `gh auth login` has been run.
  5. Databricks  — DATABRICKS_HOST + DATABRICKS_TOKEN
  6. "none"      — no LLM available; callers should fall back gracefully

No configuration required — just have any one of these set up.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Backend detection
# ---------------------------------------------------------------------------

def detect_backend(preferred: str = "auto") -> str:
    """Return the name of the best available LLM backend.

    Pass *preferred* = ``"auto"`` (default) to auto-detect.
    Any other value is returned as-is (allows callers to override).
    """
    if preferred != "auto":
        return preferred

    if os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic"

    if os.environ.get("AZURE_OPENAI_API_KEY") and os.environ.get("AZURE_OPENAI_ENDPOINT"):
        return "azure_openai"

    if os.environ.get("OPENAI_API_KEY"):
        return "openai"

    if find_github_token():
        return "github"

    if os.environ.get("DATABRICKS_HOST") and os.environ.get("DATABRICKS_TOKEN"):
        return "databricks"

    return "none"


# ---------------------------------------------------------------------------
# GitHub token discovery
# ---------------------------------------------------------------------------

def find_github_token() -> str | None:
    """Find a usable GitHub token from any of the standard sources.

    Sources checked (in order):
    - Environment variables: GITHUB_TOKEN, GH_TOKEN (Codespaces / Actions)
    - GitHub CLI: ``gh auth token``  (works after ``gh auth login``)
    - Copilot config file: ~/.config/github-copilot/hosts.json
    """
    # 1. Environment variables — fastest, covers Codespaces and Actions
    for var in ("GITHUB_TOKEN", "GH_TOKEN", "GITHUB_PERSONAL_ACCESS_TOKEN"):
        if token := os.environ.get(var):
            log.debug("GitHub token found via env var %s", var)
            return token

    # 2. GitHub CLI — covers local dev machines where user has run `gh auth login`
    try:
        result = subprocess.run(
            ["gh", "auth", "token"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            token = result.stdout.strip()
            if token:
                log.debug("GitHub token found via gh CLI")
                return token
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        pass  # gh not installed or timed out — try next source

    # 3. Copilot config files (written by VS Code, neovim, JetBrains Copilot plugins)
    copilot_config_dirs = [
        Path.home() / ".config" / "github-copilot",                  # Linux / macOS
        Path.home() / "Library" / "Application Support" / "GitHub Copilot",  # macOS alt
        Path(os.environ.get("APPDATA", "~")) / "GitHub Copilot",      # Windows
    ]
    for config_dir in copilot_config_dirs:
        for filename in ("hosts.json", "apps.json"):
            config_file = config_dir / filename
            if not config_file.exists():
                continue
            try:
                data: dict[str, Any] = json.loads(config_file.read_text())
                for host_data in data.values():
                    if not isinstance(host_data, dict):
                        continue
                    token = host_data.get("oauth_token") or host_data.get("token")
                    if token:
                        log.debug("GitHub token found via %s", config_file)
                        return str(token)
            except Exception:
                pass  # malformed file — try next

    return None


# ---------------------------------------------------------------------------
# Unified call interface
# ---------------------------------------------------------------------------

def call_llm(
    messages: list[dict[str, str]],
    *,
    system: str,
    backend: str,
    max_tokens: int = 1024,
) -> str:
    """Invoke the given *backend* and return the model's text response.

    *messages* should be a list of ``{"role": ..., "content": ...}`` dicts
    (user/assistant turns, without the system message — pass that via *system*).
    """
    if backend == "anthropic":
        return _call_anthropic(messages, system, max_tokens)
    if backend == "azure_openai":
        return _call_openai(messages, system, max_tokens, azure=True)
    if backend == "openai":
        return _call_openai(messages, system, max_tokens, azure=False)
    if backend == "github":
        return _call_github(messages, system, max_tokens)
    if backend == "databricks":
        return _call_databricks(messages, system, max_tokens)
    return ""


# ---------------------------------------------------------------------------
# Backend implementations
# ---------------------------------------------------------------------------

def _call_anthropic(messages: list[dict], system: str, max_tokens: int) -> str:
    import anthropic  # type: ignore[import-untyped]
    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=max_tokens,
        system=system,
        messages=messages,
    )
    return response.content[0].text


def _call_openai(
    messages: list[dict],
    system: str,
    max_tokens: int,
    *,
    azure: bool = False,
) -> str:
    if azure:
        from openai import AzureOpenAI  # type: ignore[import-untyped]
        client: Any = AzureOpenAI(
            api_key=os.environ.get("AZURE_OPENAI_API_KEY"),
            azure_endpoint=os.environ.get("AZURE_OPENAI_ENDPOINT", ""),
            api_version=os.environ.get("AZURE_OPENAI_API_VERSION", "2024-02-01"),
        )
        model = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4o")
    else:
        from openai import OpenAI  # type: ignore[import-untyped]
        client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
        model = os.environ.get("OPENAI_MODEL", "gpt-4o")

    resp = client.chat.completions.create(
        model=model,
        max_tokens=max_tokens,
        messages=[{"role": "system", "content": system}] + messages,
    )
    return resp.choices[0].message.content or ""


def _call_github(messages: list[dict], system: str, max_tokens: int) -> str:
    """Call GitHub Models API — OpenAI-compatible, authenticated with a GitHub token.

    GitHub Models (https://github.com/marketplace/models) is available to all
    GitHub users and grants access to GPT-4o, Claude, Llama, and more.
    Copilot subscribers get higher rate limits.
    """
    from openai import OpenAI  # type: ignore[import-untyped]

    token = find_github_token()
    if not token:
        raise RuntimeError(
            "GitHub backend selected but no token found. "
            "Run `gh auth login` or set GITHUB_TOKEN."
        )

    client = OpenAI(
        base_url="https://models.inference.ai.azure.com",
        api_key=token,
    )
    # Default to gpt-4o; override with GITHUB_MODEL env var
    model = os.environ.get("GITHUB_MODEL", "gpt-4o")

    resp = client.chat.completions.create(
        model=model,
        max_tokens=max_tokens,
        messages=[{"role": "system", "content": system}] + messages,
    )
    return resp.choices[0].message.content or ""


def _call_databricks(messages: list[dict], system: str, max_tokens: int) -> str:
    from databricks.sdk import WorkspaceClient  # type: ignore[import-untyped]
    w = WorkspaceClient()
    endpoint = os.environ.get("DATABRICKS_LLM_ENDPOINT", "databricks-claude-sonnet-4")
    response = w.serving_endpoints.query(
        name=endpoint,
        messages=[{"role": "system", "content": system}] + messages,
    )
    return response.choices[0].message.content or ""
