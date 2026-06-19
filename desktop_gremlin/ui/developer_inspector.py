from __future__ import annotations

import json
import tkinter as tk
from tkinter import messagebox, scrolledtext

from desktop_gremlin.game.models import GameSave, GameViewState, StateChange, TurnEvent
from desktop_gremlin.game.turn_processor import TurnDebugSnapshot


def developer_inspector_text(
    save: GameSave | None,
    view: GameViewState | None,
    debug: TurnDebugSnapshot | None,
    events: list[TurnEvent],
) -> str:
    latest_turn = save.recent_turns[-1] if save and save.recent_turns else None
    latest_player_action = debug.latest_player_action if debug and debug.latest_player_action else (
        latest_turn.player_action if latest_turn else None
    )
    latest_narrator_turn = debug.latest_narrator_turn if debug and debug.latest_narrator_turn else (
        latest_turn.narrator_turn if latest_turn else None
    )
    proposed = debug.proposed_state_changes if debug else []
    applied = debug.applied_state_changes if debug else (latest_turn.applied_state_changes if latest_turn else [])
    context = debug.latest_model_context if debug else []
    failure = debug.validation_failure if debug else None

    sections = [
        ("Complete canonical state", view.state.model_dump(mode="json") if view else None),
        ("Latest player action", latest_player_action.model_dump(mode="json") if latest_player_action else None),
        ("Latest parsed NarratorTurn", latest_narrator_turn.model_dump(mode="json") if latest_narrator_turn else None),
        ("Proposed state changes", [change.model_dump(mode="json") for change in proposed]),
        ("Applied state changes", [change.model_dump(mode="json") for change in applied]),
        ("Validation failures", failure or "None"),
        ("Latest model context", context),
        ("Event-log records", [event.model_dump(mode="json") for event in events]),
        ("Current choices", [choice.model_dump(mode="json") for choice in view.choices] if view else []),
    ]
    return "\n\n".join(f"## {title}\n{json.dumps(value, indent=2)}" for title, value in sections)


class DeveloperInspectorWindow:
    def __init__(self, parent, controller, game_id: str, colors: dict[str, str]):
        self.parent = parent
        self.controller = controller
        self.game_id = game_id
        self.colors = colors
        self.window = tk.Toplevel(parent)
        self.window.title("Game Inspector")
        self.window.geometry("760x680")
        self.window.minsize(580, 460)
        self.window.configure(bg=colors["window"])
        self.window.grid_rowconfigure(0, weight=1)
        self.window.grid_columnconfigure(0, weight=1)

        self.text = scrolledtext.ScrolledText(
            self.window,
            wrap="word",
            bg=colors["panel"],
            fg=colors["text"],
            insertbackground=colors["text"],
            relief="flat",
            padx=12,
            pady=10,
            font=("Consolas", 9),
        )
        self.text.grid(row=0, column=0, sticky="nsew", padx=12, pady=12)
        button_row = tk.Frame(self.window, bg=colors["window"])
        button_row.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 12))
        tk.Button(
            button_row,
            text="Refresh",
            command=self.refresh,
            bg=colors["button"],
            fg=colors["header_text"],
            relief="flat",
            padx=10,
        ).pack(side="left")
        self.refresh()

    def refresh(self) -> None:
        try:
            save = self.controller.load_game(self.game_id)
            view = self.controller.get_game_view(self.game_id)
            debug = self.controller.get_debug_snapshot(self.game_id)
            events = self.controller.list_turn_events(self.game_id)
            text = developer_inspector_text(save, view, debug, events)
        except Exception as exc:
            messagebox.showerror("Game Inspector", str(exc), parent=self.window)
            return
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.insert("end", text)
        self.text.configure(state="disabled")
