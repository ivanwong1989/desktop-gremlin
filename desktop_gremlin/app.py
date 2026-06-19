from __future__ import annotations

import tkinter as tk

from .config import AppConfig, SETTINGS_FILE, configure_logging, load_env_file
from .ui.main_window import DesktopGremlinChatApp


def run() -> None:
    config = AppConfig.load_from_json(SETTINGS_FILE)
    load_env_file(config.env_file)
    configure_logging(config)
    root = tk.Tk()
    DesktopGremlinChatApp(root, config)
    root.mainloop()
