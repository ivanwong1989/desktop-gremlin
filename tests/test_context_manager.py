from __future__ import annotations

from desktop_gremlin.config import AppConfig
from desktop_gremlin.context_manager import estimate_message_tokens, trim_history
from desktop_gremlin.models import ChatMessage


def test_estimate_message_tokens_counts_images_without_io() -> None:
    messages = [
        ChatMessage(role="user", content="Look at this", images=["encoded-image"]),
        ChatMessage(role="assistant", content="I see it."),
    ]

    assert estimate_message_tokens(messages, "system") > 1120


def test_trim_history_keeps_recent_messages() -> None:
    config = AppConfig.defaults()
    config.max_history_tokens = 8
    config.min_recent_messages_to_keep = 2
    messages = [ChatMessage(role="user", content=f"message {index}" * 20) for index in range(6)]

    trimmed, removed = trim_history(messages, config)

    assert removed > 0
    assert len(trimmed) >= config.min_recent_messages_to_keep
    assert trimmed[-1].content == messages[-1].content
