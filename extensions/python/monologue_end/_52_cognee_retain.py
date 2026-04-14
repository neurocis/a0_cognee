"""Cognee plugin - Knowledge retention extension.

Hook: monologue_end (priority 52)
Extracts key knowledge from the conversation using a utility LLM,
then stores it in Cognee via the REST API. Runs in a background thread
to avoid blocking the agent response.
"""

from helpers.extension import Extension


class CogneeRetain(Extension):

    async def execute(self, **kwargs):
        # Guard: only run for agent0-level contexts
        if not hasattr(self.agent.context, "agent0"):
            return

        context = self.agent.context

        # Check if Cognee is enabled
        if not hasattr(context, "_cognee") or not context._cognee.get("enabled"):
            return

        try:
            from helpers.cognee_helper import _get_plugin_config, _log

            config = _get_plugin_config(self.agent)

            # Check if retain is enabled
            if not config.get("cognee_retain_enabled", True):
                return

            debug = config.get("cognee_debug", False)

            # Get conversation history
            try:
                history_text = self.agent.history.output_text(max_chars=4000)
            except Exception:
                history_text = ""

            if not history_text or not history_text.strip():
                return

            if debug:
                _log(context, f"Extracting knowledge from {len(history_text)} chars of conversation")

            # Run retention in background to avoid blocking
            from helpers.defer import DeferredTask, THREAD_BACKGROUND

            DeferredTask(
                self._retain_to_cognee,
                self.agent,
                context,
                history_text,
                config,
                thread_group=THREAD_BACKGROUND,
            )

        except Exception as e:
            try:
                from helpers.cognee_helper import _log

                _log(context, f"Retain extension error: {e}", "error")
            except Exception:
                pass

    @staticmethod
    async def _retain_to_cognee(agent, context, history_text, config):
        """Background task: extract knowledge and store in Cognee."""
        try:
            from helpers.cognee_helper import retain_and_cognify, _log

            debug = config.get("cognee_debug", False)

            # Use utility LLM to extract key knowledge from conversation
            try:
                system_prompt = agent.read_prompt("cognee.retain_extract.sys.md")
                extraction_messages = agent.concat_messages(
                    system_prompt,
                    history_text,
                )
                extraction_result = await agent.call_utility_model(
                    messages=extraction_messages
                )

                if not extraction_result or not extraction_result.strip():
                    if debug:
                        _log(context, "No knowledge extracted from conversation")
                    return

                # Parse extracted knowledge - expect JSON array of facts
                try:
                    from helpers.dirty_json import DirtyJson

                    facts = DirtyJson.parse_string(extraction_result)
                    if isinstance(facts, list):
                        knowledge_text = "\n\n".join(
                            str(f) for f in facts if f and str(f).strip()
                        )
                    else:
                        knowledge_text = str(facts)
                except Exception:
                    # If JSON parsing fails, use raw extraction
                    knowledge_text = extraction_result

            except Exception as e:
                if debug:
                    _log(context, f"LLM extraction failed, using raw history: {e}", "warning")
                # Fallback: store a condensed version of the conversation
                knowledge_text = history_text[-2000:]

            if not knowledge_text or not knowledge_text.strip():
                return

            # Store in Cognee
            result = await retain_and_cognify(
                agent,
                content=knowledge_text,
                context=context,
            )

            if "error" in result:
                if debug:
                    _log(context, f"Retain failed: {result.get('error')}", "warning")
            else:
                # Update retain counter
                if hasattr(context, "_cognee"):
                    context._cognee["retained_count"] = (
                        context._cognee.get("retained_count", 0) + 1
                    )
                if debug:
                    _log(
                        context,
                        f"Retained {len(knowledge_text)} chars of knowledge",
                    )

        except Exception as e:
            try:
                from helpers.cognee_helper import _log

                _log(context, f"Background retain error: {e}", "error")
            except Exception:
                pass
