"""Cognee plugin - Initialization extension.

Hook: monologue_start (priority 20)
Initializes the Cognee client state on the context when a monologue begins.
"""

from helpers.extension import Extension


class CogneeInit(Extension):

    async def execute(self, **kwargs):
        # Guard: only run for agent0-level contexts
        if not hasattr(self.agent.context, "agent0"):
            return

        try:
            from helpers.cognee_helper import is_configured, get_dataset_name, _log

            context = self.agent.context

            if not is_configured(self.agent):
                context._cognee = {"enabled": False, "reason": "not configured"}
                return

            dataset_name = get_dataset_name(self.agent)
            context._cognee = {
                "enabled": True,
                "dataset": dataset_name,
                "retained_count": 0,
            }

            from helpers.cognee_helper import _get_plugin_config

            config = _get_plugin_config(self.agent)
            if config.get("cognee_debug", False):
                _log(
                    context,
                    f"Initialized: dataset='{dataset_name}', "
                    f"retain={config.get('cognee_retain_enabled')}, "
                    f"recall={config.get('cognee_recall_enabled')}, "
                    f"context={config.get('cognee_context_enabled')}",
                )

        except Exception as e:
            try:
                self.agent.context._cognee = {
                    "enabled": False,
                    "reason": str(e),
                }
            except Exception:
                pass
