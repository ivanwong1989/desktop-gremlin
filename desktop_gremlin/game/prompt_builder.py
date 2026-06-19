from __future__ import annotations

import json

from .models import CampaignDefinition
from .schemas import INITIAL_GAME_STATE_SCHEMA


def build_initial_state_messages(campaign: CampaignDefinition) -> list[dict[str, str]]:
    schema_json = json.dumps(INITIAL_GAME_STATE_SCHEMA, indent=2)
    return [
        {
            "role": "system",
            "content": (
                "You generate strict JSON for a turn-by-turn storytelling game. "
                "Return only valid JSON. Do not wrap it in Markdown. "
                "Python code owns canonical state; you only propose the initial state."
            ),
        },
        {
            "role": "user",
            "content": (
                "Create an InitialGameState JSON object for this campaign.\n\n"
                "Rules:\n"
                "- Obey the user's initial lore exactly.\n"
                "- Do not rewrite or contradict the initial canon.\n"
                "- Create stable string IDs using lowercase words, numbers, and hyphens.\n"
                "- Create a manageable starting cast.\n"
                "- Create only immediately relevant locations, items, and quests.\n"
                "- Include an opening_narrative.\n"
                "- Optionally include initial_choices.\n"
                "- Return only the required structured result.\n\n"
                f"Campaign title: {campaign.title}\n"
                f"Initial lore:\n{campaign.initial_lore}\n\n"
                f"Player premise:\n{campaign.player_premise}\n\n"
                f"Tone/style: {campaign.tone}\n"
                f"Content constraints: {json.dumps(campaign.content_constraints)}\n\n"
                f"Required JSON schema:\n{schema_json}"
            ),
        },
    ]


def build_initial_state_repair_messages(
    campaign: CampaignDefinition,
    malformed_response: str,
    validation_errors: str,
) -> list[dict[str, str]]:
    schema_json = json.dumps(INITIAL_GAME_STATE_SCHEMA, indent=2)
    return [
        {
            "role": "system",
            "content": (
                "Repair invalid InitialGameState JSON. Return only valid JSON. "
                "Do not include Markdown or explanation."
            ),
        },
        {
            "role": "user",
            "content": (
                "The previous response failed validation. Produce a corrected InitialGameState.\n\n"
                "Keep the campaign canon unchanged.\n\n"
                f"Campaign title: {campaign.title}\n"
                f"Initial lore:\n{campaign.initial_lore}\n\n"
                f"Player premise:\n{campaign.player_premise}\n"
                f"Tone/style: {campaign.tone}\n"
                f"Content constraints: {json.dumps(campaign.content_constraints)}\n\n"
                f"Validation errors:\n{validation_errors}\n\n"
                f"Malformed response:\n{malformed_response}\n\n"
                f"Required JSON schema:\n{schema_json}"
            ),
        },
    ]
