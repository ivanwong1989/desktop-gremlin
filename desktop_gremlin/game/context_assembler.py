from __future__ import annotations

import json

from .models import GameSave, PlayerAction, state_change_operation_reference
from .schemas import NARRATOR_TURN_SCHEMA


class ContextAssembler:
    def __init__(self, max_recent_turns: int = 6):
        self.max_recent_turns = max_recent_turns

    def build_messages(self, save: GameSave, action: PlayerAction) -> list[dict[str, str]]:
        return [
            {
                "role": "system",
                "content": (
                    "You are the narrator for a turn-by-turn storytelling game. "
                    "Return only a complete NarratorTurn JSON object. "
                    "Never invent fields outside the schema. Do not stream prose outside JSON. "
                    "Python owns canonical state."
                ),
            },
            {"role": "user", "content": self.build_context_text(save, action)},
        ]

    def build_context_text(self, save: GameSave, action: PlayerAction) -> str:
        state = save.state
        current_location = state.locations[state.current_location_id]
        recent_turns = save.recent_turns[-self.max_recent_turns :]
        sections = [
            (
                "Narrator rules",
                "\n".join(
                    [
                        "Propose narrative, choices, and approved state_changes only.",
                        "Never invent fields outside the schema.",
                        "For create operations, put the new entity ID in parameters.id.",
                        "Do not provide target_id for create_location or create_character.",
                        "For operations acting on existing entities, use target_id where required.",
                        "State changes are applied sequentially in array order.",
                        "Return only a complete NarratorTurn JSON object.",
                    ]
                ),
            ),
            ("Campaign premise", self.campaign_text(save)),
            ("Relevant initial canon", self.lore_text(save.initial_lore)),
            ("Canonical current state", json.dumps(state.model_dump(mode="json"), indent=2)),
            (
                "Current scene",
                json.dumps(
                    {
                        "location": current_location.model_dump(mode="json"),
                        "present_character_ids": state.present_character_ids,
                        "current_choices": [choice.model_dump(mode="json") for choice in save.current_choices],
                    },
                    indent=2,
                ),
            ),
            ("Relevant dynamic lore", self.lore_text(save.dynamic_lore)),
            ("Rolling summary", save.story_summary.text),
            ("Recent turns", self.turns_text(recent_turns)),
            ("Current player action", action.model_dump_json(indent=2)),
            ("State-change operation reference", state_change_operation_reference()),
            (
                "Valid state-change examples",
                json.dumps(
                    [
                        {
                            "operation": "create_location",
                            "parameters": {
                                "id": "office-pantry",
                                "name": "Office Pantry",
                                "description": "A small pantry near the office floor.",
                                "discovered": True,
                                "attributes": {},
                            },
                            "reason": "Ivan walks to the pantry to get coffee.",
                        },
                        {
                            "operation": "move_character",
                            "target_id": "ivan",
                            "parameters": {"location_id": "office-pantry"},
                            "reason": "Ivan enters the pantry.",
                        },
                    ],
                    indent=2,
                ),
            ),
            ("Required output schema", json.dumps(NARRATOR_TURN_SCHEMA, indent=2)),
        ]
        return "\n\n".join(f"## {title}\n{content}" for title, content in sections)

    def campaign_text(self, save: GameSave) -> str:
        campaign = save.campaign
        return "\n".join(
            [
                f"Title: {campaign.title}",
                f"Player premise: {campaign.player_premise}",
                f"Tone/style: {campaign.tone}",
                f"Content constraints: {json.dumps(campaign.content_constraints)}",
            ]
        )

    def lore_text(self, lore_entries) -> str:
        if not lore_entries:
            return "None"
        return "\n".join(f"- {entry.title}: {entry.content}" for entry in lore_entries)

    def turns_text(self, turns) -> str:
        if not turns:
            return "None"
        lines = []
        for turn in turns:
            lines.append(
                f"- Turn {turn.turn_number}: player={turn.player_action.text!r}; narrative={turn.narrator_turn.narrative!r}"
            )
        return "\n".join(lines)
