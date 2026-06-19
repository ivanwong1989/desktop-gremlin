from __future__ import annotations

import pytest
from pydantic import ValidationError

from desktop_gremlin.game.actions import PlayerActionSource, StateChangeOperation
from desktop_gremlin.game.models import (
    CampaignDefinition,
    CharacterState,
    Choice,
    GameSave,
    GameState,
    InitialGameState,
    InventoryEntry,
    ItemDefinition,
    LocationState,
    LoreEntry,
    NarratorTurn,
    PlayerAction,
    QuestState,
    StateChange,
    StorySummary,
)
from desktop_gremlin.game.schemas import INITIAL_GAME_STATE_SCHEMA, NARRATOR_TURN_SCHEMA


def sample_state() -> GameState:
    return GameState(
        player=CharacterState(
            id="player",
            name="Mira",
            description="A courier with a sealed letter.",
            status="healthy",
            current_location_id="crossroads",
        ),
        characters={
            "guard": CharacterState(
                id="guard",
                name="Gate Guard",
                description="A tired guard watching the road.",
                status="alert",
                current_location_id="crossroads",
            )
        },
        locations={
            "crossroads": LocationState(
                id="crossroads",
                name="Old Crossroads",
                description="Four muddy roads meet beneath a leaning sign.",
                discovered=True,
            )
        },
        item_definitions={
            "letter": ItemDefinition(
                id="letter",
                name="Sealed Letter",
                description="A wax-sealed message.",
            )
        },
        inventory={
            "letter": InventoryEntry(item_id="letter", quantity=1),
        },
        quests={
            "deliver-letter": QuestState(
                id="deliver-letter",
                title="Deliver the Letter",
                description="Bring the letter to the abbey.",
                status="active",
                stage="Find the abbey road.",
            )
        },
        world_flags={"weather": "rain"},
        current_location_id="crossroads",
        present_character_ids=["player", "guard"],
        game_time="Dusk",
        turn_number=0,
    )


def test_valid_initial_game_state_parses() -> None:
    initial = InitialGameState(
        opening_narrative="Rain ticks against the old crossroads sign.",
        state=sample_state(),
        initial_choices=[
            Choice(id="ask-guard", label="Ask the guard", action_text="Ask the guard about the abbey road.")
        ],
    )

    assert initial.schema_version == 1
    assert initial.state.inventory["letter"].quantity == 1
    assert initial.initial_choices[0].action_text.startswith("Ask")


def test_campaign_and_save_include_schema_versions() -> None:
    campaign = CampaignDefinition(
        id="campaign-1",
        title="The Rain Road",
        initial_lore="The abbey controls the old northern road.",
        player_premise="A courier carrying a sealed letter.",
        tone="Low fantasy mystery",
        content_constraints=["No graphic gore"],
    )
    save = GameSave(
        campaign=campaign,
        state=sample_state(),
        initial_lore=[
            LoreEntry(
                id="abbey-lore",
                title="The Abbey",
                category="place",
                summary="The abbey controls the northern road.",
                content="The abbey keeps toll records and old maps.",
                source_type="initial",
            )
        ],
        story_summary=StorySummary(text="Mira has just reached the crossroads."),
    )

    dumped = save.model_dump(mode="json")

    assert dumped["schema_version"] == 1
    assert dumped["campaign"]["schema_version"] == 1
    assert dumped["state"]["schema_version"] == 1


def test_player_action_requires_choice_id_for_choice_source() -> None:
    with pytest.raises(ValidationError, match="choice_id is required"):
        PlayerAction(source=PlayerActionSource.CHOICE, text="Take the offered route.")


def test_inventory_quantity_cannot_be_negative() -> None:
    with pytest.raises(ValidationError):
        InventoryEntry(item_id="letter", quantity=-1)


def test_inventory_quantity_rejects_string_coercion() -> None:
    with pytest.raises(ValidationError):
        InventoryEntry(item_id="letter", quantity="1")


def test_current_location_must_exist() -> None:
    with pytest.raises(ValidationError, match="current_location_id must reference"):
        GameState(
            player=CharacterState(
                id="player",
                name="Mira",
                description="A courier.",
                status="healthy",
            ),
            locations={},
            current_location_id="missing",
        )


def test_present_character_ids_must_exist() -> None:
    with pytest.raises(ValidationError, match="present character stranger does not exist"):
        state = sample_state()
        GameState(
            **{
                **state.model_dump(),
                "present_character_ids": ["player", "stranger"],
            }
        )


def test_character_location_references_must_exist() -> None:
    with pytest.raises(ValidationError, match="references unknown current_location_id"):
        state = sample_state()
        data = state.model_dump()
        data["characters"]["guard"]["current_location_id"] = "missing"
        GameState(**data)


def test_keyed_entity_ids_must_match_keys() -> None:
    with pytest.raises(ValidationError, match="characters key guard must match entity.id"):
        state = sample_state()
        data = state.model_dump()
        data["characters"]["guard"]["id"] = "different"
        GameState(**data)


def test_invalid_state_change_operation_fails() -> None:
    with pytest.raises(ValidationError):
        StateChange(operation="mutate_any_path", reason="Not allowed.")


def test_state_change_rejects_arbitrary_path_parameters() -> None:
    with pytest.raises(ValidationError, match="not arbitrary paths"):
        StateChange(
            operation=StateChangeOperation.SET_FLAG,
            parameters={"player.stats.strength": 99},
            reason="No arbitrary object paths.",
        )


def test_state_change_requires_target_for_targeted_operations() -> None:
    with pytest.raises(ValidationError, match="target_id is required"):
        StateChange(operation=StateChangeOperation.REMOVE_ITEM, reason="Spent the item.")


def test_empty_narrative_and_empty_choice_label_fail() -> None:
    with pytest.raises(ValidationError, match="narrative"):
        NarratorTurn(narrative=" ")

    with pytest.raises(ValidationError):
        Choice(id="choice-1", label=" ", action_text="Walk north.")


def test_narrator_turn_choice_ids_are_unique() -> None:
    with pytest.raises(ValidationError, match="duplicate ID"):
        NarratorTurn(
            narrative="The road forks.",
            choices=[
                Choice(id="north", label="North", action_text="Go north."),
                Choice(id="north", label="North again", action_text="Go north again."),
            ],
        )


def test_json_schemas_are_available_for_llm_contracts() -> None:
    assert INITIAL_GAME_STATE_SCHEMA["title"] == "InitialGameState"
    assert NARRATOR_TURN_SCHEMA["title"] == "NarratorTurn"
