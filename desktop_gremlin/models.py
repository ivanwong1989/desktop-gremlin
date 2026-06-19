from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass
class ChatMessage:
    role: Literal["system", "user", "assistant", "tool"]
    content: str
    images: list[str] = field(default_factory=list)
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    tool_name: str | None = None


@dataclass
class StreamDelta:
    content: str = ""
    thinking: str = ""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    done: bool = False
    prompt_eval_count: int | None = None
    eval_count: int | None = None
