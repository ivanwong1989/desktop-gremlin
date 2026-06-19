from __future__ import annotations

import tkinter as tk

from desktop_gremlin.game.models import GameViewState


STATE_EMPTY_TEXT = "No active game."


def game_state_lines(view: GameViewState | None) -> list[str]:
    if view is None:
        return [STATE_EMPTY_TEXT]

    state = view.state
    current_location = state.locations[state.current_location_id]
    inventory = [
        f"{state.item_definitions[item_id].name} x{entry.quantity}"
        for item_id, entry in sorted(state.inventory.items())
    ] or ["None"]
    present_characters = [
        state.player.name if character_id == state.player.id else state.characters[character_id].name
        for character_id in state.present_character_ids
        if character_id == state.player.id or character_id in state.characters
    ] or ["None"]
    active_quests = [
        f"{quest.title}: {quest.stage}"
        for quest in state.quests.values()
        if quest.status == "active"
    ] or ["None"]

    return [
        f"Player: {state.player.name} ({state.player.status})",
        f"Location: {current_location.name}",
        f"Inventory: {', '.join(inventory)}",
        f"Present: {', '.join(present_characters)}",
        f"Active quests: {'; '.join(active_quests)}",
        f"Game time: {state.game_time or 'Unspecified'}",
        f"Turn: {state.turn_number}",
    ]


def game_state_text(view: GameViewState | None) -> str:
    return "\n".join(game_state_lines(view))


class GameStatePanel(tk.Frame):
    def __init__(self, parent, **kwargs):
        super().__init__(parent, **kwargs)
        self.text_var = tk.StringVar(value=STATE_EMPTY_TEXT)
        self.label = tk.Label(
            self,
            text="Game State",
            anchor="w",
            font=("Segoe UI", 10, "bold"),
        )
        self.label.grid(row=0, column=0, sticky="ew", padx=8, pady=(8, 2))
        self.value_label = tk.Label(
            self,
            textvariable=self.text_var,
            anchor="nw",
            justify="left",
            wraplength=190,
            font=("Segoe UI", 9),
        )
        self.value_label.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 8))
        self.grid_columnconfigure(0, weight=1)

    def apply_theme(self, bg: str, fg: str, muted: str) -> None:
        self.configure(bg=bg)
        self.label.configure(bg=bg, fg=fg)
        self.value_label.configure(bg=bg, fg=muted)

    def set_view(self, view: GameViewState | None) -> None:
        self.text_var.set(game_state_text(view))
