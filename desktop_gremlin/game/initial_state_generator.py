from __future__ import annotations

import json
import re
from typing import Protocol

from pydantic import ValidationError

from .errors import InitialStateGenerationError
from .models import CampaignDefinition, InitialGameState
from .prompt_builder import build_initial_state_messages, build_initial_state_repair_messages


class InitialStateLLM(Protocol):
    def complete(self, messages: list[dict[str, str]]) -> str: ...


class OllamaInitialStateLLM:
    def __init__(self, ollama_client, config):
        self.ollama_client = ollama_client
        self.config = config

    def complete(self, messages: list[dict[str, str]]) -> str:
        from desktop_gremlin.models import ChatMessage

        prompt = "\n\n".join(f"{message['role'].upper()}:\n{message['content']}" for message in messages)
        chat_messages = [ChatMessage(role="user", content=prompt)]
        response = self.ollama_client.chat(chat_messages, stream=False, config=self.config)
        message = response.get("message")
        if not isinstance(message, dict):
            raise InitialStateGenerationError("Ollama response did not contain a message object.")
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise InitialStateGenerationError("Ollama returned no JSON content for the initial state.")
        return content


class InitialStateGenerator:
    def __init__(self, llm: InitialStateLLM):
        self.llm = llm

    def generate(self, campaign: CampaignDefinition) -> InitialGameState:
        first_response = self.llm.complete(build_initial_state_messages(campaign))
        first_result = self._parse_and_validate(first_response)
        if isinstance(first_result, InitialGameState):
            return first_result

        validation_errors = first_result
        repair_response = self.llm.complete(
            build_initial_state_repair_messages(campaign, first_response, validation_errors)
        )
        repair_result = self._parse_and_validate(repair_response)
        if isinstance(repair_result, InitialGameState):
            return repair_result

        raise InitialStateGenerationError(
            "Initial state generation failed after repair attempt.\n"
            f"First validation errors:\n{validation_errors}\n"
            f"Repair validation errors:\n{repair_result}"
        )

    def _parse_and_validate(self, response_text: str) -> InitialGameState | str:
        try:
            parsed = json.loads(extract_json_text(response_text))
        except json.JSONDecodeError as exc:
            return f"Invalid JSON: {exc}"

        try:
            return InitialGameState.model_validate(parsed)
        except ValidationError as exc:
            return str(exc)


def extract_json_text(response_text: str) -> str:
    text = response_text.strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", text, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        return fenced.group(1).strip()
    return text
