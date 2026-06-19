from __future__ import annotations

from dataclasses import asdict, dataclass, fields
import json
import logging
import os
from typing import Any, Literal


SETTINGS_FILE = "desktop_gremlin_settings.json"


DEFAULT_SYSTEM_PROMPT = (
    "You are Desktop Gremlin, a concise local desktop chat assistant. "
    "Be useful, direct, and answer clearly.\n\n"
    "You have access to a web_search tool when web access is enabled. "
    "Use web_search when the user's question depends on current, recent, changing, "
    "niche, or externally verifiable information. This includes current news, "
    "prices, schedules, laws, software versions, product specifications, sports "
    "results, current public office holders, recent company information, and facts "
    "that may have changed after your training data.\n\n"
    "Do not use web_search for casual conversation, rewriting, translation, "
    "summarizing user-provided text, creative writing, basic arithmetic, or stable "
    "facts you already know confidently.\n\n"
    "When web search is needed, generate a concise standalone search query. Include "
    "the relevant subject, date, version, country, location, or recency terms. Do "
    "not blindly copy the user's full message when a better search query can be "
    "formed.\n\n"
    "After receiving a web_search result, answer the user's original question using "
    "the retrieved information. Do not claim that the search succeeded when the "
    "tool result reports an error. Do not invent information that is absent from "
    "the tool result.\n\n"
    "You have access to a python_runner tool when Python tool access is enabled. "
    "Use python_runner for exact arithmetic, unit conversions, small algorithms, "
    "data parsing, validation, or other tasks where running simple Python improves "
    "correctness. The code must be self-contained, deterministic, and print the "
    "values needed for the final answer. Do not use python_runner for file access, "
    "network access, installing packages, subprocesses, secrets, or operating-system "
    "operations. After receiving a python_runner result, use the printed output or "
    "error to answer the user clearly."
)


@dataclass
class AppConfig:
    ollama_base_url: str = "http://localhost:11434"
    auto_start_ollama: bool = True
    ollama_startup_timeout_seconds: int = 20
    ollama_command: str = "ollama"
    preload_model_on_launch: bool = True
    model_keep_alive: str = "30m"
    stop_ollama_server_on_exit: bool = True
    model: str = "gemma4:26b-a4b-it-qat"
    request_timeout_seconds: int = 120
    log_file: str = "desktop_gremlin.log"
    env_file: str = ".env"
    history_dir: str = "history"

    system_prompt: str = DEFAULT_SYSTEM_PROMPT

    temperature: float = 0.9
    top_p: float = 0.95
    top_k: int = 64
    num_ctx: int = 32768
    num_predict: int = 4096
    seed: int = -1
    repeat_penalty: float = 1.0
    repeat_last_n: int = 256
    min_p: float | None = None
    think: bool = True

    max_history_tokens: int = 24000
    min_recent_messages_to_keep: int = 8
    max_tool_rounds: int = 3
    web_access_mode: Literal["automatic", "disabled"] = "automatic"
    python_access_mode: Literal["automatic", "disabled"] = "automatic"
    appearance_mode: Literal["light", "dark"] = "dark"

    tavily_timeout_seconds: int = 30
    tavily_max_results: int = 5
    max_search_query_length: int = 500
    max_result_content_chars: int = 2000
    max_total_tool_content_chars: int = 12000

    python_runner_timeout_seconds: int = 5
    max_python_code_chars: int = 8000
    max_python_output_chars: int = 12000

    def to_ollama_options(self) -> dict[str, Any]:
        options: dict[str, Any] = {
            "temperature": self.temperature,
            "top_p": self.top_p,
            "top_k": self.top_k,
            "num_ctx": self.num_ctx,
            "num_predict": self.num_predict,
            "seed": self.seed,
            "repeat_penalty": self.repeat_penalty,
            "repeat_last_n": self.repeat_last_n,
        }
        if self.min_p is not None:
            options["min_p"] = self.min_p
        return options

    @classmethod
    def load_from_json(cls, path: str) -> "AppConfig":
        config = cls()
        if not os.path.exists(path):
            return config

        try:
            with open(path, "r", encoding="utf-8") as settings_file:
                data = json.load(settings_file)
        except (OSError, json.JSONDecodeError) as exc:
            logging.warning("Could not load settings from %s: %s", path, exc)
            return config

        if not isinstance(data, dict):
            logging.warning("Ignoring invalid settings file shape: %s", type(data).__name__)
            return config

        valid_names = {field.name for field in fields(cls)}
        for key, value in data.items():
            if key in valid_names:
                setattr(config, key, value)
        return config

    def save_to_json(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as settings_file:
            json.dump(asdict(self), settings_file, indent=2)

    @classmethod
    def defaults(cls) -> "AppConfig":
        return cls()


def configure_logging(config: AppConfig) -> None:
    logging.basicConfig(
        filename=config.log_file,
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )


def load_env_file(env_file: str) -> None:
    env_path = os.path.join(os.getcwd(), env_file)
    if not os.path.exists(env_path):
        return

    try:
        with open(env_path, "r", encoding="utf-8") as file:
            for line in file:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = value
    except OSError as exc:
        logging.warning("Could not read %s: %s", env_file, exc)
