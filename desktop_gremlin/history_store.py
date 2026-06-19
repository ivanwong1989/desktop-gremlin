from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import json
import logging
import os
import re
from typing import Any
from uuid import uuid4

from .models import ChatMessage


INDEX_FILE = "index.json"
HISTORY_VERSION = 1


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def ensure_history_dir(history_dir: str) -> None:
    os.makedirs(history_dir, exist_ok=True)


def new_conversation_id() -> str:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return f"{stamp}-{uuid4().hex[:8]}"


def conversation_path(history_dir: str, conversation_id: str) -> str:
    safe_id = re.sub(r"[^A-Za-z0-9_.-]", "_", conversation_id)
    return os.path.join(history_dir, f"{safe_id}.json")


def create_empty_conversation() -> dict[str, Any]:
    now = utc_now_iso()
    return {
        "version": HISTORY_VERSION,
        "id": new_conversation_id(),
        "title": "New chat",
        "created_at": now,
        "updated_at": now,
        "messages": [],
    }


def list_conversations(history_dir: str) -> list[dict[str, Any]]:
    ensure_history_dir(history_dir)
    conversations = []
    try:
        names = os.listdir(history_dir)
    except OSError as exc:
        logging.warning("Could not list chat history from %s: %s", history_dir, exc)
        return []

    for name in names:
        if not name.endswith(".json") or name == INDEX_FILE:
            continue
        conversation = load_conversation(history_dir, name[:-5])
        if conversation is not None:
            conversations.append(conversation)

    conversations.sort(key=lambda item: str(item.get("updated_at") or ""), reverse=True)
    return conversations


def load_conversation(history_dir: str, conversation_id: str) -> dict[str, Any] | None:
    path = conversation_path(history_dir, conversation_id)
    try:
        with open(path, "r", encoding="utf-8") as file:
            data = json.load(file)
    except (OSError, json.JSONDecodeError) as exc:
        logging.warning("Could not load chat history from %s: %s", path, exc)
        return None

    if not isinstance(data, dict):
        logging.warning("Ignoring invalid chat history shape in %s", path)
        return None

    messages = messages_from_json(data.get("messages"))
    return {
        "version": data.get("version") or HISTORY_VERSION,
        "id": str(data.get("id") or conversation_id),
        "title": str(data.get("title") or title_from_messages(messages)),
        "created_at": str(data.get("created_at") or utc_now_iso()),
        "updated_at": str(data.get("updated_at") or utc_now_iso()),
        "messages": messages,
    }


def save_conversation(history_dir: str, conversation: dict[str, Any]) -> None:
    ensure_history_dir(history_dir)
    conversation["updated_at"] = utc_now_iso()
    messages = conversation.get("messages")
    if isinstance(messages, list):
        conversation["title"] = title_from_messages(messages)

    path = conversation_path(history_dir, str(conversation["id"]))
    data = {
        "version": HISTORY_VERSION,
        "id": conversation["id"],
        "title": conversation.get("title") or "New chat",
        "created_at": conversation.get("created_at") or conversation["updated_at"],
        "updated_at": conversation["updated_at"],
        "messages": messages_to_json(conversation.get("messages", [])),
    }
    with open(path, "w", encoding="utf-8") as file:
        json.dump(data, file, indent=2)


def messages_to_json(messages: list[ChatMessage]) -> list[dict[str, Any]]:
    return [asdict(message) for message in messages]


def messages_from_json(value: object) -> list[ChatMessage]:
    if not isinstance(value, list):
        return []

    messages = []
    for item in value:
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        if role not in {"system", "user", "assistant", "tool"}:
            continue
        content = item.get("content")
        images = item.get("images")
        tool_calls = item.get("tool_calls")
        tool_name = item.get("tool_name")
        messages.append(
            ChatMessage(
                role=role,
                content=str(content or ""),
                images=list(images) if isinstance(images, list) else [],
                tool_calls=list(tool_calls) if isinstance(tool_calls, list) else [],
                tool_name=tool_name if isinstance(tool_name, str) else None,
            )
        )
    return messages


def title_from_messages(messages: list[ChatMessage]) -> str:
    for message in messages:
        if message.role == "user" and message.content.strip():
            title = re.sub(r"\s+", " ", message.content).strip()
            return title[:60] if title else "New chat"
    return "New chat"
