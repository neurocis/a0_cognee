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
                emit_verbose_event,
                format_verbose_event,
                should_emit_verbose_to_prompt,
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
                # Emit a verbose event so the user sees the failure when verbose enabled
                emit_verbose_event(
                    self.agent,
                    "recall",
                    {
                        "results_count": 0,
                        "injected_into_prompt": False,
                        "success": False,
                        "error": str(result.get("error")),
                    },
                    context=context,
                )
                return

            # Format and inject results
            max_tokens = config.get("cognee_recall_max_tokens", 4096)
            formatted = format_search_results(result, max_tokens=max_tokens)

            # Approximate result count: count non-empty lines, fallback to 1
            results_count = 0
            if formatted and formatted.strip():
                lines = [ln for ln in formatted.splitlines() if ln.strip()]
                results_count = len(lines) if lines else 1

            injected_into_prompt = False

            if formatted and formatted.strip():
                # Inject via prompt template into extras_persistent
                try:
                    prompt_text = self.agent.read_prompt(
                        "cognee.recall.md", recall_results=formatted
                    )
                    if prompt_text and prompt_text.strip():
                        if hasattr(loop_data, "extras_persistent"):
                            loop_data.extras_persistent["cognee_memories"] = prompt_text
                            injected_into_prompt = True
                        if debug:
                            _log(
                                context,
                                f"Injected {len(formatted)} chars of recall results",
                            )
                except Exception as e:
                    if debug:
                        _log(context, f"Recall prompt error: {e}", "warning")
            else:
                # Clear stale memories when recall finds nothing
                if hasattr(loop_data, "extras_persistent"):
                    loop_data.extras_persistent.pop("cognee_memories", None)

            # Emit verbose feedback event (no-op when verbose mode disabled)
            verbose_event = emit_verbose_event(
                self.agent,
                "recall",
                {
                    "results_count": results_count,
                    "injected_into_prompt": injected_into_prompt,
                    "success": True,
                },
                context=context,
            )
            if verbose_event and should_emit_verbose_to_prompt(self.agent):
                if hasattr(loop_data, "extras_persistent"):
                    loop_data.extras_persistent["cognee_verbose"] = (
                        format_verbose_event(verbose_event)
                    )
            else:
                if hasattr(loop_data, "extras_persistent"):
                    loop_data.extras_persistent.pop("cognee_verbose", None)

        except Exception as e:
            try:
                from helpers.cognee_helper import _log

                _log(context, f"Recall extension error: {e}", "error")
            except Exception:
                pass
