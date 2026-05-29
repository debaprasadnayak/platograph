"""Shared LLM backend detection and invocation for platograph.

Auto-discovers available LLM providers in this priority order:
  1. anthropic       — ANTHROPIC_API_KEY env var
  2. azure_openai    — AZURE_OPENAI_API_KEY + AZURE_OPENAI_ENDPOINT
  3. openai          — OPENAI_API_KEY env var
  4. github          — GITHUB_TOKEN / GH_TOKEN / gh CLI token
                       → tries GitHub Copilot API first (api.githubcopilot.com),
                         then falls back to GitHub Models (models.inference.ai.azure.com)
  5. databricks      — DATABRICKS_HOST + DATABRICKS_TOKEN
  6. ollama          — Ollama running locally at localhost:11434 (no key required)
  7. claude-code     — `claude` CLI installed (explicit opt-in recommended)
  8. "none"          — no LLM available; callers fall back gracefully

No configuration required — just have any one of these set up.

CLI usage:
  # Use GitHub Copilot session (recommended when gh CLI is authenticated):
  platograph query "..." --backend github-copilot

  # Pass a key inline without exporting env vars:
  platograph query "..." --backend anthropic --api-key sk-ant-...
  platograph query "..." --backend openai    --api-key sk-...
  platograph query "..." --backend github    --api-key ghp_...

  # Use local Ollama (no internet needed):
  platograph scan . --enrich-llm --backend ollama

Explicit key mapping (--api-key sets the corresponding env var):
  anthropic / claude-code  → ANTHROPIC_API_KEY
  openai                   → OPENAI_API_KEY
  azure_openai             → AZURE_OPENAI_API_KEY
  github / github-copilot  → GITHUB_TOKEN
  databricks               → DATABRICKS_TOKEN
  ollama                   → (no key; set OLLAMA_HOST / OLLAMA_MODEL instead)
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# Choices exposed to the CLI for --backend option
BACKEND_CHOICES = [
    "auto",
    "anthropic",
    "github-copilot",   # GitHub Copilot Chat API (api.githubcopilot.com)
    "github",           # GitHub Models with Copilot fallback
    "azure_openai",
    "openai",
    "databricks",
    "ollama",
    "claude-code",      # claude CLI (explicit opt-in)
]

# Maps backend name → environment variable set by --api-key
_BACKEND_KEY_ENV: dict[str, str] = {
    "anthropic":      "ANTHROPIC_API_KEY",
    "claude-code":    "ANTHROPIC_API_KEY",
    "openai":         "OPENAI_API_KEY",
    "azure_openai":   "AZURE_OPENAI_API_KEY",
    "github":         "GITHUB_TOKEN",
    "github-copilot": "GITHUB_TOKEN",
    "databricks":     "DATABRICKS_TOKEN",
}


# ---------------------------------------------------------------------------
# Key injection helper (for --api-key CLI flag)
# ---------------------------------------------------------------------------

def apply_api_key(backend: str, api_key: str) -> None:
    """Set the appropriate environment variable for *backend* to *api_key*.

    Allows passing ``--api-key`` from the CLI without exporting env vars manually.
    Must be called before ``detect_backend()`` / ``call_llm()``.
    """
    env_var = _BACKEND_KEY_ENV.get(backend)
    if env_var:
        os.environ[env_var] = api_key
        log.debug("Set %s from --api-key for backend %s", env_var, backend)
    elif backend not in ("ollama", "auto", "none"):
        log.warning("--api-key provided for unknown backend %r — ignoring", backend)


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
        # "github" backend always tries Copilot first, falls back to Models
        return "github"

    if os.environ.get("DATABRICKS_HOST") and os.environ.get("DATABRICKS_TOKEN"):
        return "databricks"

    if _is_ollama_running():
        return "ollama"

    # claude-code: last resort in auto-detection; prefer --backend claude-code explicitly
    if _is_claude_code_available():
        return "claude-code"

    return "none"


def _is_claude_code_available() -> bool:
    """Return True if the `claude` CLI is installed and responds."""
    try:
        r = subprocess.run(
            ["claude", "--version"],
            capture_output=True, text=True, timeout=5,
        )
        return r.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False


def _is_ollama_running() -> bool:
    """Return True if Ollama is reachable at OLLAMA_HOST (default localhost:11434)."""
    host = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
    try:
        import httpx
        r = httpx.get(f"{host}/api/version", timeout=2)
        return r.status_code == 200
    except Exception:
        return False


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
    if backend == "claude-code":
        return _call_claude_code(messages, system, max_tokens)
    if backend == "azure_openai":
        return _call_openai(messages, system, max_tokens, azure=True)
    if backend == "openai":
        return _call_openai(messages, system, max_tokens, azure=False)
    if backend == "github-copilot":
        # Explicit Copilot-only path — no Models fallback
        result = _find_github_token_with_source()
        if not result:
            raise RuntimeError("github-copilot backend selected but no GitHub token found. "
                               "Run: gh auth login")
        token, _ = result
        return _call_github_copilot(token, messages, system, max_tokens)
    if backend == "github":
        return _call_github(messages, system, max_tokens)
    if backend == "databricks":
        return _call_databricks(messages, system, max_tokens)
    if backend == "ollama":
        return _call_ollama(messages, system, max_tokens)
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
    """Call GitHub Copilot API first; fall back to GitHub Models on failure.

    Any GitHub OAuth token (from env, gh CLI, or Copilot hosts.json) can be
    exchanged for a short-lived Copilot session token at api.github.com.
    This path uses api.githubcopilot.com which is NOT affected by corporate
    TLS inspection of *.azure.com endpoints.
    """
    result = _find_github_token_with_source()
    if not result:
        raise RuntimeError("GitHub backend selected but no token found. "
                           "Run: gh auth login")
    token, _source = result

    # Always try Copilot Chat API first (works for any gho_* OAuth token)
    try:
        return _call_github_copilot(token, messages, system, max_tokens)
    except Exception as copilot_exc:
        log.debug("Copilot API failed (%s), falling back to GitHub Models", copilot_exc)

    # Fallback: GitHub Models API (may be blocked on corporate networks)
    return _call_github_models(token, messages, system, max_tokens)


def _call_github_copilot(oauth_token: str, messages: list[dict], system: str, max_tokens: int) -> str:
    """Exchange an OAuth token for a Copilot session token, then call api.githubcopilot.com.

    Uses urllib for the token exchange (api.github.com is not affected by corporate
    TLS inspection). The subsequent chat call uses httpx with the same SSL-aware
    context as _call_github_models to handle corporate CA bundles.
    """
    import ssl
    import urllib.request
    import httpx
    from openai import OpenAI  # type: ignore[import-untyped]

    # Step 1: exchange OAuth token for short-lived Copilot session token
    # api.github.com is reachable even on corporate networks (verified)
    req = urllib.request.Request(
        "https://api.github.com/copilot_internal/v2/token",
        headers={
            "Authorization": f"token {oauth_token}",
            "Accept": "application/json",
            "User-Agent": "platograph/1.0",
            "Editor-Version": "platograph/1.0",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310
            session_data: dict[str, Any] = json.loads(resp.read())
    except Exception as exc:
        raise RuntimeError(
            f"Copilot session token exchange failed: {exc}. "
            "Ensure you have an active GitHub Copilot subscription and your "
            "token has the required scopes (gh auth login --scopes copilot)."
        ) from exc

    session_token: str = session_data.get("token", "")
    if not session_token:
        raise RuntimeError(
            "Copilot session token exchange returned no token. "
            f"Response keys: {list(session_data.keys())}"
        )

    # Step 2: call Copilot chat API (OpenAI-compatible) at api.githubcopilot.com
    # This domain is NOT affected by corporate *.azure.com TLS inspection.
    # Still apply the same SSL context for consistency with other HTTPS calls.
    ca_bundle = os.environ.get("REQUESTS_CA_BUNDLE") or os.environ.get("SSL_CERT_FILE")
    ssl_ctx: ssl.SSLContext | bool = True
    if ca_bundle:
        ssl_ctx = ssl.create_default_context(cafile=ca_bundle)
    else:
        try:
            import certifi  # type: ignore[import-untyped]
            ssl_ctx = ssl.create_default_context(cafile=certifi.where())
        except ImportError:
            pass

    http_client = httpx.Client(verify=ssl_ctx)
    client = OpenAI(
        base_url="https://api.githubcopilot.com",
        api_key=session_token,
        http_client=http_client,
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


def _call_claude_code(messages: list[dict], system: str, max_tokens: int) -> str:
    """Call the `claude` CLI in non-interactive print mode.

    Uses Claude Code's own stored authentication — no ANTHROPIC_API_KEY needed.
    Requires the Claude Code CLI to be installed: https://claude.ai/code

    Model is selected via CLAUDE_CODE_MODEL env var (default: claude-sonnet-4-5).
    Falls back to the anthropic SDK when ANTHROPIC_API_KEY is set.
    """
    if os.environ.get("ANTHROPIC_API_KEY"):
        return _call_anthropic(messages, system, max_tokens)

    model = os.environ.get("CLAUDE_CODE_MODEL", "claude-sonnet-4-5")

    # Build a single prompt string (system + conversation turns)
    prompt_parts = [f"<system>\n{system}\n</system>"]
    for msg in messages:
        role = msg["role"].capitalize()
        prompt_parts.append(f"{role}: {msg['content']}")
    full_prompt = "\n\n".join(prompt_parts)

    cmd = ["claude", "-p", full_prompt, "--model", model]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("claude CLI timed out after 120 s") from exc
    except FileNotFoundError as exc:
        raise RuntimeError(
            "claude CLI not found. Install Claude Code from https://claude.ai/code"
        ) from exc

    if result.returncode != 0:
        err = result.stderr.strip()[:300]
        raise RuntimeError(f"claude CLI exited with code {result.returncode}: {err}")

    return result.stdout.strip()


def _call_ollama(messages: list[dict], system: str, max_tokens: int) -> str:
    """Call a locally running Ollama instance (no API key required).

    Configure via environment variables:
      OLLAMA_HOST   — base URL (default: http://localhost:11434)
      OLLAMA_MODEL  — model name (default: llama3.2)
    """
    import httpx  # already available as transitive dep of openai

    host = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
    model = os.environ.get("OLLAMA_MODEL", "llama3.2")

    payload = {
        "model": model,
        "messages": [{"role": "system", "content": system}] + messages,
        "stream": False,
        "options": {"num_predict": max_tokens},
    }
    try:
        resp = httpx.post(f"{host}/api/chat", json=payload, timeout=120)
        resp.raise_for_status()
    except Exception as exc:
        raise RuntimeError(
            f"Ollama request failed ({host}). "
            "Is Ollama running? Start it with: ollama serve"
        ) from exc

    return resp.json()["message"]["content"]


def _call_databricks(messages: list[dict], system: str, max_tokens: int) -> str:
    from databricks.sdk import WorkspaceClient  # type: ignore[import-untyped]
    w = WorkspaceClient()
    endpoint = os.environ.get("DATABRICKS_LLM_ENDPOINT", "databricks-claude-sonnet-4")
    response = w.serving_endpoints.query(
        name=endpoint,
        messages=[{"role": "system", "content": system}] + messages,
    )
    return response.choices[0].message.content or ""
