import subprocess
import sys
from pathlib import Path


def install():
    """Install plugin dependencies from requirements.txt."""
    req_file = Path(__file__).parent / "requirements.txt"
    if req_file.exists():
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "-r", str(req_file), "-q"]
        )


def pre_update():
    """Re-install dependencies before plugin update."""


def config_changed(config: dict, agent=None, context=None, **kwargs) -> dict:
    """Handle configuration changes from the WebUI.

    This hook is called when the user saves settings from the WebUI panel.
    It validates the configuration and persists it using Agent Zero's plugin config manager.

    Args:
        config: Dictionary of configuration key-value pairs from the WebUI
        agent: The agent instance making the configuration change
        context: The agent context (if available)
        **kwargs: Additional arguments from the framework

    Returns:
        Dictionary with 'success' boolean and optional 'error' message
    """
    try:
        from helpers import plugins

        # Validate configuration
        validated_config = {}

        # Type validation and coercion
        expected_types = {
            "cognee_base_url": str,
            "cognee_dataset_prefix": str,
            "cognee_retain_enabled": bool,
            "cognee_recall_enabled": bool,
            "cognee_context_enabled": bool,
            "cognee_search_type": str,
            "cognee_recall_max_tokens": int,
            "cognee_auto_cognify": bool,
            "cognee_cache_ttl": int,
            "cognee_context_max_tokens": int,
            "cognee_debug": bool,
        }

        for key, expected_type in expected_types.items():
            if key not in config:
                continue

            val = config[key]

            # Type coercion
            if expected_type == bool:
                if isinstance(val, bool):
                    validated_config[key] = val
                elif isinstance(val, str):
                    validated_config[key] = val.lower() in ("true", "1", "yes")
                else:
                    validated_config[key] = bool(val)
            elif expected_type == int:
                try:
                    validated_config[key] = int(val)
                except (ValueError, TypeError):
                    return {
                        "success": False,
                        "error": f"Invalid integer value for {key}: {val}",
                    }
            elif expected_type == str:
                validated_config[key] = str(val).strip() if val else ""

        # Validate specific fields
        if "cognee_base_url" in validated_config:
            url = validated_config["cognee_base_url"]
            if url and not (url.startswith("http://") or url.startswith("https://")):
                return {
                    "success": False,
                    "error": "Cognee Base URL must start with http:// or https://",
                }

        if "cognee_recall_max_tokens" in validated_config:
            tokens = validated_config["cognee_recall_max_tokens"]
            if tokens < 256 or tokens > 16384:
                return {
                    "success": False,
                    "error": "Recall Max Tokens must be between 256 and 16384",
                }

        if "cognee_context_max_tokens" in validated_config:
            tokens = validated_config["cognee_context_max_tokens"]
            if tokens < 100 or tokens > 4096:
                return {
                    "success": False,
                    "error": "Context Max Tokens must be between 100 and 4096",
                }

        if "cognee_cache_ttl" in validated_config:
            ttl = validated_config["cognee_cache_ttl"]
            if ttl < 0 or ttl > 3600:
                return {
                    "success": False,
                    "error": "Cache TTL must be between 0 and 3600 seconds",
                }

        # Persist configuration using Agent Zero's plugin config manager
        try:
            plugins.set_plugin_config(
                "a0_cognee", validated_config, agent=agent, context=context
            )
            return {"success": True, "message": "Configuration saved successfully"}
        except Exception as e:
            return {"success": False, "error": f"Failed to save configuration: {str(e)}"}

    except Exception as e:
        return {"success": False, "error": f"Configuration error: {str(e)}"}
