from __future__ import annotations

import json
from typing import Any, Callable

from ..config import AppConfig
from ..models import ChatMessage
from .python_runner import python_runner
from .web_search import web_search


ToolFunction = Callable[..., dict[str, Any]]


TOOL_REGISTRY: dict[str, ToolFunction] = {
    "python_runner": python_runner,
    "web_search": web_search,
}


def execute_tool_call(tool_call: dict[str, Any], config: AppConfig) -> ChatMessage:
    tool_name = "unknown_tool"

    try:
        if not isinstance(tool_call, dict):
            raise ValueError("Tool call must be an object.")

        function_data = tool_call.get("function")
        if not isinstance(function_data, dict):
            raise ValueError("Tool call is missing function data.")

        raw_tool_name = function_data.get("name")
        if not isinstance(raw_tool_name, str) or not raw_tool_name.strip():
            raise ValueError("Tool name must be a non-empty string.")

        tool_name = raw_tool_name.strip()
        arguments = function_data.get("arguments", {})
        if not isinstance(arguments, dict):
            raise ValueError("Tool arguments must be an object.")

        tool_function = TOOL_REGISTRY.get(tool_name)
        if tool_function is None:
            result = {
                "ok": False,
                "error": f"Unknown tool requested: {tool_name}",
                "results": [],
            }
        elif tool_name == "web_search":
            query = arguments.get("query")
            if not isinstance(query, str):
                result = {
                    "ok": False,
                    "error": "web_search query must be a string.",
                    "results": [],
                }
            else:
                result = tool_function(query=query, config=config)
        elif tool_name == "python_runner":
            code = arguments.get("code")
            if not isinstance(code, str):
                result = {
                    "ok": False,
                    "error": "python_runner code must be a string.",
                    "stdout": "",
                    "stderr": "",
                    "exit_code": None,
                }
            else:
                result = tool_function(code=code, config=config)
        else:
            result = tool_function(**arguments)
    except Exception as exc:
        result = {
            "ok": False,
            "error": str(exc),
            "results": [],
        }

    return ChatMessage(
        role="tool",
        tool_name=tool_name,
        content=json.dumps(result, ensure_ascii=False),
    )
