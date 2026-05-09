"""Cognee plugin - Knowledge context injection extension.

Hook: system_prompt (priority 30)
Queries Cognee with recent conversation context and injects relevant
knowledge graph results into the system prompt.
"""

from helpers.extension import Extension


class CogneeContext(Extension):

    async def execute(self, **kwargs):
        # Guard: only run for agent0-level contexts
        if not hasattr(self.agent.context, "agent0"):
            return

        context = self.agent.context

        # Check if Cognee is enabled on this context
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

            # Check if context injection is enabled
            if not config.get("cognee_context_enabled", True):
                return

            debug = config.get("cognee_debug", False)

            # Build query from recent conversation history
            try:
                history_text = self.agent.history.output_text(max_chars=2000)
            except Exception:
                history_text = ""

            if not history_text or not history_text.strip():
                return

            # Use last portion as context query
            query = history_text[-1500:].strip()
            if not query:
                return

            if debug:
                _log(context, f"Context query: {query[:80]}...")

            # Search for relevant knowledge
            result = await search(
                self.agent,
                query=query,
                search_type="GRAPH_COMPLETION",
                context=context,
            )

            injected_into_prompt = False
            success = True
            error_msg = None

            if "error" in result:
                if debug:
                    _log(context, f"Context search error: {result['error']}", "warning")
                success = False
                error_msg = str(result.get("error"))
                formatted = ""
            else:
                # Format results
                max_tokens = config.get("cognee_context_max_tokens", 500)
                formatted = format_search_results(result, max_tokens=max_tokens)

            system_prompt = kwargs.get("system_prompt", [])

            if formatted and formatted.strip():
                # Inject into system prompt via template
                try:
                    prompt_text = self.agent.read_prompt(
                        "cognee.context.md", knowledge_context=formatted
                    )
                    if prompt_text and prompt_text.strip():
                        system_prompt.append(prompt_text)
                        injected_into_prompt = True
                        if debug:
                            _log(
                                context,
                                f"Injected {len(formatted)} chars of knowledge context",
                            )
                except Exception as e:
                    if debug:
                        _log(context, f"Prompt template error: {e}", "warning")

            # Emit verbose feedback event (no-op when verbose mode disabled)
            payload = {
                "result_present": bool(formatted and formatted.strip()),
                "injected_into_prompt": injected_into_prompt,
                "success": success,
            }
            if error_msg:
                payload["error"] = error_msg
            verbose_event = emit_verbose_event(
                self.agent,
                "context",
                payload,
                context=context,
            )
            if verbose_event and should_emit_verbose_to_prompt(self.agent):
                system_prompt.append(format_verbose_event(verbose_event))

        except Exception as e:
            try:
                from helpers.cognee_helper import _log

                _log(context, f"Context extension error: {e}", "error")
            except Exception:
                pass
