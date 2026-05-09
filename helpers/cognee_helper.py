"""Cognee Knowledge Memory - Core Helper Module.

Centralizes all Cognee REST API interactions, configuration management,
client caching, and core operations (add, cognify, search).
"""

import time
import json
import asyncio
from typing import Any, Optional
from datetime import datetime, timedelta

try:
    import aiohttp

    AIOHTTP_AVAILABLE = True
except ImportError:
    AIOHTTP_AVAILABLE = False

# ---------------------------------------------------------------------------
# Defaults & caches
# ---------------------------------------------------------------------------

_DEFAULTS = {
    "cognee_base_url": "http://localhost:8000",
    "cognee_dataset_prefix": "a0",
    "cognee_retain_enabled": True,
    "cognee_recall_enabled": True,
    "cognee_context_enabled": True,
    "cognee_search_type": "GRAPH_COMPLETION",
    "cognee_recall_max_tokens": 4096,
    "cognee_auto_cognify": True,
    "cognee_cache_ttl": 120,
    "cognee_context_max_tokens": 500,
    "cognee_debug": False,
    # ── Verbose feedback mode (disabled by default) ─────────
    # When enabled, Cognee extensions emit structured events for
    # init/recall/retain/context operations so users can observe what
    # the plugin is doing, similar to FAISS-derived memory sections.
    "cognee_verbose": False,
    "cognee_verbose_include_dataset": True,
    "cognee_verbose_include_recall_count": True,
    "cognee_verbose_include_retain_status": True,
    "cognee_verbose_include_prompt_injection_status": True,
    "cognee_verbose_emit_to_prompt": True,
    "cognee_verbose_emit_to_log": True,
}

# Session cache: keyed by base_url
_session_cache: dict[str, "aiohttp.ClientSession"] = {}

# Context/search cache: keyed by (dataset, query) with TTL
_context_cache: dict[str, dict[str, Any]] = {}

# Cognify tracking: datasets that have been cognified this session
_cognified_datasets: set[str] = set()

# Bearer token cache: keyed by base_url, stores (token, expiry_time)
_bearer_tokens: dict[str, tuple[str, float]] = {}

# Auth lock: prevents concurrent auth attempts
_auth_locks: dict[str, asyncio.Lock] = {}

# Logging
# ---------------------------------------------------------------------------


def _log(context, message: str, log_type: str = "info"):
    """Unified logging via A0's context logger with print fallback."""
    try:
        if context and hasattr(context, "log"):
            context.log.log(type=log_type, content=f"[cognee] {message}")
        else:
            print(f"[cognee] [{log_type}] {message}")
    except Exception:
        print(f"[cognee] [{log_type}] {message}")


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


def _get_plugin_config(agent) -> dict:
    """Read plugin config merged with defaults."""
    try:
        from helpers import plugins

        config = plugins.get_plugin_config("a0-cognee", agent=agent) or {}
    except Exception:
        config = {}
    merged = dict(_DEFAULTS)
    for key, default_val in _DEFAULTS.items():
        val = config.get(key)
        if val is not None:
            # Coerce types to match defaults
            if isinstance(default_val, bool):
                if isinstance(val, str):
                    merged[key] = val.lower() in ("true", "1", "yes")
                else:
                    merged[key] = bool(val)
            elif isinstance(default_val, int):
                try:
                    merged[key] = int(val)
                except (ValueError, TypeError):
                    pass
            else:
                merged[key] = val
    return merged


def _get_secret(context, name: str, fallback: str = "") -> str:
    """Read a secret value from A0's secrets manager."""
    try:
        from helpers import secrets as sec_mod

        sm = sec_mod.get_secrets_manager(context)
        store = sm.load_secrets()
        return store.get(name, fallback)
    except Exception:
        return fallback


def get_base_url(agent) -> str:
    """Get the Cognee server base URL from plugin config (preferred) or secrets (fallback)."""
    config = _get_plugin_config(agent)
    url = config.get("cognee_base_url", "")
    if not url:
        # Fallback 1: check secrets for backward compatibility
        context = agent.context if hasattr(agent, "context") else None
        url = _get_secret(context, "COGNEE_BASE_URL", "")
    if not url:
        # Fallback 2: check environment variable
        import os
        url = os.environ.get("COGNEE_BASE_URL", "")
    return url.rstrip("/")


def get_api_key(agent) -> str:
    """Get the optional Cognee API key from secrets."""
    context = agent.context if hasattr(agent, "context") else None
    key = _get_secret(context, "COGNEE_API_KEY", "")
    if not key:
        import os

        key = os.environ.get("COGNEE_API_KEY", "")
    return key

def get_credentials(agent) -> tuple[str, str]:
    """Get Cognee username and password from secrets."""
    context = agent.context if hasattr(agent, "context") else None
    username = _get_secret(context, "COGNEE_USERNAME", "")
    password = _get_secret(context, "COGNEE_PASSWORD", "")
    if not username:
        import os
        username = os.environ.get("COGNEE_USERNAME", "")
    if not password:
        import os
        password = os.environ.get("COGNEE_PASSWORD", "")
    return username, password


async def _get_bearer_token(agent, base_url: str, force_refresh: bool = False) -> tuple[str, bool]:
    """Get or refresh Cognee bearer token using OAuth2 Password Grant.
    
    Returns:
        (token, success) where token is empty string if auth fails
    """
    if not force_refresh and base_url in _bearer_tokens:
        token, expiry = _bearer_tokens[base_url]
        if time.time() < expiry:
            return token, True
    
    # Get auth lock for this base_url
    if base_url not in _auth_locks:
        _auth_locks[base_url] = asyncio.Lock()
    
    async with _auth_locks[base_url]:
        # Double-check after acquiring lock
        if not force_refresh and base_url in _bearer_tokens:
            token, expiry = _bearer_tokens[base_url]
            if time.time() < expiry:
                return token, True
        
        username, password = get_credentials(agent)
        if not username or not password:
            return "", False
        
        session = await _get_session(base_url)
        url = f"{base_url}/api/v1/auth/login"
        
        try:
            req_timeout = aiohttp.ClientTimeout(total=10)
            
            # OAuth2 Password Grant: form-urlencoded
            data = {
                "username": username,
                "password": password,
            }
            
            async with session.post(
                url,
                data=data,
                timeout=req_timeout,
                headers={"Content-Type": "application/x-www-form-urlencoded"}
            ) as resp:
                status = resp.status
                body = await resp.json() if status < 400 else await resp.text()
                
                if status == 200 and isinstance(body, dict):
                    token = body.get("access_token") or body.get("token")
                    if token:
                        # Cache token with 30-minute expiry (default JWT lifetime)
                        _bearer_tokens[base_url] = (token, time.time() + 1800)
                        return token, True
                
                # Auth failed
                return "", False
        except Exception as e:
            return "", False


def is_configured(agent) -> bool:
    """Check if Cognee is available and configured."""
    if not AIOHTTP_AVAILABLE:
        return False
    return bool(get_base_url(agent))


def get_dataset_name(agent, context=None) -> str:
    """Derive the dataset name from config and active project.

    Resolution priority:
    1. Explicit `cognee_dataset_id` config override (matches Hindsight's
       `hindsight_bank_id` semantics).
    2. `<prefix>-<active-project-slug>` using the framework's project API
       (`helpers.projects.get_context_project_name`), which works correctly
       for both superior agents and subordinates spawned via
       `tools/call_subordinate.py` (they share the same `AgentContext`).
    3. `<prefix>-default` when no project is active.

    The `agent` argument is used to resolve plugin config against the
    *current* running agent's profile so per-profile overrides apply to
    subordinates — Option 2 fix mirrored from a0_hindsight.
    """
    config = _get_plugin_config(agent)

    # 1. Explicit override wins. Field is declared in hooks.py
    #    expected_types but was previously never read — fix.
    explicit = (config.get("cognee_dataset_id") or "").strip()
    if explicit:
        return explicit

    prefix = config.get("cognee_dataset_prefix", "a0") or "a0"

    # 2. Resolve project name via the framework's data API.
    #    AgentContext has NO `.project` attribute — only
    #    `context.data['project']` (a string), accessed via
    #    `context.get_data('project')`. The previous code path
    #    `agent.context.project.name/title` was always falsy and
    #    silently fell through to 'default' for every chat,
    #    which is the root cause of subordinates (and superiors)
    #    not knowing the right dataset.
    ctx = context
    if ctx is None and hasattr(agent, "context"):
        ctx = agent.context

    project_name = None
    if ctx is not None:
        try:
            from helpers.projects import get_context_project_name
            project_name = get_context_project_name(ctx)
        except Exception:
            project_name = None

    if not project_name:
        return f"{prefix}-default"

    # Sanitize: lowercase, replace non-alphanumerics with hyphens
    import re
    slug = re.sub(r"[^a-z0-9]+", "-", project_name.lower()).strip("-")
    return f"{prefix}-{slug}" if slug else f"{prefix}-default"


# ---------------------------------------------------------------------------
# HTTP Session Management
# ---------------------------------------------------------------------------


async def _get_headers(agent, base_url: str) -> dict:
    """Build HTTP headers for Cognee API requests with bearer token."""
    headers = {"Content-Type": "application/json"}
    api_key = get_api_key(agent)
    if api_key:
        headers["X-Api-Key"] = api_key
    
    # Check for OAuth2 access token from environment
    import os
    access_token = os.environ.get("COGNEE_ACCESS_TOKEN")
    if access_token:
        headers["Authorization"] = f"Bearer {access_token}"
    
    return headers


async def _get_session(base_url: str) -> "aiohttp.ClientSession":
    """Get or create a cached aiohttp session for a base URL."""
    if base_url in _session_cache:
        session = _session_cache[base_url]
        if not session.closed:
            return session
    session = aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=30)
    )
    _session_cache[base_url] = session
    return session


async def _api_request(
    agent,
    method: str,
    path: str,
    data: Optional[dict] = None,
    params: Optional[dict] = None,
    timeout: int = 30,
    retry_on_401: bool = True,
) -> dict:
    """Make an HTTP request to the Cognee API with automatic bearer token refresh on 401."""
    base_url = get_base_url(agent)
    if not base_url:
        return {"error": "COGNEE_BASE_URL not configured"}

    headers = await _get_headers(agent, base_url)
    url = f"{base_url}{path}"
    session = await _get_session(base_url)

    try:
        req_timeout = aiohttp.ClientTimeout(total=timeout)
        async with session.request(
            method, url, json=data, params=params, headers=headers, timeout=req_timeout
        ) as resp:
            status = resp.status
            try:
                body = await resp.json()
            except Exception:
                body = await resp.text()

            # On 401, refresh token and retry once
            if status == 401 and retry_on_401:
                # Force refresh the bearer token
                token, success = await _get_bearer_token(agent, base_url, force_refresh=True)
                if success and token:
                    # Update headers with new token
                    headers = await _get_headers(agent, base_url)
                    # Retry the request
                    async with session.request(
                        method, url, json=data, params=params, headers=headers, timeout=req_timeout
                    ) as retry_resp:
                        status = retry_resp.status
                        try:
                            body = await retry_resp.json()
                        except Exception:
                            body = await retry_resp.text()
                        
                        if status >= 400:
                            return {
                                "error": f"HTTP {status}",
                                "detail": body,
                                "url": url,
                            }
                        return {"status": status, "data": body}

            if status >= 400:
                return {
                    "error": f"HTTP {status}",
                    "detail": body,
                    "url": url,
                }
            return {"status": status, "data": body}
    except aiohttp.ClientError as e:
        return {"error": f"Connection error: {e}", "url": url}
    except Exception as e:
        return {"error": f"Request failed: {e}", "url": url}

# ---------------------------------------------------------------------------
# Core Operations
# ---------------------------------------------------------------------------


async def health_check(agent) -> dict:
    """Check Cognee server health."""
    return await _api_request(agent, "GET", "/health", timeout=5)


async def add_data(
    agent,
    content: str,
    dataset_name: Optional[str] = None,
    context=None,
) -> dict:
    """Add text data to Cognee for later cognification.

    Args:
        agent: The A0 agent instance.
        content: Text content to add.
        dataset_name: Optional dataset name override.
        context: A0 context for logging.
    """
    if not content or not content.strip():
        return {"error": "Empty content"}

    ds_name = dataset_name or get_dataset_name(agent)
    config = _get_plugin_config(agent)
    debug = config.get("cognee_debug", False)

    if debug and context:
        _log(context, f"Adding data to dataset '{ds_name}' ({len(content)} chars)")

    result = await _api_request(
        agent,
        "POST",
        "/api/v1/add",
        data={"data": content, "dataset_name": ds_name},
        timeout=30,
    )

    if "error" not in result and debug and context:
        _log(context, f"Data added successfully to '{ds_name}'")

    return result


async def cognify(
    agent,
    dataset_name: Optional[str] = None,
    context=None,
) -> dict:
    """Trigger cognification (knowledge graph building) on ingested data.

    Args:
        agent: The A0 agent instance.
        dataset_name: Optional dataset name to cognify.
        context: A0 context for logging.
    """
    ds_name = dataset_name or get_dataset_name(agent)
    config = _get_plugin_config(agent)
    debug = config.get("cognee_debug", False)

    if debug and context:
        _log(context, f"Cognifying dataset '{ds_name}'...")

    # Build request - cognify can take a while
    # Build request - cognify can take a while
    data = {"datasets": [ds_name]} if ds_name else {}
    result = await _api_request(
        agent,
        "POST",
        "/api/v1/cognify",
        data=data,
        timeout=120,  # Cognify can be slow
    )

    if "error" not in result:
        _cognified_datasets.add(ds_name)
        if debug and context:
            _log(context, f"Cognification complete for '{ds_name}'")

    return result


async def search(
    agent,
    query: str,
    search_type: Optional[str] = None,
    dataset_name: Optional[str] = None,
    context=None,
) -> dict:
    """Search Cognee knowledge graph.

    Args:
        agent: The A0 agent instance.
        query: Search query text.
        search_type: Override search type (default from config).
        dataset_name: Optional dataset filter.
        context: A0 context for logging.
    """
    if not query or not query.strip():
        return {"error": "Empty query"}

    config = _get_plugin_config(agent)
    s_type = search_type or config.get("cognee_search_type", "GRAPH_COMPLETION")
    debug = config.get("cognee_debug", False)

    # Check cache
    ds_name = dataset_name or get_dataset_name(agent)
    cache_key = f"{ds_name}:{s_type}:{query[:100]}"
    ttl = config.get("cognee_cache_ttl", 120)

    if cache_key in _context_cache:
        cached = _context_cache[cache_key]
        if time.time() - cached["ts"] < ttl:
            if debug and context:
                _log(context, f"Cache hit for search: {query[:50]}...")
            return cached["result"]

    if debug and context:
        _log(context, f"Searching ({s_type}): {query[:80]}...")

    payload = {
        "query_text": query,
        "search_type": s_type,
    }

    result = await _api_request(
        agent,
        "POST",
        "/api/search",
        data=payload,
        timeout=60,
    )

    # Cache successful results
    if "error" not in result:
        _context_cache[cache_key] = {"ts": time.time(), "result": result}
        if debug and context:
            _log(context, f"Search complete, caching result")

    return result


async def get_datasets(agent, context=None) -> dict:
    """List all datasets."""
    return await _api_request(agent, "GET", "/api/v1/datasets", timeout=10)


async def get_dataset_status(
    agent, dataset_id: str, context=None
) -> dict:
    """Get processing status of a dataset."""
    return await _api_request(
        agent, "GET", f"/api/v1/datasets/{dataset_id}/status", timeout=10
    )


async def delete_dataset(
    agent, dataset_id: str, context=None
) -> dict:
    """Delete a specific dataset."""
    return await _api_request(
        agent, "DELETE", f"/api/v1/datasets/{dataset_id}", timeout=15
    )


async def prune_data(agent, context=None) -> dict:
    """Prune all data (use with caution)."""
    return await _api_request(
        agent, "DELETE", "/api/v1/datasets", timeout=30
    )


# ---------------------------------------------------------------------------
# Convenience: Retain + Auto-Cognify
# ---------------------------------------------------------------------------


async def retain_and_cognify(
    agent,
    content: str,
    dataset_name: Optional[str] = None,
    context=None,
) -> dict:
    """Add data and optionally trigger cognification.

    This is the primary retain operation used by the monologue_end extension.
    """
    config = _get_plugin_config(agent)
    debug = config.get("cognee_debug", False)

    # Add data first
    add_result = await add_data(agent, content, dataset_name, context)
    if "error" in add_result:
        return add_result

    # Auto-cognify if enabled
    if config.get("cognee_auto_cognify", True):
        ds_name = dataset_name or get_dataset_name(agent)
        if debug and context:
            _log(context, f"Auto-cognifying '{ds_name}'...")
        cognify_result = await cognify(agent, ds_name, context)
        return {
            "add": add_result,
            "cognify": cognify_result,
        }

    return {"add": add_result, "cognify": "skipped (auto_cognify disabled)"}


# ---------------------------------------------------------------------------
# Format helpers
# ---------------------------------------------------------------------------


def format_search_results(result: dict, max_tokens: int = 4096) -> str:
    """Format Cognee search results into readable text for prompt injection."""
    if "error" in result:
        return ""

    data = result.get("data", result)

    # Handle various response shapes from Cognee
    if isinstance(data, str):
        return data[:max_tokens] if len(data) > max_tokens else data

    if isinstance(data, list):
        parts = []
        char_count = 0
        for item in data:
            if isinstance(item, dict):
                # Extract meaningful content from result items
                text = (
                    item.get("content")
                    or item.get("text")
                    or item.get("payload", {}).get("content", "")
                    or item.get("description", "")
                    or json.dumps(item, default=str)
                )
            else:
                text = str(item)

            if char_count + len(text) > max_tokens * 4:  # rough char estimate
                break
            parts.append(text)
            char_count += len(text)
        return "\n\n".join(parts)

    if isinstance(data, dict):
        # Single result or wrapped response
        content = (
            data.get("content")
            or data.get("text")
            or data.get("answer")
            or json.dumps(data, default=str)
        )
        return content[:max_tokens * 4] if len(content) > max_tokens * 4 else content

    return str(data)[:max_tokens * 4]


# ---------------------------------------------------------------------------
# Verbose Feedback Helpers
# ---------------------------------------------------------------------------
#
# Optional structured feedback for Cognee operations. Disabled by
# default; enabled via the cognee_verbose plugin config flag.
# Designed to give FAISS-style observability (recall counts, retain
# success, dataset names) without polluting normal conversations.


def _verbose_options(agent) -> dict:
    """Resolve the verbose-mode option set for the calling agent."""
    cfg = _get_plugin_config(agent)
    return {
        "enabled": bool(cfg.get("cognee_verbose", False)),
        "include_dataset": bool(cfg.get("cognee_verbose_include_dataset", True)),
        "include_recall_count": bool(cfg.get("cognee_verbose_include_recall_count", True)),
        "include_retain_status": bool(cfg.get("cognee_verbose_include_retain_status", True)),
        "include_prompt_injection_status": bool(
            cfg.get("cognee_verbose_include_prompt_injection_status", True)
        ),
        "emit_to_prompt": bool(cfg.get("cognee_verbose_emit_to_prompt", True)),
        "emit_to_log": bool(cfg.get("cognee_verbose_emit_to_log", True)),
    }


def is_verbose_enabled(agent=None, context=None) -> bool:
    """Return True when the verbose feedback mode is enabled for this agent."""
    return _verbose_options(agent)["enabled"]


def build_verbose_event(
    agent,
    event: str,
    payload: Optional[dict] = None,
    context=None,
) -> dict:
    """Construct a structured Cognee verbose event dict.

    Honors include_* options so each field is only present when the
    operator wants it. Always sets `source` and `event`.
    """
    payload = dict(payload or {})
    options = _verbose_options(agent)

    data: dict = {
        "source": "cognee",
        "event": event,
    }

    if options["include_dataset"]:
        dataset = payload.pop("dataset", None)
        if dataset is None and agent is not None:
            try:
                dataset = get_dataset_name(agent, context=context)
            except Exception:
                dataset = None
        if dataset:
            data["dataset"] = dataset
    else:
        payload.pop("dataset", None)

    if not options["include_recall_count"]:
        payload.pop("results_count", None)
    if not options["include_retain_status"]:
        payload.pop("items_count", None)
        # `success` is still useful for non-retain events; only strip on retain
        if event == "retain":
            payload.pop("success", None)
    if not options["include_prompt_injection_status"]:
        payload.pop("injected_into_prompt", None)

    data.update(payload)
    return data


def format_verbose_event(event: dict) -> str:
    """Render a verbose event dict as a `# Cognee Verbose` markdown block."""
    lines = ["# Cognee Verbose"]
    for key, value in event.items():
        lines.append(f"- {key}: {value}")
    return "\n".join(lines)


def emit_verbose_event(
    agent,
    event: str,
    payload: Optional[dict] = None,
    context=None,
) -> Optional[dict]:
    """Build, log, and return a verbose event when verbose mode is enabled.

    Returns the event dict on success, or None if verbose mode is disabled.
    Callers that want to inject the event into prompt text should check
    `should_emit_verbose_to_prompt(agent)` and call
    `format_verbose_event(...)` themselves.
    """
    options = _verbose_options(agent)
    if not options["enabled"]:
        return None

    verbose_event = build_verbose_event(agent, event, payload=payload, context=context)

    if options["emit_to_log"]:
        try:
            _log(context, f"verbose: {verbose_event}", "util")
        except Exception:
            try:
                print(f"[cognee verbose] {verbose_event}")
            except Exception:
                pass

    return verbose_event


def should_emit_verbose_to_prompt(agent=None) -> bool:
    """Convenience predicate for extensions deciding whether to inject prompt text."""
    options = _verbose_options(agent)
    return options["enabled"] and options["emit_to_prompt"]


# ---------------------------------------------------------------------------
# Cache & cleanup
# ---------------------------------------------------------------------------


def clear_cache():
    """Clear all caches."""
    _context_cache.clear()
    _cognified_datasets.clear()


async def cleanup():
    """Close all cached HTTP sessions."""
    for url, session in list(_session_cache.items()):
        if not session.closed:
            await session.close()
    _session_cache.clear()
    clear_cache()
