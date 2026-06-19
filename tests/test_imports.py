from __future__ import annotations

import importlib


def test_core_modules_import_without_starting_tk_or_ollama() -> None:
    module_names = [
        "main",
        "desktop_gremlin.agent_loop",
        "desktop_gremlin.config",
        "desktop_gremlin.context_manager",
        "desktop_gremlin.history_store",
        "desktop_gremlin.models",
        "desktop_gremlin.ollama_client",
        "desktop_gremlin.tools.registry",
        "desktop_gremlin.tools.schemas",
    ]

    for module_name in module_names:
        importlib.import_module(module_name)
