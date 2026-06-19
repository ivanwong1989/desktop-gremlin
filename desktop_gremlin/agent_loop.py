from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Callable

from .config import AppConfig
from .context_manager import trim_history
from .models import ChatMessage
from .ollama_client import OllamaClient
from .tools.registry import execute_tool_call
from .tools.schemas import PYTHON_RUNNER_TOOL, WEB_SEARCH_TOOL


StatusCallback = Callable[[str], None]
DeltaCallback = Callable[[str], None]


@dataclass
class AgentTurnResult:
    answer: str
    thinking_text: str
    prompt_tokens: int | None
    output_tokens: int | None
    messages: list[ChatMessage]
    removed_messages: int


def run_chat_turn(
    messages: list[ChatMessage],
    config: AppConfig,
    ollama_client: OllamaClient,
    web_access_mode: str,
    python_access_mode: str,
    status_callback: StatusCallback | None = None,
    content_callback: DeltaCallback | None = None,
    thinking_callback: DeltaCallback | None = None,
) -> AgentTurnResult:
    tools = build_tools(web_access_mode, python_access_mode)
    working_messages, removed = trim_history(messages, config)
    thinking_parts: list[str] = []
    prompt_tokens = None
    output_tokens = None

    for round_index in range(config.max_tool_rounds + 1):
        if round_index == 0:
            update_status(status_callback, "Thinking...")
        else:
            update_status(status_callback, "Tool completed. Generating response...")
            logging.info("[Ollama] Requesting final answer")

        response_json = stream_chat_response(
            ollama_client,
            working_messages,
            tools=tools,
            config=config,
            content_callback=content_callback,
            thinking_callback=thinking_callback,
        )
        assistant_message = response_json.get("message")
        if not isinstance(assistant_message, dict):
            raise RuntimeError("Ollama response does not contain a valid message.")

        assistant_chat_message = chat_message_from_ollama(assistant_message)
        working_messages.append(assistant_chat_message)

        thinking = assistant_message.get("thinking") or assistant_message.get("thought") or ""
        if thinking:
            thinking_parts.append(str(thinking))

        prompt_tokens = response_json.get("prompt_eval_count", prompt_tokens)
        output_tokens = response_json.get("eval_count", output_tokens)

        tool_calls = assistant_message.get("tool_calls") or []
        if not tool_calls:
            logging.info("[Ollama] Final answer received")
            return AgentTurnResult(
                answer=str(assistant_message.get("content") or ""),
                thinking_text="".join(thinking_parts),
                prompt_tokens=prompt_tokens,
                output_tokens=output_tokens,
                messages=working_messages,
                removed_messages=removed,
            )

        if not isinstance(tool_calls, list):
            tool_calls = [{"function": {"name": "unknown_tool", "arguments": {}}}]

        logging.info("[Ollama] Assistant requested %s tool call(s)", len(tool_calls))
        for tool_call in tool_calls:
            tool_name = extract_tool_name(tool_call)
            logging.info("[Tool] Name: %s", tool_name)
            update_status(status_callback, status_for_tool_call(tool_call))

            tool_message = execute_tool_call(tool_call, config)
            working_messages.append(tool_message)
            logging.info("[Ollama] Tool result appended to conversation")

    answer = "Maximum tool-call rounds reached."
    working_messages.append(ChatMessage(role="assistant", content=answer))
    return AgentTurnResult(
        answer=answer,
        thinking_text="".join(thinking_parts),
        prompt_tokens=prompt_tokens,
        output_tokens=output_tokens,
        messages=working_messages,
        removed_messages=removed,
    )


def build_tools(web_access_mode: str, python_access_mode: str) -> list[dict] | None:
    tools = []
    if web_access_mode == "automatic":
        tools.append(WEB_SEARCH_TOOL)
    if python_access_mode == "automatic":
        tools.append(PYTHON_RUNNER_TOOL)
    return tools or None


def stream_chat_response(
    ollama_client: OllamaClient,
    messages: list[ChatMessage],
    tools: list[dict] | None,
    config: AppConfig,
    content_callback: DeltaCallback | None = None,
    thinking_callback: DeltaCallback | None = None,
) -> dict:
    content_parts: list[str] = []
    thinking_parts: list[str] = []
    tool_calls: list[dict] = []
    prompt_tokens = None
    output_tokens = None

    for delta in ollama_client.stream_chat(messages, tools=tools, config=config):
        if delta.content:
            content_parts.append(delta.content)
            if content_callback is not None:
                content_callback(delta.content)
        if delta.thinking:
            thinking_parts.append(delta.thinking)
            if thinking_callback is not None:
                thinking_callback(delta.thinking)
        if delta.tool_calls:
            tool_calls = delta.tool_calls
        if delta.prompt_eval_count is not None:
            prompt_tokens = delta.prompt_eval_count
        if delta.eval_count is not None:
            output_tokens = delta.eval_count

    message = {
        "role": "assistant",
        "content": "".join(content_parts),
    }
    thinking_text = "".join(thinking_parts)
    if thinking_text:
        message["thinking"] = thinking_text
    if tool_calls:
        message["tool_calls"] = tool_calls

    return {
        "message": message,
        "prompt_eval_count": prompt_tokens,
        "eval_count": output_tokens,
    }


def chat_message_from_ollama(message: dict) -> ChatMessage:
    role = message.get("role") or "assistant"
    if role not in {"assistant", "user", "system", "tool"}:
        role = "assistant"

    tool_calls = message.get("tool_calls") or []
    if not isinstance(tool_calls, list):
        tool_calls = []

    content = message.get("content") or ""
    return ChatMessage(
        role=role,
        content=str(content),
        tool_calls=tool_calls,
        tool_name=message.get("tool_name") if isinstance(message.get("tool_name"), str) else None,
    )


def extract_tool_name(tool_call: object) -> str:
    if not isinstance(tool_call, dict):
        return "unknown_tool"
    function_data = tool_call.get("function")
    if not isinstance(function_data, dict):
        return "unknown_tool"
    name = function_data.get("name")
    return name if isinstance(name, str) and name else "unknown_tool"


def status_for_tool_call(tool_call: object) -> str:
    tool_name = extract_tool_name(tool_call)
    if tool_name == "web_search":
        query = extract_argument(tool_call, "query")
        if query:
            logging.info("[Tool] Query: %s", query)
            return f"Web search requested: {query}"
        return "Searching the web..."
    if tool_name == "python_runner":
        code = extract_argument(tool_call, "code")
        line_count = len(code.splitlines()) if code else 0
        return f"Running Python code ({line_count} lines)..."
    return f"Running tool: {tool_name}"


def extract_query(tool_call: object) -> str:
    return extract_argument(tool_call, "query")


def extract_argument(tool_call: object, key: str) -> str:
    if not isinstance(tool_call, dict):
        return ""
    function_data = tool_call.get("function")
    if not isinstance(function_data, dict):
        return ""
    arguments = function_data.get("arguments")
    if not isinstance(arguments, dict):
        return ""
    value = arguments.get(key)
    return value.strip() if isinstance(value, str) else ""


def update_status(callback: StatusCallback | None, message: str) -> None:
    if callback is not None:
        callback(message)
