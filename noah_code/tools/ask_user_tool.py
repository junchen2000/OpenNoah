"""Ask User Question tool - interactively ask the user a question."""
from __future__ import annotations

from typing import Any, Callable

from ..tool import Tool, ToolResult


class AskUserQuestionTool(Tool):
    """Ask the user a question and wait for their response."""

    name = "ask_user"
    description_text = (
        "Ask the user a question and wait for a response. Use this when you need "
        "clarification or confirmation before proceeding with a task."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "question": {
                "type": "string",
                "description": "The question to ask the user.",
            },
        },
        "required": ["question"],
    }

    def is_read_only(self, tool_input: dict[str, Any]) -> bool:
        return True

    def requires_user_interaction(self) -> bool:
        return True

    def get_tool_use_summary(self, tool_input: dict[str, Any]) -> str | None:
        q = tool_input.get("question", "")
        return f"Ask: {q[:60]}"

    async def call(
        self,
        tool_input: dict[str, Any],
        cwd: str,
        on_progress: Callable[[dict[str, Any]], None] | None = None,
    ) -> ToolResult:
        question = tool_input.get("question", "")
        if not question:
            return ToolResult(output="Error: question is required", is_error=True)

        # In interactive mode, the REPL will handle displaying the question
        # and collecting the answer. This tool returns the question for display.
        # The actual user input collection happens at the REPL level.
        return ToolResult(
            output=f"[Question for user]: {question}",
            metadata={"requires_input": True, "question": question},
        )
