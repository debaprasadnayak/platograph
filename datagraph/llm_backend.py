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

    Returns just the raw token string; call ``find_github_token_with_source()``
    when you also need to know where the token came from.
    """
    result = _find_github_token_with_source()
    return result[0] if result else None


def _find_github_token_with_source() -> tuple[str, str] | None:
    """Return ``(token, source)`` where source is ``"env"``, ``"gh_cli"``, or ``"copilot"``.

    - ``"env"``     — GITHUB_TOKEN / GH_TOKEN env var (Codespaces, Actions, manual export)
    - ``"gh_cli"``  — output of ``gh auth token`` (local dev after ``gh auth login``)
    - ``"copilot"`` — oauth_token from ~/.config/github-copilot/hosts.json;
                       must be exchanged for a session token before calling the API
    """
    # 1. Environment variables
    for var in ("GITHUB_TOKEN", "GH_TOKEN", "GITHUB_PERSONAL_ACCESS_TOKEN"):
        if token := os.environ.get(var):
            log.debug("GitHub token found via env var %s", var)
            return token, "env"

    # 2. GitHub CLI
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
                return token, "gh_cli"
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        pass

    # 3. Copilot config files (written by VS Code / JetBrains / neovim Copilot plugins)
    copilot_config_dirs = [
        Path.home() / ".config" / "github-copilot",
        Path.home() / "Library" / "Application Support" / "GitHub Copilot",
        Path(os.environ.get("APPDATA", "~")) / "GitHub Copilot",
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
                        return str(token), "copilot"
            except Exception:
                pass

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
    """Call GitHub Models API or GitHub Copilot API depending on the token source.

    - Tokens from env vars / gh CLI     → GitHub Models  (models.inference.ai.azure.com)
    - Tokens from Copilot hosts.json    → Copilot Chat API (api.githubcopilot.com)
      The Copilot OAuth token is exchanged for a short-lived session token first.
    """
    result = _find_github_token_with_source()
    if not result:
        raise RuntimeError("GitHub backend selected but no token found")
    token, source = result

    if source == "copilot":
        # Copilot OAuth token: exchange for session token, then call Copilot API
        try:
            return _call_github_copilot(token, messages, system, max_tokens)
        except Exception as exc:
            log.debug("Copilot API failed (%s), trying GitHub Models", exc)
            # Fall through to GitHub Models as last resort

    # Standard GitHub token (env / gh CLI / fallback) → GitHub Models
    return _call_github_models(token, messages, system, max_tokens)


def _call_github_copilot(oauth_token: str, messages: list[dict], system: str, max_tokens: int) -> str:
    """Exchange a Copilot OAuth token for a session token then call the Copilot chat API."""
    import urllib.request

    # Step 1: exchange OAuth token for short-lived Copilot session token
    req = urllib.request.Request(
        "https://api.github.com/copilot_internal/v2/token",
        headers={
            "Authorization": f"token {oauth_token}",
            "Accept": "application/json",
            "User-Agent": "platograph/1.0",
            "Editor-Version": "platograph/1.0",
        },
    )
    with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310
        session_data: dict[str, Any] = json.loads(resp.read())
    session_token: str = session_data["token"]

    # Step 2: call Copilot chat API (OpenAI-compatible)
    from openai import OpenAI  # type: ignore[import-untyped]
    client = OpenAI(
        base_url="https://api.githubcopilot.com",
        api_key=session_token,
        default_headers={
            "Editor-Version": "platograph/1.0",
            "Editor-Plugin-Version": "platograph/1.0",
            "Copilot-Integration-Id": "vscode-chat",
        },
    )
    model = os.environ.get("GITHUB_COPILOT_MODEL", "gpt-4o")
    resp2 = client.chat.completions.create(
        model=model,
        max_tokens=max_tokens,
        messages=[{"role": "system", "content": system}] + messages,
    )
    return resp2.choices[0].message.content or ""


def _call_github_models(token: str, messages: list[dict], system: str, max_tokens: int) -> str:
    """Call GitHub Models API (OpenAI-compatible, authenticated with a GitHub token)."""
    import ssl
    import httpx
    from openai import OpenAI  # type: ignore[import-untyped]

    # Build an SSL context that respects corporate CA bundles.
    # Priority: REQUESTS_CA_BUNDLE / SSL_CERT_FILE env vars → certifi → system default.
    ca_bundle = os.environ.get("REQUESTS_CA_BUNDLE") or os.environ.get("SSL_CERT_FILE")
    ssl_ctx: ssl.SSLContext | bool = True  # httpx default (system certs)
    if ca_bundle:
        ssl_ctx = ssl.create_default_context(cafile=ca_bundle)
    else:
        try:
            import certifi  # type: ignore[import-untyped]
            ssl_ctx = ssl.create_default_context(cafile=certifi.where())
        except ImportError:
            pass  # no certifi — fall back to httpx default (system certs)

    http_client = httpx.Client(verify=ssl_ctx)
    client = OpenAI(
        base_url="https://models.inference.ai.azure.com",
        api_key=token,
        http_client=http_client,
    )
    model = os.environ.get("GITHUB_MODEL", "gpt-4o")
    try:
        resp = client.chat.completions.create(
            model=model,
            max_tokens=max_tokens,
            messages=[{"role": "system", "content": system}] + messages,
        )
        return resp.choices[0].message.content or ""
    except Exception as exc:
        # Traverse the exception chain to detect SSL cert errors (e.g. corporate proxy)
        cause: BaseException | None = exc
        while cause:
            if "CERTIFICATE_VERIFY_FAILED" in str(cause) or "SSL" in type(cause).__name__.upper():
                raise RuntimeError(
                    "SSL certificate verification failed for GitHub Models endpoint. "
                    "If you are on a corporate network with TLS inspection, set the "
                    "REQUESTS_CA_BUNDLE environment variable to your company CA bundle "
                    "path, e.g.: export REQUESTS_CA_BUNDLE=/path/to/ca-bundle.crt"
                ) from exc
            cause = cause.__cause__ or cause.__context__
        raise


def _call_databricks(messages: list[dict], system: str, max_tokens: int) -> str:
    from databricks.sdk import WorkspaceClient  # type: ignore[import-untyped]
    w = WorkspaceClient()
    endpoint = os.environ.get("DATABRICKS_LLM_ENDPOINT", "databricks-claude-sonnet-4")
    response = w.serving_endpoints.query(
        name=endpoint,
        messages=[{"role": "system", "content": system}] + messages,
    )
    return response.choices[0].message.content or ""
