from __future__ import annotations

import importlib


def test_core_modules_import_without_starting_tk_or_ollama() -> None:
    module_names = [
        "main",
        "desktop_gremlin.agent_loop",
        "desktop_gremlin.config",
        "desktop_gremlin.context_manager",
        "desktop_gremlin.game.game_controller",
        "desktop_gremlin.game.initial_state_generator",
        "desktop_gremlin.game.context_assembler",
        "desktop_gremlin.game.narrator_service",
        "desktop_gremlin.game.prompt_builder",
        "desktop_gremlin.game.state_applier",
        "desktop_gremlin.game.state_validator",
        "desktop_gremlin.game.turn_processor",
        "desktop_gremlin.history_store",
        "desktop_gremlin.models",
        "desktop_gremlin.ollama_client",
        "desktop_gremlin.persistence.json_repository",
        "desktop_gremlin.persistence.repository",
        "desktop_gremlin.tools.registry",
        "desktop_gremlin.tools.schemas",
        "desktop_gremlin.ui.choice_panel",
        "desktop_gremlin.ui.developer_inspector",
        "desktop_gremlin.ui.game_state_panel",
        "desktop_gremlin.ui.main_window",
    ]

    for module_name in module_names:
        importlib.import_module(module_name)
