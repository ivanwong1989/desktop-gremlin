from __future__ import annotations

import logging
import math

from .config import AppConfig
from .models import ChatMessage


IMAGE_TOKEN_ESTIMATE = 1120


def estimate_token_count(text: str) -> int:
    if not text:
        return 0
    return max(1, math.ceil(len(str(text)) / 4))


def estimate_message_tokens(messages: list[ChatMessage], system_prompt: str) -> int:
    total = estimate_token_count(system_prompt)
    for message in messages:
        total += estimate_token_count(message.role)
        total += estimate_token_count(message.content)
        total += estimate_token_count(message.tool_name or "")
        total += estimate_token_count(message.tool_calls)
        total += len(message.images) * IMAGE_TOKEN_ESTIMATE
    return total


def trim_history(messages: list[ChatMessage], config: AppConfig) -> tuple[list[ChatMessage], int]:
    trimmed = list(messages)
    removed = 0
    estimated = estimate_message_tokens(trimmed, config.system_prompt)

    while (
        estimated > config.max_history_tokens
        and len(trimmed) > config.min_recent_messages_to_keep
    ):
        trimmed.pop(0)
        removed += 1
        estimated = estimate_message_tokens(trimmed, config.system_prompt)

    if estimated > config.max_history_tokens:
        logging.warning(
            "Message estimate remains high after trimming: estimate=%s max_history=%s num_ctx=%s",
            estimated,
            config.max_history_tokens,
            config.num_ctx,
        )
    else:
        logging.info(
            "Message estimate before Ollama request: estimate=%s max_history=%s num_ctx=%s trimmed_messages=%s",
            estimated,
            config.max_history_tokens,
            config.num_ctx,
            removed,
        )

    return trimmed, removed
