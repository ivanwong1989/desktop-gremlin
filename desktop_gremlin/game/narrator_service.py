from __future__ import annotations

import json
from typing import Protocol

from pydantic import ValidationError

from .errors import NarratorTurnError
from .initial_state_generator import extract_json_text
from .models import NarratorTurn


class NarratorLLM(Protocol):
    def complete(self, messages: list[dict[str, str]]) -> str: ...


class OllamaNarratorLLM:
    def __init__(self, ollama_client, config):
        self.ollama_client = ollama_client
        self.config = config

    def complete(self, messages: list[dict[str, str]]) -> str:
        from desktop_gremlin.models import ChatMessage

        prompt = "\n\n".join(f"{message['role'].upper()}:\n{message['content']}" for message in messages)
        response = self.ollama_client.chat([ChatMessage(role="user", content=prompt)], stream=False, config=self.config)
        message = response.get("message")
        if not isinstance(message, dict):
            raise NarratorTurnError("Ollama response did not contain a message object.")
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise NarratorTurnError("Ollama returned no JSON content for the narrator turn.")
        return content


class NarratorService:
    def __init__(self, llm: NarratorLLM):
        self.llm = llm

    def narrate(self, messages: list[dict[str, str]]) -> NarratorTurn:
        response_text = self.llm.complete(messages)
        try:
            parsed = json.loads(extract_json_text(response_text))
        except json.JSONDecodeError as exc:
            raise NarratorTurnError(f"Invalid narrator JSON: {exc}") from exc
        try:
            return NarratorTurn.model_validate(parsed)
        except ValidationError as exc:
            raise NarratorTurnError(f"Narrator turn failed validation: {exc}") from exc
