"""Agent tool - spawn a subagent for isolated tasks."""
from __future__ import annotations

import asyncio
from typing import Any, Callable

from ..tool import Tool, ToolResult


class AgentTool(Tool):
    """Spawn a subagent to handle a task in an isolated context."""

    name = "agent"
    description_text = (
        "Spawn a subagent to handle a complex task. The subagent gets its own "
        "conversation context and can use all available tools. Use this for "
        "tasks that require focused exploration without polluting the main context."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "task": {
                "type": "string",
                "description": "Description of the task for the subagent to perform.",
            },
            "prompt": {
                "type": "string",
                "description": "The detailed prompt/instructions for the subagent.",
            },
        },
        "required": ["prompt"],
    }

    def is_read_only(self, tool_input: dict[str, Any]) -> bool:
        return False

    def is_concurrency_safe(self, tool_input: dict[str, Any]) -> bool:
        return False

    def get_tool_use_summary(self, tool_input: dict[str, Any]) -> str | None:
        task = tool_input.get("task", tool_input.get("prompt", ""))
        return f"Agent: {task[:60]}..."

    async def call(
        self,
        tool_input: dict[str, Any],
        cwd: str,
        on_progress: Callable[[dict[str, Any]], None] | None = None,
    ) -> ToolResult:
        prompt = tool_input.get("prompt", "")
        task = tool_input.get("task", "")

        if not prompt:
            return ToolResult(output="Error: prompt is required", is_error=True)

        from ..services.subagent import run_subagent, SubagentConfig
        from ..state import get_state
        from ..tools.registry import create_tool_registry
        from ..services.skills import discover_skills, render_skill_prompt

        state = get_state()
        # Create a fresh tool registry for the subagent
        tool_registry = create_tool_registry()

        # Build system prompt with skills context
        system_prompt = (
            "You are a subagent for Noah Code. Complete the given task fully "
            "using the tools available. Be concise in your final report.\n\n"
            "IMPORTANT: Be persistent. If your first attempt doesn't work, "
            "try alternative approaches immediately — don't just report failure. "
            "Try at least 2-3 different strategies before giving up. "
            "Only return when you have a concrete result or have exhausted all options."
        )
        # Inject skills description so the subagent knows about available skills
        skills_desc = getattr(state, '_skills_description', '')
        if skills_desc:
            system_prompt += f"\n\n{skills_desc}"

        # Auto-load any skills mentioned in the prompt
        skills = discover_skills(cwd)
        skill_context = self._load_matching_skills(prompt + " " + task, skills)
        if skill_context:
            system_prompt += f"\n\n# Loaded Skill Instructions\n\n{skill_context}"

        config = SubagentConfig(
            system_prompt=system_prompt,
            max_iterations=10,
        )

        try:
            result = await asyncio.wait_for(
                run_subagent(
                    api_client=self._get_api_client(state),
                    tool_registry=tool_registry,
                    prompt=prompt,
                    config=config,
                    cwd=cwd,
                ),
                timeout=config.timeout or None,
            )
            output = result.text
            if result.error:
                output += f"\n\nError: {result.error}"
            return ToolResult(output=output)
        except asyncio.TimeoutError:
            return ToolResult(output=f"Subagent timed out after {config.timeout}s", is_error=True)
        except Exception as e:
            return ToolResult(output=f"Subagent error: {e}", is_error=True)

    @staticmethod
    def _get_api_client(state):
        from ..services.claude_api import NoahAPIClient
        return NoahAPIClient(
            model=state.model,
            base_url=state.base_url,
            api_key=state.api_key,
        )

    @staticmethod
    def _load_matching_skills(text: str, skills: list) -> str:
        """Auto-load skills whose name appears in the prompt text."""
        from ..services.skills import render_skill_prompt

        text_lower = text.lower()
        loaded = []
        for skill in skills:
            # Match skill name in prompt (e.g. "az-devops" matches "azure devops" or "az-devops")
            name_parts = skill.name.lower().replace("-", " ").split()
            # Check if all parts of the skill name appear in the text
            if all(part in text_lower for part in name_parts):
                rendered = render_skill_prompt(skill)
                loaded.append(f"## Skill: {skill.name}\n\n{rendered}")
        return "\n\n---\n\n".join(loaded) if loaded else ""
