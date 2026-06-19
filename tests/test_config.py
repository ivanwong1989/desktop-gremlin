from __future__ import annotations

import json

from desktop_gremlin.config import AppConfig


def test_default_config_exposes_ollama_options() -> None:
    config = AppConfig.defaults()

    assert config.ollama_base_url == "http://localhost:11434"
    assert config.web_access_mode in {"automatic", "disabled"}
    assert config.python_access_mode in {"automatic", "disabled"}
    assert config.to_ollama_options()["num_ctx"] == config.num_ctx
    assert "temperature" in config.to_ollama_options()


def test_config_load_ignores_unknown_keys(tmp_path) -> None:
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps(
            {
                "model": "test-model",
                "num_ctx": 1234,
                "unknown_future_key": "ignored",
            }
        ),
        encoding="utf-8",
    )

    config = AppConfig.load_from_json(str(path))

    assert config.model == "test-model"
    assert config.num_ctx == 1234
    assert not hasattr(config, "unknown_future_key")


def test_config_save_round_trip(tmp_path) -> None:
    path = tmp_path / "settings.json"
    config = AppConfig.defaults()
    config.model = "round-trip-model"
    config.web_access_mode = "disabled"

    config.save_to_json(str(path))
    loaded = AppConfig.load_from_json(str(path))

    assert loaded.model == "round-trip-model"
    assert loaded.web_access_mode == "disabled"
