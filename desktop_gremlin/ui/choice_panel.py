from __future__ import annotations

import tkinter as tk
from typing import Callable

from desktop_gremlin.game.models import Choice


class ChoicePanelState:
    def __init__(self):
        self.choices_by_id: dict[str, Choice] = {}
        self.enabled = True

    def set_choices(self, choices: list[Choice]) -> None:
        self.choices_by_id = {choice.id: choice for choice in choices}
        self.enabled = True

    def clear_choices(self) -> None:
        self.choices_by_id = {}

    def set_enabled(self, enabled: bool) -> None:
        self.enabled = enabled

    def choose(self, choice_id: str) -> Choice | None:
        if not self.enabled:
            return None
        choice = self.choices_by_id.get(choice_id)
        if choice is None:
            raise ValueError(f"Unknown or stale choice ID: {choice_id}")
        self.enabled = False
        return choice


class ChoicePanel(tk.Frame):
    def __init__(self, parent, on_choice: Callable[[Choice], None], **kwargs):
        super().__init__(parent, **kwargs)
        self.on_choice = on_choice
        self.state_model = ChoicePanelState()
        self.buttons: dict[str, tk.Button] = {}
        self.colors = {
            "bg": kwargs.get("bg", "#ffffff"),
            "button_bg": "#3c3c3c",
            "button_fg": "#ffffff",
            "active_bg": "#505050",
        }

    def apply_theme(self, bg: str, button_bg: str, button_fg: str, active_bg: str) -> None:
        self.colors = {
            "bg": bg,
            "button_bg": button_bg,
            "button_fg": button_fg,
            "active_bg": active_bg,
        }
        self.configure(bg=bg)
        self.render()

    def set_choices(self, choices: list[Choice]) -> None:
        self.state_model.set_choices(choices)
        self.render()

    def clear_choices(self) -> None:
        self.state_model.clear_choices()
        self.render()

    def set_enabled(self, enabled: bool) -> None:
        self.state_model.set_enabled(enabled)
        state = "normal" if enabled else "disabled"
        for button in self.buttons.values():
            button.configure(state=state)

    def render(self) -> None:
        for child in self.winfo_children():
            child.destroy()
        self.buttons = {}
        if not self.state_model.choices_by_id:
            self.grid_remove()
            return

        self.grid()
        for index, choice in enumerate(self.state_model.choices_by_id.values()):
            button = tk.Button(
                self,
                text=choice.label,
                command=lambda choice_id=choice.id: self.handle_click(choice_id),
                bg=self.colors["button_bg"],
                fg=self.colors["button_fg"],
                activebackground=self.colors["active_bg"],
                activeforeground=self.colors["button_fg"],
                relief="flat",
                padx=10,
                pady=5,
                wraplength=220,
                justify="left",
            )
            button.grid(row=index // 3, column=index % 3, sticky="ew", padx=(0, 8), pady=(0, 6))
            self.grid_columnconfigure(index % 3, weight=1)
            self.buttons[choice.id] = button
        self.set_enabled(self.state_model.enabled)

    def handle_click(self, choice_id: str) -> None:
        choice = self.state_model.choose(choice_id)
        if choice is None:
            return
        self.set_enabled(False)
        self.on_choice(choice)
