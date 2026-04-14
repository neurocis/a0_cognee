"""Cognee Knowledge Memory - Core Helper Module.

Centralizes all Cognee REST API interactions, configuration management,
client caching, and core operations (add, cognify, search).
"""

import time
import json
from typing import Any, Optional

try:
    import aiohttp

    AIOHTTP_AVAILABLE = True
except ImportError:
    AIOHTTP_AVAILABLE = False

# ---------------------------------------------------------------------------
# Defaults & caches
# ---------------------------------------------------------------------------

_DEFAULTS = {
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
}

# Session cache: keyed by base_url
_session_cache: dict[str, "aiohttp.ClientSession"] = {}

# Context/search cache: keyed by (dataset, query) with TTL
_context_cache: dict[str, dict[str, Any]] = {}

# Cognify tracking: datasets that have been cognified this session
_cognified_datasets: set[str] = set()


# ---------------------------------------------------------------------------
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
    """Get the Cognee server base URL from secrets."""
    context = agent.context if hasattr(agent, "context") else None
    url = _get_secret(context, "COGNEE_BASE_URL", "")
    if not url:
        # Fallback: check environment variable
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


def is_configured(agent) -> bool:
    """Check if Cognee is available and configured."""
    if not AIOHTTP_AVAILABLE:
        return False
    return bool(get_base_url(agent))


def get_dataset_name(agent) -> str:
    """Derive the dataset name from config prefix and project."""
    config = _get_plugin_config(agent)
    prefix = config.get("cognee_dataset_prefix", "a0")

    # Get project name
    project_name = "default"
    try:
        if hasattr(agent, "context") and hasattr(agent.context, "project"):
            proj = agent.context.project
            if proj and hasattr(proj, "name") and proj.name:
                project_name = proj.name
            elif proj and hasattr(proj, "title") and proj.title:
                project_name = proj.title
    except Exception:
        pass

    # Sanitize: lowercase, replace spaces/special chars with hyphens
    import re

    project_name = re.sub(r"[^a-z0-9]+", "-", project_name.lower()).strip("-")
    return f"{prefix}-{project_name}" if project_name else prefix


# ---------------------------------------------------------------------------
# HTTP Session Management
# ---------------------------------------------------------------------------


def _get_headers(agent) -> dict:
    """Build HTTP headers for Cognee API requests."""
    headers = {"Content-Type": "application/json"}
    api_key = get_api_key(agent)
    if api_key:
        headers["X-Api-Key"] = api_key
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
) -> dict:
    """Make an HTTP request to the Cognee API."""
    base_url = get_base_url(agent)
    if not base_url:
        return {"error": "COGNEE_BASE_URL not configured"}

    headers = _get_headers(agent)
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
    return await _api_request(agent, "GET", "/api/health", timeout=5)


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
        "/api/add",
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
    data = {"datasets": [ds_name]} if ds_name else {}
    result = await _api_request(
        agent,
        "POST",
        "/api/cognify",
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
