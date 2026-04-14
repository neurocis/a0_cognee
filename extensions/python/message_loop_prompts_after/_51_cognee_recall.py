"""Cognee plugin - Recall enrichment extension.

Hook: message_loop_prompts_after (priority 51)
Queries Cognee with the current user message and conversation history,
then injects relevant knowledge graph results as extra context.
"""

from helpers.extension import Extension


class CogneeRecall(Extension):

    async def execute(self, **kwargs):
        # Guard: only run for agent0-level contexts
        if not hasattr(self.agent.context, "agent0"):
            return

        context = self.agent.context

        # Check if Cognee is enabled
        if not hasattr(context, "_cognee") or not context._cognee.get("enabled"):
            return

        try:
            from helpers.cognee_helper import (
                _get_plugin_config,
                search,
                format_search_results,
                _log,
            )

            config = _get_plugin_config(self.agent)

            # Check if recall is enabled
            if not config.get("cognee_recall_enabled", True):
                return

            debug = config.get("cognee_debug", False)
            loop_data = kwargs.get("loop_data", None)
            if loop_data is None:
                return

            # Build query from user message + recent history
            user_msg = ""
            try:
                if hasattr(loop_data, "user_message") and loop_data.user_message:
                    user_msg = str(loop_data.user_message)
            except Exception:
                pass

            if not user_msg:
                try:
                    history_text = self.agent.history.output_text(max_chars=1000)
                    user_msg = history_text[-800:] if history_text else ""
                except Exception:
                    return

            if not user_msg or not user_msg.strip():
                return

            # Build search query combining user message with context
            query = user_msg.strip()[:500]

            if debug:
                _log(context, f"Recall query: {query[:80]}...")

            # Search using configured search type
            search_type = config.get("cognee_search_type", "GRAPH_COMPLETION")
            result = await search(
                self.agent,
                query=query,
                search_type=search_type,
                context=context,
            )

            if "error" in result:
                if debug:
                    _log(context, f"Recall search error: {result['error']}", "warning")
                return

            # Format and inject results
            max_tokens = config.get("cognee_recall_max_tokens", 4096)
            formatted = format_search_results(result, max_tokens=max_tokens)

            if not formatted or not formatted.strip():
                return

            # Inject via prompt template into extras_persistent
            try:
                prompt_text = self.agent.read_prompt(
                    "cognee.recall.md", recall_results=formatted
                )
                if prompt_text and prompt_text.strip():
                    if hasattr(loop_data, "extras_persistent"):
                        loop_data.extras_persistent["cognee_memories"] = prompt_text
                    if debug:
                        _log(
                            context,
                            f"Injected {len(formatted)} chars of recall results",
                        )
            except Exception as e:
                if debug:
                    _log(context, f"Recall prompt error: {e}", "warning")

        except Exception as e:
            try:
                from helpers.cognee_helper import _log

                _log(context, f"Recall extension error: {e}", "error")
            except Exception:
                pass
