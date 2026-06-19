from __future__ import annotations

import logging
import os
import re
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext
from typing import Callable

from PIL import Image, ImageDraw

from ..agent_loop import run_chat_turn
from ..config import AppConfig, SETTINGS_FILE
from ..context_manager import estimate_message_tokens
from ..game.game_controller import GameController, InitialGameReview
from ..game.initial_state_generator import InitialStateGenerator, OllamaInitialStateLLM
from ..game.context_assembler import ContextAssembler
from ..game.models import Choice, GameSave, GameViewState, PlayerAction
from ..game.narrator_service import NarratorService, OllamaNarratorLLM
from ..game.state_applier import StateApplier
from ..game.state_validator import StateValidator
from ..game.turn_processor import TurnProcessor
from ..game.actions import PlayerActionSource
from ..history_store import (
    create_empty_conversation,
    list_conversations,
    load_conversation,
    save_conversation,
)
from ..image_utils import ALLOWED_IMAGE_EXTENSIONS, image_file_to_base64
from ..models import ChatMessage
from ..ollama_client import OllamaClient
from ..persistence.json_repository import JsonGameRepository
from ..search_client import SearchClient
from .image_attachment_bar import ImageAttachmentBar
from .choice_panel import ChoicePanel
from .developer_inspector import DeveloperInspectorWindow
from .game_state_panel import GameStatePanel
from .settings_dialog import SettingsDialog

try:
    import pystray
except ImportError:
    pystray = None


THEMES = {
    "light": {
        "window": "#f4f1ea",
        "header": "#242424",
        "header_text": "#fff7d6",
        "header_muted": "#d8d0b4",
        "panel": "#fffdf7",
        "panel_alt": "#fbf8ef",
        "strip": "#ebe5d8",
        "text": "#222222",
        "muted": "#6f6a60",
        "assistant": "#2f2a20",
        "user": "#064f7a",
        "error": "#9b1c1c",
        "accent": "#d08b32",
        "button": "#3c3c3c",
        "button_hover": "#505050",
        "primary": "#1f1f1f",
        "primary_hover": "#383838",
        "input": "#ffffff",
        "border": "#d5cabb",
        "code_bg": "#eee7d9",
        "code_fg": "#2d2a25",
        "quote": "#80683e",
    },
    "dark": {
        "window": "#101214",
        "header": "#171a1f",
        "header_text": "#f4f0e6",
        "header_muted": "#aeb6c2",
        "panel": "#181b20",
        "panel_alt": "#14171b",
        "strip": "#20242b",
        "text": "#e9edf2",
        "muted": "#939ba7",
        "assistant": "#e9edf2",
        "user": "#8ecbff",
        "error": "#ff8a8a",
        "accent": "#f0a84c",
        "button": "#29303a",
        "button_hover": "#343d49",
        "primary": "#d98d38",
        "primary_hover": "#f0a84c",
        "input": "#111418",
        "border": "#2d3440",
        "code_bg": "#0d1014",
        "code_fg": "#d8e1ee",
        "quote": "#c6aa72",
    },
}


class DesktopGremlinChatApp:
    def __init__(self, root: tk.Tk, config: AppConfig):
        self.root = root
        self.config = config
        self.ollama_client = OllamaClient(config)
        self.search_client = SearchClient(config)
        self.game_repository = JsonGameRepository()
        self.game_controller = GameController(
            self.game_repository,
            InitialStateGenerator(OllamaInitialStateLLM(self.ollama_client, self.config)),
            TurnProcessor(
                repository=self.game_repository,
                context_assembler=ContextAssembler(),
                narrator_service=NarratorService(OllamaNarratorLLM(self.ollama_client, self.config)),
                state_validator=StateValidator(),
                state_applier=StateApplier(),
            ),
        )

        self.root.title("Desktop Gremlin")
        self.root.geometry("900x700")
        self.root.minsize(640, 520)
        self.root.protocol("WM_DELETE_WINDOW", self.hide_to_tray_or_quit)

        self.is_waiting = False
        self.messages: list[ChatMessage] = []
        self.current_conversation = create_empty_conversation()
        self.current_game_id: str | None = None
        self.current_game_view: GameViewState | None = None
        self.pending_game_choices: list[Choice] = []
        self.history_items: list[dict] = []
        self.loading_history_selection = False
        self.selected_image_paths: list[str] = []
        self.tray_icon = None
        self.web_access_mode_var = tk.StringVar(value=self.config.web_access_mode)
        self.theme_mode_var = tk.StringVar(value=self.normalized_theme_mode())
        self.thinking_expanded = tk.BooleanVar(value=False)
        self.current_answer_parts: list[str] = []
        self.current_thinking_parts: list[str] = []
        self.assistant_stream_started = False
        self.assistant_stream_body_mark = "assistant_stream_body"
        self.activity_animation_job: str | None = None
        self.activity_animation_message = ""
        self.activity_animation_step = 0
        self.last_prompt_tokens: int | None = None
        self.last_output_tokens: int | None = None
        self.last_context_total_tokens: int | None = None
        self.trimmed_message_count = 0
        self.ollama_startup_thread: threading.Thread | None = None

        self.build_ui()
        self.start_tray_icon()
        self.start_fresh_conversation("Ready. Type something and press Enter.")
        self.refresh_history_list()
        self.start_ollama_startup_check()

    def normalized_theme_mode(self) -> str:
        return self.config.appearance_mode if self.config.appearance_mode in THEMES else "dark"

    @property
    def colors(self) -> dict[str, str]:
        return THEMES[self.normalized_theme_mode()]

    def build_ui(self) -> None:
        c = self.colors
        self.root.configure(bg=c["window"])
        self.root.grid_rowconfigure(1, weight=1)
        self.root.grid_columnconfigure(0, weight=1)

        self.header = tk.Frame(self.root, bg=c["header"])
        header = self.header
        header.grid(row=0, column=0, sticky="ew")
        header.grid_columnconfigure(0, weight=1)

        self.title_label = tk.Label(
            header,
            text="Desktop Gremlin",
            bg=c["header"],
            fg=c["header_text"],
            font=("Segoe UI", 15, "bold"),
            padx=16,
            pady=11,
        )
        self.title_label.grid(row=0, column=0, sticky="w")

        self.status_var = tk.StringVar(value=f"Model: {self.config.model}")
        self.status_label = tk.Label(
            header,
            textvariable=self.status_var,
            bg=c["header"],
            fg=c["header_muted"],
            font=("Segoe UI", 9),
            padx=16,
            pady=0,
            anchor="w",
            justify="left",
            wraplength=760,
        )
        self.status_label.grid(row=1, column=0, columnspan=8, sticky="ew", pady=(0, 8))
        self.header.bind("<Configure>", self.update_status_wraplength)

        self.web_access_label = tk.Label(
            header,
            text="Web access",
            bg=c["header"],
            fg=c["header_text"],
            font=("Segoe UI", 9),
        )
        self.web_access_label.grid(row=0, column=1, sticky="e", padx=(10, 4))

        self.web_access_menu = tk.OptionMenu(
            header,
            self.web_access_mode_var,
            "automatic",
            "disabled",
            command=self.set_web_access_mode,
        )
        self.configure_option_menu(self.web_access_menu)
        self.web_access_menu.grid(row=0, column=2, sticky="e")

        self.python_access_label = tk.Label(
            header,
            text="Python",
            bg=c["header"],
            fg=c["header_text"],
            font=("Segoe UI", 9),
        )
        self.python_access_label.grid(row=0, column=3, sticky="e", padx=(10, 4))

        self.python_access_mode_var = tk.StringVar(value=self.config.python_access_mode)
        self.python_access_menu = tk.OptionMenu(
            header,
            self.python_access_mode_var,
            "automatic",
            "disabled",
            command=self.set_python_access_mode,
        )
        self.configure_option_menu(self.python_access_menu)
        self.python_access_menu.grid(row=0, column=4, sticky="e")

        self.theme_button = tk.Button(
            header,
            text=self.theme_button_text(),
            command=self.toggle_theme,
            bg=c["button"],
            fg=c["header_text"],
            activebackground=c["button_hover"],
            activeforeground=c["header_text"],
            relief="flat",
            font=("Segoe UI", 9),
            padx=10,
        )
        self.theme_button.grid(row=0, column=5, sticky="e", padx=(8, 0))

        self.settings_button = tk.Button(
            header,
            text="Settings",
            command=self.open_settings,
            bg=c["button"],
            fg=c["header_text"],
            activebackground=c["button_hover"],
            activeforeground=c["header_text"],
            relief="flat",
            font=("Segoe UI", 9),
            padx=10,
        )
        self.settings_button.grid(row=0, column=6, sticky="e", padx=(8, 12))

        self.inspector_button = tk.Button(
            header,
            text="Inspector",
            command=self.open_developer_inspector,
            bg=c["button"],
            fg=c["header_text"],
            activebackground=c["button_hover"],
            activeforeground=c["header_text"],
            relief="flat",
            font=("Segoe UI", 9),
            padx=10,
        )
        self.inspector_button.grid(row=0, column=7, sticky="e", padx=(0, 12))

        self.body = tk.Frame(self.root, bg=c["window"])
        body = self.body
        body.grid(row=1, column=0, sticky="nsew", padx=14, pady=(14, 8))
        body.grid_rowconfigure(0, weight=1)
        body.grid_columnconfigure(0, weight=0)
        body.grid_columnconfigure(1, weight=1)

        self.history_panel = tk.Frame(body, bg=c["panel_alt"], width=210)
        self.history_panel.grid(row=0, column=0, sticky="nsw", padx=(0, 10))
        self.history_panel.grid_propagate(False)
        self.history_panel.grid_rowconfigure(1, weight=1)
        self.history_panel.grid_columnconfigure(0, weight=1)

        self.history_label = tk.Label(
            self.history_panel,
            text="Chat History",
            bg=c["panel_alt"],
            fg=c["text"],
            font=("Segoe UI", 10, "bold"),
            anchor="w",
            padx=10,
            pady=8,
        )
        self.history_label.grid(row=0, column=0, columnspan=2, sticky="ew")

        self.history_listbox = tk.Listbox(
            self.history_panel,
            activestyle="none",
            exportselection=False,
            bg=c["panel"],
            fg=c["text"],
            selectbackground=c["accent"],
            selectforeground="#111111",
            relief="flat",
            bd=0,
            highlightthickness=0,
            font=("Segoe UI", 9),
        )
        self.history_listbox.grid(row=1, column=0, sticky="nsew", padx=(8, 0), pady=(0, 8))
        self.history_listbox.bind("<<ListboxSelect>>", self.load_selected_history)

        self.history_scrollbar = tk.Scrollbar(
            self.history_panel,
            orient="vertical",
            command=self.history_listbox.yview,
            relief="flat",
        )
        self.history_scrollbar.grid(row=1, column=1, sticky="ns", padx=(0, 8), pady=(0, 8))
        self.history_listbox.configure(yscrollcommand=self.history_scrollbar.set)

        self.game_state_panel = GameStatePanel(self.history_panel, bg=c["panel_alt"])
        self.game_state_panel.apply_theme(bg=c["panel_alt"], fg=c["text"], muted=c["muted"])
        self.game_state_panel.grid(row=2, column=0, columnspan=2, sticky="ew", padx=8, pady=(0, 8))
        self.game_state_panel.set_view(None)

        self.transcript = scrolledtext.ScrolledText(
            body,
            wrap="word",
            state="disabled",
            bg=c["panel"],
            fg=c["text"],
            insertbackground=c["text"],
            relief="flat",
            bd=1,
            padx=16,
            pady=14,
            font=("Segoe UI", 10),
        )
        self.transcript.grid(row=0, column=1, sticky="nsew")
        self.configure_transcript_tags()

        self.thinking_bar = tk.Frame(self.root, bg=c["strip"])
        thinking_bar = self.thinking_bar
        thinking_bar.grid(row=2, column=0, sticky="ew", padx=14, pady=(0, 0))
        thinking_bar.grid_columnconfigure(1, weight=1)

        self.thinking_button = tk.Checkbutton(
            thinking_bar,
            text="Show thinking",
            variable=self.thinking_expanded,
            command=self.toggle_thinking_panel,
            bg=c["strip"],
            fg=c["text"],
            selectcolor=c["strip"],
            activebackground=c["strip"],
            activeforeground=c["text"],
            font=("Segoe UI", 9, "bold"),
        )
        self.thinking_button.grid(row=0, column=0, sticky="w", padx=(6, 8), pady=4)

        self.thinking_status_var = tk.StringVar(value="No thinking captured yet")
        self.thinking_status = tk.Label(
            thinking_bar,
            textvariable=self.thinking_status_var,
            bg=c["strip"],
            fg=c["muted"],
            font=("Segoe UI", 9),
        )
        self.thinking_status.grid(row=0, column=1, sticky="w")

        self.activity_status_var = tk.StringVar(value="")
        self.activity_status = tk.Label(
            thinking_bar,
            textvariable=self.activity_status_var,
            bg=c["strip"],
            fg=c["accent"],
            font=("Segoe UI", 9, "bold"),
        )
        self.activity_status.grid(row=0, column=2, sticky="e", padx=(10, 6))

        self.thinking_text = scrolledtext.ScrolledText(
            self.root,
            height=6,
            wrap="word",
            state="disabled",
            bg=c["panel_alt"],
            fg=c["text"],
            insertbackground=c["text"],
            relief="flat",
            bd=1,
            padx=10,
            pady=8,
            font=("Consolas", 9),
        )

        self.composer = tk.Frame(self.root, bg=c["window"])
        composer = self.composer
        composer.grid(row=4, column=0, sticky="ew", padx=14, pady=(8, 14))
        composer.grid_columnconfigure(0, weight=1)

        self.choice_panel = ChoicePanel(composer, on_choice=self.send_choice_action, bg=c["window"])
        self.choice_panel.apply_theme(
            bg=c["window"],
            button_bg=c["button"],
            button_fg=c["header_text"],
            active_bg=c["button_hover"],
        )
        self.choice_panel.grid(row=0, column=0, columnspan=5, sticky="ew", pady=(0, 6))
        self.choice_panel.clear_choices()

        self.attachment_bar = ImageAttachmentBar(
            composer,
            on_remove=self.remove_attached_image,
            on_clear=self.clear_attached_images,
            bg=c["window"],
        )
        self.attachment_bar.apply_theme(
            bg=c["window"],
            chip_bg=c["strip"],
            chip_fg=c["text"],
            remove_bg=c["button"],
            button_bg=c["button"],
            button_fg=c["header_text"],
            active_bg=c["button_hover"],
        )
        self.choice_panel.apply_theme(
            bg=c["window"],
            button_bg=c["button"],
            button_fg=c["header_text"],
            active_bg=c["button_hover"],
        )
        self.attachment_bar.grid(row=1, column=0, columnspan=5, sticky="ew", pady=(0, 6))
        self.attachment_bar.set_paths([])

        self.input_text = tk.Text(
            composer,
            height=4,
            wrap="word",
            bg=c["input"],
            fg=c["text"],
            insertbackground=c["text"],
            relief="flat",
            bd=1,
            padx=12,
            pady=9,
            font=("Segoe UI", 10),
        )
        self.input_text.grid(row=2, column=0, sticky="ew")
        self.input_text.bind("<Return>", self.handle_return)
        self.input_text.bind("<Shift-Return>", lambda _event: None)

        self.attach_button = tk.Button(
            composer,
            text="Attach image",
            command=self.attach_images,
            width=12,
            bg=c["button"],
            fg=c["header_text"],
            activebackground=c["button_hover"],
            activeforeground=c["header_text"],
            relief="flat",
            font=("Segoe UI", 10),
        )
        self.attach_button.grid(row=2, column=1, sticky="ns", padx=(8, 0))

        self.send_button = tk.Button(
            composer,
            text="Send",
            command=self.send_message,
            width=10,
            bg=c["primary"],
            fg="#111111" if self.normalized_theme_mode() == "dark" else c["header_text"],
            activebackground=c["primary_hover"],
            activeforeground="#111111" if self.normalized_theme_mode() == "dark" else c["header_text"],
            relief="flat",
            font=("Segoe UI", 10, "bold"),
        )
        self.send_button.grid(row=2, column=2, sticky="ns", padx=(8, 0))

        self.new_game_button = tk.Button(
            composer,
            text="New Game",
            command=self.open_new_game,
            width=10,
            bg=c["button"],
            fg=c["header_text"],
            activebackground=c["button_hover"],
            activeforeground=c["header_text"],
            relief="flat",
            font=("Segoe UI", 10),
        )
        self.new_game_button.grid(row=2, column=3, sticky="ns", padx=(8, 0))

        self.new_chat_button = tk.Button(
            composer,
            text="New Chat",
            command=self.new_chat,
            width=10,
            bg=c["button"],
            fg=c["header_text"],
            activebackground=c["button_hover"],
            activeforeground=c["header_text"],
            relief="flat",
            font=("Segoe UI", 10),
        )
        self.new_chat_button.grid(row=2, column=4, sticky="ns", padx=(8, 0))

        self.helper_label = tk.Label(
            composer,
            text="Enter = send   |   Shift+Enter = newline",
            bg=c["window"],
            fg=c["muted"],
            font=("Segoe UI", 8),
        )
        self.helper_label.grid(row=3, column=0, columnspan=5, sticky="w", pady=(4, 0))

        self.update_status()

    def configure_option_menu(self, option_menu: tk.OptionMenu) -> None:
        c = self.colors
        option_menu.configure(
            bg=c["button"],
            fg=c["header_text"],
            activebackground=c["button_hover"],
            activeforeground=c["header_text"],
            relief="flat",
            highlightthickness=0,
            font=("Segoe UI", 9),
            width=10,
        )
        option_menu["menu"].configure(bg=c["panel"], fg=c["text"], activebackground=c["strip"])

    def configure_transcript_tags(self) -> None:
        c = self.colors
        self.transcript.tag_configure("user", foreground=c["user"], spacing1=10, spacing3=4)
        self.transcript.tag_configure("assistant", foreground=c["assistant"], spacing1=10, spacing3=4)
        self.transcript.tag_configure("error", foreground=c["error"], spacing1=10, spacing3=4)
        self.transcript.tag_configure("meta", foreground=c["muted"], spacing1=10, spacing3=4)
        self.transcript.tag_configure("speaker", font=("Segoe UI", 10, "bold"), spacing1=10)
        self.transcript.tag_configure("bold", font=("Segoe UI", 10, "bold"))
        self.transcript.tag_configure("italic", font=("Segoe UI", 10, "italic"))
        self.transcript.tag_configure("link", foreground=c["accent"], underline=True)
        self.transcript.tag_configure("heading", font=("Segoe UI", 13, "bold"), spacing1=12, spacing3=6)
        self.transcript.tag_configure(
            "code",
            font=("Consolas", 9),
            background=c["code_bg"],
            foreground=c["code_fg"],
        )
        self.transcript.tag_configure(
            "code_block",
            font=("Consolas", 9),
            background=c["code_bg"],
            foreground=c["code_fg"],
            lmargin1=12,
            lmargin2=12,
            spacing1=6,
            spacing3=6,
        )
        self.transcript.tag_configure(
            "quote",
            foreground=c["quote"],
            lmargin1=14,
            lmargin2=14,
            spacing1=4,
            spacing3=4,
        )
        self.transcript.tag_configure("list", lmargin1=16, lmargin2=32, spacing1=2)

    def update_status_wraplength(self, _event=None) -> None:
        width = max(240, self.header.winfo_width() - 32)
        self.status_label.configure(wraplength=width)

    def open_settings(self) -> None:
        if self.is_waiting:
            return
        SettingsDialog(self.root, self.config, self.save_settings)

    def save_settings(self, new_config: AppConfig) -> None:
        self.config = new_config
        self.config.save_to_json(SETTINGS_FILE)
        self.ollama_client.config = self.config
        self.search_client = SearchClient(self.config)
        self.web_access_mode_var.set(self.config.web_access_mode)
        self.python_access_mode_var.set(self.config.python_access_mode)
        self.theme_mode_var.set(self.normalized_theme_mode())
        self.update_status()
        logging.info("Settings saved to %s", SETTINGS_FILE)

    def toggle_theme(self) -> None:
        self.config.appearance_mode = "light" if self.normalized_theme_mode() == "dark" else "dark"
        self.theme_mode_var.set(self.config.appearance_mode)
        self.config.save_to_json(SETTINGS_FILE)
        self.apply_theme()

    def theme_button_text(self) -> str:
        return "Light" if self.normalized_theme_mode() == "dark" else "Dark"

    def apply_theme(self) -> None:
        c = self.colors
        self.root.configure(bg=c["window"])
        self.header.configure(bg=c["header"])
        self.title_label.configure(bg=c["header"], fg=c["header_text"])
        self.status_label.configure(bg=c["header"], fg=c["header_muted"])
        self.web_access_label.configure(bg=c["header"], fg=c["header_text"])
        self.python_access_label.configure(bg=c["header"], fg=c["header_text"])
        self.configure_option_menu(self.web_access_menu)
        self.configure_option_menu(self.python_access_menu)

        for button in (
            self.theme_button,
            self.settings_button,
            self.inspector_button,
            self.attach_button,
            self.new_game_button,
            self.new_chat_button,
        ):
            button.configure(
                bg=c["button"],
                fg=c["header_text"],
                activebackground=c["button_hover"],
                activeforeground=c["header_text"],
            )
        self.theme_button.configure(text=self.theme_button_text())
        primary_fg = "#111111" if self.normalized_theme_mode() == "dark" else c["header_text"]
        self.send_button.configure(
            bg=c["primary"],
            fg=primary_fg,
            activebackground=c["primary_hover"],
            activeforeground=primary_fg,
        )

        self.body.configure(bg=c["window"])
        self.history_panel.configure(bg=c["panel_alt"])
        self.history_label.configure(bg=c["panel_alt"], fg=c["text"])
        self.history_listbox.configure(
            bg=c["panel"],
            fg=c["text"],
            selectbackground=c["accent"],
            selectforeground="#111111",
        )
        self.game_state_panel.apply_theme(bg=c["panel_alt"], fg=c["text"], muted=c["muted"])
        self.composer.configure(bg=c["window"])
        self.helper_label.configure(bg=c["window"], fg=c["muted"])
        self.transcript.configure(
            bg=c["panel"],
            fg=c["text"],
            insertbackground=c["text"],
        )
        self.configure_transcript_tags()
        self.thinking_bar.configure(bg=c["strip"])
        self.thinking_button.configure(
            bg=c["strip"],
            fg=c["text"],
            selectcolor=c["strip"],
            activebackground=c["strip"],
            activeforeground=c["text"],
        )
        self.thinking_status.configure(bg=c["strip"], fg=c["muted"])
        self.activity_status.configure(bg=c["strip"], fg=c["accent"])
        self.thinking_text.configure(
            bg=c["panel_alt"],
            fg=c["text"],
            insertbackground=c["text"],
        )
        self.input_text.configure(
            bg=c["input"],
            fg=c["text"],
            insertbackground=c["text"],
        )
        self.attachment_bar.apply_theme(
            bg=c["window"],
            chip_bg=c["strip"],
            chip_fg=c["text"],
            remove_bg=c["button"],
            button_bg=c["button"],
            button_fg=c["header_text"],
            active_bg=c["button_hover"],
        )

    def set_web_access_mode(self, mode: str) -> None:
        if mode not in {"automatic", "disabled"}:
            mode = "automatic"
        self.config.web_access_mode = mode
        self.config.save_to_json(SETTINGS_FILE)
        self.update_status()

    def set_python_access_mode(self, mode: str) -> None:
        if mode not in {"automatic", "disabled"}:
            mode = "automatic"
        self.config.python_access_mode = mode
        self.config.save_to_json(SETTINGS_FILE)
        self.update_status()

    def attach_images(self) -> None:
        if self.is_waiting:
            return
        patterns = " ".join(f"*{ext}" for ext in sorted(ALLOWED_IMAGE_EXTENSIONS))
        paths = filedialog.askopenfilenames(
            parent=self.root,
            title="Attach image",
            filetypes=[("Image files", patterns), ("All files", "*.*")],
        )
        if not paths:
            return
        for path in paths:
            if path not in self.selected_image_paths:
                self.selected_image_paths.append(path)
        self.attachment_bar.set_paths(self.selected_image_paths)

    def remove_attached_image(self, index: int) -> None:
        if 0 <= index < len(self.selected_image_paths):
            self.selected_image_paths.pop(index)
            self.attachment_bar.set_paths(self.selected_image_paths)

    def clear_attached_images(self) -> None:
        self.selected_image_paths = []
        self.attachment_bar.set_paths([])

    def new_chat(self) -> None:
        if self.is_waiting:
            return
        self.current_game_id = None
        self.current_game_view = None
        self.pending_game_choices = []
        self.choice_panel.clear_choices()
        self.start_fresh_conversation("New chat started. How can I help you?")
        self.refresh_history_list()

    def open_new_game(self) -> None:
        if self.is_waiting:
            return
        NewGameDialog(self.root, self.game_controller, self.show_accepted_game, self.colors)

    def open_developer_inspector(self) -> None:
        if self.current_game_id is None:
            self.append_message("Assistant", "No active game to inspect.", "error")
            return
        DeveloperInspectorWindow(self.root, self.game_controller, self.current_game_id, self.colors)

    def show_accepted_game(self, save: GameSave) -> None:
        view = self.game_controller.get_game_view(save.campaign.id)
        self.show_game_view(view, game_save_summary(save), f"Game saved: {save.campaign.title}")

    def show_loaded_game(self, game_id: str) -> None:
        view = self.game_controller.get_game_view(game_id)
        self.show_game_view(view, game_view_summary(view), f"Game: {view.title} | Turn {view.state.turn_number}")

    def show_game_view(self, view: GameViewState, transcript_text: str, status: str) -> None:
        self.current_conversation = create_empty_conversation()
        self.current_game_id = view.game_id
        self.current_game_view = view
        self.pending_game_choices = []
        self.messages = []
        self.trimmed_message_count = 0
        self.last_prompt_tokens = None
        self.last_output_tokens = None
        self.last_context_total_tokens = None
        self.clear_attached_images()

        self.transcript.configure(state="normal")
        self.transcript.delete("1.0", "end")
        self.transcript.configure(state="disabled")

        self.set_thinking_text("")
        self.thinking_status_var.set("No thinking captured yet")
        self.append_message("Assistant", transcript_text, "assistant")
        self.choice_panel.set_choices(view.choices)
        self.game_state_panel.set_view(view)
        self.update_status(status)

    def start_fresh_conversation(self, greeting: str) -> None:
        self.current_conversation = create_empty_conversation()
        self.current_game_id = None
        self.current_game_view = None
        self.pending_game_choices = []
        self.choice_panel.clear_choices()
        self.game_state_panel.set_view(None)
        self.messages = []
        self.trimmed_message_count = 0
        self.last_prompt_tokens = None
        self.last_output_tokens = None
        self.last_context_total_tokens = None
        self.clear_attached_images()

        self.transcript.configure(state="normal")
        self.transcript.delete("1.0", "end")
        self.transcript.configure(state="disabled")

        self.set_thinking_text("")
        self.thinking_status_var.set("No thinking captured yet")
        self.append_message("Assistant", greeting, "assistant")
        self.update_status()

    def refresh_history_list(self, selected_id: str | None = None) -> None:
        self.history_items = list_conversations(self.config.history_dir)
        self.loading_history_selection = True
        try:
            self.history_listbox.delete(0, "end")
            selected_index = None
            for index, conversation in enumerate(self.history_items):
                title = str(conversation.get("title") or "New chat")
                updated = str(conversation.get("updated_at") or "")
                label = title if len(title) <= 32 else title[:29] + "..."
                if updated:
                    label = f"{label}  {updated[:10]}"
                self.history_listbox.insert("end", label)
                if selected_id and str(conversation.get("id")) == selected_id:
                    selected_index = index

            if selected_index is not None:
                self.history_listbox.selection_set(selected_index)
                self.history_listbox.see(selected_index)
        finally:
            self.loading_history_selection = False

    def load_selected_history(self, _event=None) -> None:
        if self.loading_history_selection or self.is_waiting:
            return
        selection = self.history_listbox.curselection()
        if not selection:
            return
        index = selection[0]
        if index >= len(self.history_items):
            return
        conversation_id = str(self.history_items[index].get("id") or "")
        if conversation_id:
            self.load_history_conversation(conversation_id)

    def load_history_conversation(self, conversation_id: str) -> None:
        conversation = load_conversation(self.config.history_dir, conversation_id)
        if conversation is None:
            self.refresh_history_list()
            return

        self.current_conversation = conversation
        self.current_game_id = None
        self.current_game_view = None
        self.pending_game_choices = []
        self.choice_panel.clear_choices()
        self.game_state_panel.set_view(None)
        messages = self.current_conversation.get("messages", [])
        self.messages = list(messages) if isinstance(messages, list) else []
        self.trimmed_message_count = 0
        self.last_prompt_tokens = None
        self.last_output_tokens = None
        self.last_context_total_tokens = None
        self.clear_attached_images()

        self.transcript.configure(state="normal")
        self.transcript.delete("1.0", "end")
        self.transcript.configure(state="disabled")

        if not self.messages:
            self.append_message("Assistant", "Ready. Type something and press Enter.", "assistant")
            self.update_status()
            return

        for message in self.messages:
            self.render_saved_message(message)
        self.refresh_history_list(str(self.current_conversation["id"]))
        self.update_status()

    def render_saved_message(self, message: ChatMessage) -> None:
        if message.role == "user":
            self.append_saved_user_message(message)
        elif message.role == "assistant" and message.content.strip() and not message.tool_calls:
            self.append_message("Assistant", message.content, "assistant")

    def append_saved_user_message(self, message: ChatMessage) -> None:
        display = message.content
        if message.images:
            count = len(message.images)
            noun = "image" if count == 1 else "images"
            display += f"\n[Attached {count} saved {noun}]"
        self.append_message("You", display, "user")

    def save_current_conversation(self) -> None:
        self.current_conversation["messages"] = self.messages
        save_conversation(self.config.history_dir, self.current_conversation)
        self.refresh_history_list(str(self.current_conversation["id"]))

    def toggle_thinking_panel(self) -> None:
        if self.thinking_expanded.get():
            self.thinking_text.grid(row=3, column=0, sticky="ew", padx=12, pady=(0, 0))
        else:
            self.thinking_text.grid_remove()

    def start_tray_icon(self) -> None:
        if pystray is None:
            logging.warning("pystray is not installed; running without tray icon")
            return

        image = create_tray_image()
        menu = pystray.Menu(
            pystray.MenuItem("Show chat", lambda _icon, _item: self.root.after(0, self.show_chat)),
            pystray.MenuItem("Quit", lambda _icon, _item: self.root.after(0, self.quit)),
        )
        self.tray_icon = pystray.Icon("desktop-gremlin", image, "Desktop Gremlin", menu)
        threading.Thread(target=self.tray_icon.run, daemon=True).start()

    def start_ollama_startup_check(self) -> None:
        if not self.config.auto_start_ollama and not self.config.preload_model_on_launch:
            return
        if self.ollama_startup_thread is not None and self.ollama_startup_thread.is_alive():
            return

        self.start_activity_animation("Preparing Ollama")
        self.update_status("Checking Ollama...")
        self.ollama_startup_thread = threading.Thread(target=self.ollama_startup_worker, daemon=True)
        self.ollama_startup_thread.start()

    def ollama_startup_worker(self) -> None:
        try:
            self.ollama_client.ensure_ready(
                preload_model=self.config.preload_model_on_launch,
                status_callback=lambda message: self.root.after(0, self.handle_ollama_startup_status, message),
            )
        except Exception as exc:
            logging.exception("Ollama startup check failed")
            self.root.after(0, self.finish_ollama_startup, f"Ollama startup failed: {exc}")
            return
        self.root.after(0, self.finish_ollama_startup, None)

    def handle_ollama_startup_status(self, message: str) -> None:
        if self.is_waiting:
            return
        self.update_status(message)
        lower = message.lower()
        if "loading model" in lower:
            self.start_activity_animation("Loading model")
        elif "starting ollama" in lower:
            self.start_activity_animation("Starting Ollama")
        elif "checking ollama" in lower:
            self.start_activity_animation("Checking Ollama")

    def finish_ollama_startup(self, error_message: str | None) -> None:
        if self.is_waiting:
            return
        self.stop_activity_animation()
        if error_message:
            self.update_status(error_message)
            self.append_message("Assistant", error_message, "error")
            return
        self.update_status()

    def handle_return(self, event):
        if event.state & 0x0001:
            return None
        self.send_message()
        return "break"

    def send_message(self) -> None:
        if self.is_waiting:
            return

        text = self.input_text.get("1.0", "end").strip()
        if self.current_game_id is not None:
            self.send_game_action(text)
            return

        image_paths = list(self.selected_image_paths)
        if not text and not image_paths:
            return

        content = text or "Please analyze the attached image(s)."

        try:
            image_base64_list = [image_file_to_base64(path) for path in image_paths]
        except ValueError as exc:
            logging.exception("Image attachment failed")
            self.append_message("Assistant", f"Oops: {exc}", "error")
            return

        self.input_text.delete("1.0", "end")
        user_message = ChatMessage(role="user", content=content, images=image_base64_list)
        self.messages.append(user_message)
        self.save_current_conversation()
        self.append_user_message(content, image_paths)
        self.clear_attached_images()
        self.set_waiting(True)
        self.prepare_stream_display()

        worker = threading.Thread(
            target=self.chat_worker,
            args=(self.web_access_mode_var.get(), self.python_access_mode_var.get()),
            daemon=True,
        )
        worker.start()

    def send_game_action(self, text: str) -> None:
        if not text:
            return
        if self.selected_image_paths:
            self.append_message("Assistant", "Game mode currently supports text actions only.", "error")
            return
        game_id = self.current_game_id
        if game_id is None:
            return
        action = PlayerAction(source=PlayerActionSource.TEXT, text=text)
        self.start_game_action(game_id, action, text)

    def send_choice_action(self, choice: Choice) -> None:
        if self.is_waiting:
            return
        game_id = self.current_game_id
        view = self.current_game_view
        if game_id is None or view is None:
            return
        current_choice = next((item for item in view.choices if item.id == choice.id), None)
        if current_choice is None or current_choice.action_text != choice.action_text:
            self.append_message("Assistant", f"Oops: Unknown or stale choice ID: {choice.id}", "error")
            self.choice_panel.set_choices(view.choices)
            return
        action = PlayerAction(source=PlayerActionSource.CHOICE, text=choice.action_text, choice_id=choice.id)
        self.start_game_action(game_id, action, choice.action_text)

    def start_game_action(self, game_id: str, action: PlayerAction, display_text: str) -> None:
        self.input_text.delete("1.0", "end")
        self.pending_game_choices = list(self.current_game_view.choices) if self.current_game_view is not None else []
        self.choice_panel.clear_choices()
        self.append_message("You", display_text, "user")
        self.set_waiting(True)
        self.start_activity_animation("Resolving turn")
        worker = threading.Thread(target=self.game_turn_worker, args=(game_id, action), daemon=True)
        worker.start()

    def game_turn_worker(self, game_id: str, action: PlayerAction) -> None:
        try:
            view = self.game_controller.submit_action(game_id, action)
        except Exception as exc:
            logging.exception("Game turn failed")
            self.root.after(0, self.finish_game_turn_error, f"Oops: {exc}")
            return
        self.root.after(0, self.finish_game_turn, view)

    def finish_game_turn(self, view: GameViewState) -> None:
        self.current_game_id = view.game_id
        self.current_game_view = view
        self.pending_game_choices = []
        self.append_message("Assistant", game_view_summary(view), "assistant")
        self.choice_panel.set_choices(view.choices)
        self.game_state_panel.set_view(view)
        self.set_waiting(False)
        self.stop_activity_animation()
        self.update_status(f"Game: {view.title} | Turn {view.state.turn_number}")

    def finish_game_turn_error(self, message: str) -> None:
        self.append_message("Assistant", message, "error")
        if self.current_game_view is not None:
            self.choice_panel.set_choices(self.pending_game_choices or self.current_game_view.choices)
        self.pending_game_choices = []
        self.set_waiting(False)
        self.stop_activity_animation()
        if self.current_game_view is not None:
            self.update_status(f"Game: {self.current_game_view.title} | Turn {self.current_game_view.state.turn_number}")

    def chat_worker(self, web_access_mode: str, python_access_mode: str) -> None:
        try:
            base_message_count = len(self.messages)
            result = run_chat_turn(
                messages=list(self.messages),
                config=self.config,
                ollama_client=self.ollama_client,
                web_access_mode=web_access_mode,
                python_access_mode=python_access_mode,
                status_callback=lambda message: self.root.after(0, self.handle_agent_status, message),
                content_callback=lambda delta: self.root.after(0, self.append_assistant_delta, delta),
                thinking_callback=lambda delta: self.root.after(0, self.append_thinking_delta, delta),
            )

            if result.removed_messages:
                self.trimmed_message_count += result.removed_messages
                logging.info("Trimmed %s messages from chat history", result.removed_messages)

            answer = clean_text(result.answer)
            thinking_text = clean_text(result.thinking_text)
            if not answer:
                raise RuntimeError("Ollama returned no usable text.")
            updated_messages = result.messages
            if result.removed_messages:
                suffix_start = max(0, base_message_count - result.removed_messages)
                updated_messages = list(self.messages) + result.messages[suffix_start:]
            self.root.after(
                0,
                self.finish_chat,
                answer,
                thinking_text,
                result.prompt_tokens,
                result.output_tokens,
                updated_messages,
            )
        except Exception as exc:
            logging.exception("Chat request failed")
            self.root.after(0, self.finish_chat_error, f"Oops: {exc}")

    def update_context_usage(self, prompt_tokens, output_tokens) -> None:
        if isinstance(prompt_tokens, int):
            self.last_prompt_tokens = prompt_tokens
        if isinstance(output_tokens, int):
            self.last_output_tokens = output_tokens

        if isinstance(self.last_prompt_tokens, int) and isinstance(self.last_output_tokens, int):
            self.last_context_total_tokens = self.last_prompt_tokens + self.last_output_tokens
            percent = (
                (self.last_context_total_tokens / self.config.num_ctx) * 100
                if self.config.num_ctx
                else 0
            )
            logging.info(
                "Context usage: prompt=%s output=%s total=%s/%s %.1f%%",
                self.last_prompt_tokens,
                self.last_output_tokens,
                self.last_context_total_tokens,
                self.config.num_ctx,
                percent,
            )
        else:
            logging.info(
                "Ollama did not return complete token counts: prompt=%r output=%r",
                prompt_tokens,
                output_tokens,
            )

    def context_status_text(self) -> str:
        if isinstance(self.last_context_total_tokens, int):
            percent = (
                (self.last_context_total_tokens / self.config.num_ctx) * 100
                if self.config.num_ctx
                else 0
            )
            return f"Ctx: {self.last_context_total_tokens:,}/{self.config.num_ctx:,} ({percent:.1f}%)"
        estimated = estimate_message_tokens(self.messages, self.config.system_prompt)
        return f"Ctx est: {estimated:,}/{self.config.num_ctx:,}"

    def prepare_stream_display(self) -> None:
        self.current_answer_parts = []
        self.current_thinking_parts = []
        self.assistant_stream_started = False
        if self.assistant_stream_body_mark in self.transcript.mark_names():
            self.transcript.mark_unset(self.assistant_stream_body_mark)
        self.set_thinking_text("")
        self.thinking_status_var.set("No thinking captured yet")
        self.start_activity_animation("Thinking")

    def append_assistant_delta(self, delta: str) -> None:
        if not self.assistant_stream_started:
            self.transcript.configure(state="normal")
            self.transcript.insert("end-1c", "Assistant:\n", ("assistant", "speaker"))
            self.transcript.mark_set(self.assistant_stream_body_mark, "end-1c")
            self.transcript.mark_gravity(self.assistant_stream_body_mark, "left")
            self.transcript.configure(state="disabled")
            self.assistant_stream_started = True
            self.start_activity_animation("Streaming response")

        self.current_answer_parts.append(delta)
        self.transcript.configure(state="normal")
        self.transcript.insert("end-1c", delta, "assistant")
        self.transcript.configure(state="disabled")
        self.transcript.see("end")

    def append_thinking_delta(self, delta: str) -> None:
        self.current_thinking_parts.append(delta)
        count = len("".join(self.current_thinking_parts))
        self.thinking_status_var.set(f"Thinking captured: {count} chars")
        self.thinking_text.configure(state="normal")
        self.thinking_text.insert("end", delta)
        self.thinking_text.configure(state="disabled")
        self.thinking_text.see("end")

    def finish_chat(
        self,
        answer: str,
        thinking_text: str,
        prompt_tokens=None,
        output_tokens=None,
        updated_messages: list[ChatMessage] | None = None,
    ) -> None:
        if self.assistant_stream_started:
            self.transcript.configure(state="normal")
            if self.assistant_stream_body_mark in self.transcript.mark_names():
                self.transcript.delete(self.assistant_stream_body_mark, "end-1c")
                self.insert_markdown(answer, "assistant")
                self.transcript.insert("end-1c", "\n\n", "assistant")
            else:
                self.transcript.insert("end-1c", "\n\n", "assistant")
            self.transcript.configure(state="disabled")
            self.transcript.see("end")
        else:
            self.append_message("Assistant", answer, "assistant")

        if thinking_text:
            self.thinking_status_var.set(f"Thinking captured: {len(thinking_text)} chars")
        else:
            self.thinking_status_var.set("No thinking captured by Ollama/model")

        if updated_messages is not None:
            self.messages = updated_messages
        else:
            self.messages.append(ChatMessage(role="assistant", content=answer))
        self.save_current_conversation()
        self.update_context_usage(prompt_tokens, output_tokens)
        self.set_waiting(False)
        self.stop_activity_animation()

    def finish_chat_error(self, message: str) -> None:
        if self.assistant_stream_started:
            self.transcript.configure(state="normal")
            self.transcript.insert("end-1c", "\n\n", "assistant")
            self.transcript.configure(state="disabled")
        self.append_message("Assistant", message, "error")
        self.save_current_conversation()
        self.set_waiting(False)
        self.stop_activity_animation()

    def append_user_message(self, message: str, image_paths: list[str]) -> None:
        display = message
        if image_paths:
            names = ", ".join(os.path.basename(path) for path in image_paths)
            display += f"\n[Attached images: {names}]"
        self.append_message("You", display, "user")

    def append_message(self, speaker: str, message: str, tag: str | None = None) -> None:
        tag = tag or ("assistant" if speaker == "Assistant" else "meta")
        self.transcript.configure(state="normal")
        self.transcript.insert("end-1c", f"{speaker}:\n", (tag, "speaker"))
        self.insert_markdown(message, tag)
        self.transcript.insert("end-1c", "\n\n", tag)
        self.transcript.configure(state="disabled")
        self.transcript.see("end")

    def insert_markdown(self, text: str, base_tag: str) -> None:
        in_code_block = False
        code_lines: list[str] = []

        for line in text.splitlines() or [""]:
            if line.strip().startswith("```"):
                if in_code_block:
                    self.insert_code_block("\n".join(code_lines), base_tag)
                    code_lines = []
                    in_code_block = False
                else:
                    in_code_block = True
                continue

            if in_code_block:
                code_lines.append(line)
                continue

            if not line.strip():
                self.transcript.insert("end-1c", "\n", base_tag)
                continue

            heading = re.match(r"^(#{1,6})\s+(.+)$", line)
            if heading:
                self.insert_inline_markdown(heading.group(2).strip(), base_tag, ("heading",))
                self.transcript.insert("end-1c", "\n", base_tag)
                continue

            quote = re.match(r"^>\s?(.*)$", line)
            if quote:
                self.transcript.insert("end-1c", "  ", (base_tag, "quote"))
                self.insert_inline_markdown(quote.group(1), base_tag, ("quote",))
                self.transcript.insert("end-1c", "\n", base_tag)
                continue

            bullet = re.match(r"^\s*[-*+]\s+(.+)$", line)
            if bullet:
                self.transcript.insert("end-1c", "- ", (base_tag, "list"))
                self.insert_inline_markdown(bullet.group(1), base_tag, ("list",))
                self.transcript.insert("end-1c", "\n", base_tag)
                continue

            numbered = re.match(r"^\s*(\d+[.)])\s+(.+)$", line)
            if numbered:
                self.transcript.insert("end-1c", f"{numbered.group(1)} ", (base_tag, "list"))
                self.insert_inline_markdown(numbered.group(2), base_tag, ("list",))
                self.transcript.insert("end-1c", "\n", base_tag)
                continue

            self.insert_inline_markdown(line, base_tag)
            self.transcript.insert("end-1c", "\n", base_tag)

        if in_code_block:
            self.insert_code_block("\n".join(code_lines), base_tag)

    def insert_code_block(self, text: str, base_tag: str) -> None:
        if not text:
            text = " "
        self.transcript.insert("end-1c", text.rstrip() + "\n", (base_tag, "code_block"))

    def insert_inline_markdown(
        self,
        text: str,
        base_tag: str,
        extra_tags: tuple[str, ...] = (),
    ) -> None:
        pattern = re.compile(r"(\[[^\]]+\]\([^)]+\)|`[^`\n]+`|\*\*[^*\n]+?\*\*|__[^_\n]+?__|\*[^*\n]+?\*|_[^_\n]+?_)")
        position = 0
        for match in pattern.finditer(text):
            if match.start() > position:
                self.transcript.insert("end-1c", text[position : match.start()], (base_tag, *extra_tags))

            token = match.group(0)
            tags = [base_tag, *extra_tags]
            value = token
            link = re.match(r"^\[([^\]]+)\]\(([^)]+)\)$", token)
            if link:
                value = f"{link.group(1)} ({link.group(2)})"
                tags.append("link")
            elif token.startswith("`") and token.endswith("`"):
                value = token[1:-1]
                tags.append("code")
            elif token.startswith(("**", "__")) and token.endswith(("**", "__")):
                value = token[2:-2]
                tags.append("bold")
            elif token.startswith(("*", "_")) and token.endswith(("*", "_")):
                value = token[1:-1]
                tags.append("italic")
            self.transcript.insert("end-1c", value, tuple(tags))
            position = match.end()

        if position < len(text):
            self.transcript.insert("end-1c", text[position:], (base_tag, *extra_tags))

    def set_thinking_text(self, text: str) -> None:
        self.thinking_text.configure(state="normal")
        self.thinking_text.delete("1.0", "end")
        if text:
            self.thinking_text.insert("end", text)
        self.thinking_text.configure(state="disabled")

    def set_waiting(self, waiting: bool) -> None:
        self.is_waiting = waiting
        state = "disabled" if waiting else "normal"
        self.send_button.configure(state=state)
        self.attach_button.configure(state=state)
        self.new_game_button.configure(state=state)
        self.new_chat_button.configure(state=state)
        self.inspector_button.configure(state=state)
        self.settings_button.configure(state=state)
        self.theme_button.configure(state=state)
        self.input_text.configure(state=state)
        self.web_access_menu.configure(state=state)
        self.python_access_menu.configure(state=state)
        self.history_listbox.configure(state=state)
        self.choice_panel.set_enabled(not waiting)
        self.update_status("Thinking..." if waiting else None)
        if not waiting:
            self.input_text.configure(state="normal")
            self.input_text.focus_set()

    def handle_agent_status(self, message: str) -> None:
        self.update_status(message)
        if "generating response" in message.lower():
            self.start_activity_animation("Generating response")
        elif self.is_tool_status(message):
            self.start_activity_animation("Tool calling")
        elif "thinking" in message.lower():
            self.start_activity_animation("Thinking")

    def is_tool_status(self, message: str) -> bool:
        lower = message.lower()
        return (
            "tool" in lower
            or "web search" in lower
            or "searching" in lower
            or "running python" in lower
        )

    def start_activity_animation(self, message: str) -> None:
        self.activity_animation_message = message
        self.activity_animation_step = 0
        if self.activity_animation_job is None:
            self.animate_activity_status()

    def animate_activity_status(self) -> None:
        if not self.activity_animation_message:
            self.activity_animation_job = None
            self.activity_status_var.set("")
            return
        dots = "." * ((self.activity_animation_step % 3) + 1)
        self.activity_status_var.set(f"{self.activity_animation_message}{dots}")
        self.activity_animation_step += 1
        self.activity_animation_job = self.root.after(350, self.animate_activity_status)

    def stop_activity_animation(self) -> None:
        self.activity_animation_message = ""
        if self.activity_animation_job is not None:
            self.root.after_cancel(self.activity_animation_job)
            self.activity_animation_job = None
        self.activity_status_var.set("")

    def update_status(self, override: str | None = None) -> None:
        if override is not None:
            self.status_var.set(override)
            return
        mode = self.web_access_mode_var.get()
        if mode == "automatic" and not self.search_client.is_configured:
            search_state = "Web: auto, not configured"
        else:
            search_state = "Web: auto" if mode == "automatic" else "Web: off"
        python_mode = self.python_access_mode_var.get()
        python_state = "Python: auto" if python_mode == "automatic" else "Python: off"
        stream_state = "Stream: on"
        think_state = "Think: on" if self.config.think else "Think: off"
        context_state = self.context_status_text()
        self.status_var.set(
            f"Model: {self.config.model} | {context_state} | {search_state} | {python_state} | {stream_state} | {think_state}"
        )

    def show_chat(self) -> None:
        self.root.deiconify()
        self.root.lift()
        self.input_text.focus_set()

    def hide_to_tray_or_quit(self) -> None:
        if self.tray_icon is None:
            self.quit()
            return
        self.root.withdraw()

    def quit(self) -> None:
        if self.tray_icon is not None:
            self.tray_icon.stop()
        self.ollama_client.stop_model()
        self.ollama_client.shutdown_ollama_server()
        self.root.destroy()


class NewGameDialog:
    def __init__(
        self,
        root: tk.Tk,
        controller: GameController,
        on_accept: Callable[[GameSave], None],
        colors: dict[str, str],
    ):
        self.root = root
        self.controller = controller
        self.on_accept = on_accept
        self.colors = colors
        self.review: InitialGameReview | None = None
        self.campaign = None
        self.is_generating = False

        self.window = tk.Toplevel(root)
        self.window.title("New Game")
        self.window.geometry("720x680")
        self.window.minsize(560, 520)
        self.window.configure(bg=colors["window"])
        self.window.transient(root)
        self.window.grab_set()
        self.window.grid_columnconfigure(0, weight=1)
        self.window.grid_rowconfigure(0, weight=1)

        self.container = tk.Frame(self.window, bg=colors["window"])
        self.container.grid(row=0, column=0, sticky="nsew", padx=14, pady=14)
        self.container.grid_columnconfigure(1, weight=1)
        self.show_form()

    def clear(self) -> None:
        for child in self.container.winfo_children():
            child.destroy()

    def show_form(self) -> None:
        self.clear()
        c = self.colors
        self.container.grid_rowconfigure(1, weight=0)
        self.container.grid_rowconfigure(3, weight=1)
        self.container.grid_rowconfigure(5, weight=1)

        self.title_entry = self.add_entry("Campaign title", 0)
        self.lore_text = self.add_text("Initial lore", 1, height=8)
        self.premise_text = self.add_text("Player premise", 3, height=4)
        self.tone_entry = self.add_entry("Tone/style", 5)
        self.constraints_text = self.add_text("Content constraints", 6, height=3)

        self.status_var = tk.StringVar(value="")
        tk.Label(
            self.container,
            textvariable=self.status_var,
            bg=c["window"],
            fg=c["muted"],
            anchor="w",
            justify="left",
        ).grid(row=8, column=0, columnspan=2, sticky="ew", pady=(8, 0))

        button_row = tk.Frame(self.container, bg=c["window"])
        button_row.grid(row=9, column=0, columnspan=2, sticky="e", pady=(12, 0))
        self.generate_button = self.dialog_button(button_row, "Generate", self.generate)
        self.generate_button.pack(side="left", padx=(0, 8))
        self.dialog_button(button_row, "Cancel", self.window.destroy).pack(side="left")

    def add_entry(self, label: str, row: int) -> tk.Entry:
        c = self.colors
        tk.Label(self.container, text=label, bg=c["window"], fg=c["text"], anchor="w").grid(
            row=row,
            column=0,
            sticky="nw",
            padx=(0, 10),
            pady=(0, 8),
        )
        entry = tk.Entry(
            self.container,
            bg=c["input"],
            fg=c["text"],
            insertbackground=c["text"],
            relief="flat",
            font=("Segoe UI", 10),
        )
        entry.grid(row=row, column=1, sticky="ew", pady=(0, 8))
        return entry

    def add_text(self, label: str, row: int, height: int) -> tk.Text:
        c = self.colors
        tk.Label(self.container, text=label, bg=c["window"], fg=c["text"], anchor="w").grid(
            row=row,
            column=0,
            sticky="nw",
            padx=(0, 10),
            pady=(0, 8),
        )
        text = tk.Text(
            self.container,
            height=height,
            wrap="word",
            bg=c["input"],
            fg=c["text"],
            insertbackground=c["text"],
            relief="flat",
            padx=8,
            pady=6,
            font=("Segoe UI", 10),
        )
        text.grid(row=row, column=1, sticky="nsew", pady=(0, 8))
        return text

    def dialog_button(self, parent, text: str, command) -> tk.Button:
        c = self.colors
        return tk.Button(
            parent,
            text=text,
            command=command,
            bg=c["button"],
            fg=c["header_text"],
            activebackground=c["button_hover"],
            activeforeground=c["header_text"],
            relief="flat",
            padx=12,
            pady=5,
        )

    def generate(self) -> None:
        if self.is_generating:
            return
        try:
            self.campaign = self.controller.build_campaign_definition(
                title=self.title_entry.get(),
                initial_lore=self.lore_text.get("1.0", "end").strip(),
                player_premise=self.premise_text.get("1.0", "end").strip(),
                tone=self.tone_entry.get(),
                content_constraints=[
                    line.strip()
                    for line in self.constraints_text.get("1.0", "end").splitlines()
                    if line.strip()
                ],
            )
        except Exception as exc:
            self.status_var.set(f"Invalid campaign details: {exc}")
            return

        self.is_generating = True
        self.generate_button.configure(state="disabled")
        self.status_var.set("Generating initial game state...")
        threading.Thread(target=self.generate_worker, daemon=True).start()

    def generate_worker(self) -> None:
        try:
            review = self.controller.generate_initial_review(self.campaign)
        except Exception as exc:
            logging.exception("Initial game generation failed")
            self.root.after(0, self.finish_generation_error, str(exc))
            return
        self.root.after(0, self.show_review, review)

    def finish_generation_error(self, message: str) -> None:
        self.is_generating = False
        self.generate_button.configure(state="normal")
        self.status_var.set(f"Generation failed: {message}")

    def show_review(self, review: InitialGameReview) -> None:
        self.review = review
        self.is_generating = False
        self.clear()
        c = self.colors
        self.container.grid_columnconfigure(0, weight=1)
        self.container.grid_rowconfigure(0, weight=1)

        review_text = scrolledtext.ScrolledText(
            self.container,
            wrap="word",
            bg=c["panel"],
            fg=c["text"],
            insertbackground=c["text"],
            relief="flat",
            padx=12,
            pady=10,
            font=("Segoe UI", 10),
        )
        review_text.grid(row=0, column=0, sticky="nsew")
        review_text.insert("end", review_summary(review))
        review_text.configure(state="disabled")

        button_row = tk.Frame(self.container, bg=c["window"])
        button_row.grid(row=1, column=0, sticky="e", pady=(12, 0))
        self.dialog_button(button_row, "Start Game", self.accept).pack(side="left", padx=(0, 8))
        self.dialog_button(button_row, "Regenerate", self.regenerate).pack(side="left", padx=(0, 8))
        self.dialog_button(button_row, "Cancel", self.window.destroy).pack(side="left")

    def regenerate(self) -> None:
        if self.review is None or self.is_generating:
            return
        self.is_generating = True
        self.clear()
        c = self.colors
        tk.Label(
            self.container,
            text="Regenerating initial game state...",
            bg=c["window"],
            fg=c["text"],
            anchor="w",
            justify="left",
        ).grid(row=0, column=0, sticky="w")
        threading.Thread(target=self.regenerate_worker, daemon=True).start()

    def regenerate_worker(self) -> None:
        try:
            review = self.controller.regenerate_initial_review(self.review)
        except Exception as exc:
            logging.exception("Initial game regeneration failed")
            self.root.after(0, self.show_regeneration_error, str(exc))
            return
        self.root.after(0, self.show_review, review)

    def show_regeneration_error(self, message: str) -> None:
        self.is_generating = False
        messagebox.showerror("New Game", f"Regeneration failed:\n{message}", parent=self.window)
        if self.review is not None:
            self.show_review(self.review)
        else:
            self.show_form()

    def accept(self) -> None:
        if self.review is None:
            return
        try:
            save = self.controller.accept_initial_review(self.review)
        except Exception as exc:
            logging.exception("Saving generated game failed")
            messagebox.showerror("New Game", f"Could not save game:\n{exc}", parent=self.window)
            return
        self.window.destroy()
        self.on_accept(save)


def review_summary(review: InitialGameReview) -> str:
    state = review.initial_state.state
    location = state.locations[state.current_location_id]
    inventory = [
        f"- {state.item_definitions[item_id].name}: {entry.quantity}"
        for item_id, entry in state.inventory.items()
    ] or ["- None"]
    characters = [
        f"- {character.name}: {character.status}"
        for character in state.characters.values()
    ] or ["- None"]
    quests = [
        f"- {quest.title}: {quest.status} / {quest.stage}"
        for quest in state.quests.values()
    ] or ["- None"]
    choices = [
        f"- {choice.label}: {choice.action_text}"
        for choice in review.initial_state.initial_choices
    ] or ["- None"]

    return "\n".join(
        [
            f"Campaign: {review.campaign.title}",
            "",
            "Opening Narrative",
            review.opening_narrative,
            "",
            "Player",
            f"{state.player.name}: {state.player.status}",
            state.player.description,
            "",
            "Starting Location",
            f"{location.name}: {location.description}",
            "",
            "Starting Inventory",
            *inventory,
            "",
            "Initial Characters",
            *characters,
            "",
            "Initial Quests",
            *quests,
            "",
            "Initial Choices",
            *choices,
        ]
    )


def game_save_summary(save: GameSave) -> str:
    location = save.state.locations[save.state.current_location_id]
    choices = "\n".join(f"- {choice.label}" for choice in save.current_choices) or "- None"
    return (
        f"Game started: {save.campaign.title}\n\n"
        f"{save.state.player.name} begins at {location.name}.\n\n"
        f"Initial canon is saved unchanged with the campaign.\n\n"
        f"Available choices:\n{choices}"
    )


def game_view_summary(view: GameViewState) -> str:
    state = view.state
    location = state.locations[state.current_location_id]
    player_location = state.locations.get(state.player.current_location_id or state.current_location_id, location)
    choices = "\n".join(f"- {choice.label}" for choice in view.choices) or "- None"
    return (
        f"{view.narrative}\n\n"
        f"Turn: {state.turn_number}\n"
        f"Scene: {location.name}\n"
        f"Player location: {player_location.name}\n\n"
        f"Available choices:\n{choices}"
    )


def create_tray_image() -> Image.Image:
    image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((8, 8, 56, 56), radius=12, fill="#2b2b2b")
    draw.ellipse((20, 24, 28, 32), fill="#fff7d6")
    draw.ellipse((36, 24, 44, 32), fill="#fff7d6")
    draw.arc((22, 30, 42, 48), start=10, end=170, fill="#fff7d6", width=3)
    return image


def clean_text(text: str) -> str:
    return text.strip().strip('"').strip("'").strip()
