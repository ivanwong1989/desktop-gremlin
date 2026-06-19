from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator

from .actions import PlayerActionSource, StateChangeOperation


SCHEMA_VERSION = 1


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


class StrictGameModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class VersionedModel(StrictGameModel):
    schema_version: int = Field(default=SCHEMA_VERSION, ge=1, strict=True)


class Choice(StrictGameModel):
    id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    action_text: str = Field(min_length=1)

    @field_validator("id", "label", "action_text")
    @classmethod
    def strip_non_empty(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be empty")
        return value


class CampaignDefinition(VersionedModel):
    id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    initial_lore: str = Field(min_length=1)
    player_premise: str = Field(min_length=1)
    tone: str = Field(min_length=1)
    content_constraints: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @field_validator("id", "title", "initial_lore", "player_premise", "tone")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be empty")
        return value

    @field_validator("content_constraints")
    @classmethod
    def strip_constraints(cls, value: list[str]) -> list[str]:
        return [item.strip() for item in value if item.strip()]


class PlayerAction(VersionedModel):
    source: PlayerActionSource
    text: str = Field(min_length=1)
    choice_id: str | None = None

    @field_validator("text")
    @classmethod
    def strip_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be empty")
        return value

    @field_validator("choice_id")
    @classmethod
    def strip_choice_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("choice_id must not be empty when provided")
        return value

    @model_validator(mode="after")
    def validate_choice_source(self) -> "PlayerAction":
        if self.source == PlayerActionSource.CHOICE and not self.choice_id:
            raise ValueError("choice_id is required when source is choice")
        if self.source == PlayerActionSource.TEXT and self.choice_id is not None:
            raise ValueError("choice_id is only allowed when source is choice")
        return self


class CharacterState(StrictGameModel):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    status: str = Field(min_length=1)
    current_location_id: str | None = None
    attributes: dict[str, JsonValue] = Field(default_factory=dict)

    @field_validator("id", "name", "description", "status")
    @classmethod
    def strip_text_fields(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be empty")
        return value

    @field_validator("current_location_id")
    @classmethod
    def strip_optional_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("current_location_id must not be empty when provided")
        return value


class LocationState(StrictGameModel):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    discovered: bool = False
    attributes: dict[str, JsonValue] = Field(default_factory=dict)

    @field_validator("id", "name", "description")
    @classmethod
    def strip_text_fields(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be empty")
        return value


class ItemDefinition(StrictGameModel):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    attributes: dict[str, JsonValue] = Field(default_factory=dict)

    @field_validator("id", "name", "description")
    @classmethod
    def strip_text_fields(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be empty")
        return value


class InventoryEntry(StrictGameModel):
    item_id: str = Field(min_length=1)
    quantity: int = Field(ge=0, strict=True)
    attributes: dict[str, JsonValue] = Field(default_factory=dict)

    @field_validator("item_id")
    @classmethod
    def strip_item_id(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be empty")
        return value


class QuestState(StrictGameModel):
    id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    description: str = Field(min_length=1)
    status: Literal["not_started", "active", "completed", "failed"]
    stage: str = Field(min_length=1)
    attributes: dict[str, JsonValue] = Field(default_factory=dict)

    @field_validator("id", "title", "description", "stage")
    @classmethod
    def strip_text_fields(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be empty")
        return value


class GameState(VersionedModel):
    player: CharacterState
    characters: dict[str, CharacterState] = Field(default_factory=dict)
    locations: dict[str, LocationState] = Field(default_factory=dict)
    item_definitions: dict[str, ItemDefinition] = Field(default_factory=dict)
    inventory: dict[str, InventoryEntry] = Field(default_factory=dict)
    quests: dict[str, QuestState] = Field(default_factory=dict)
    world_flags: dict[str, JsonValue] = Field(default_factory=dict)
    current_location_id: str = Field(min_length=1)
    present_character_ids: list[str] = Field(default_factory=list)
    game_time: str | None = None
    turn_number: int = Field(default=0, ge=0, strict=True)

    @field_validator("current_location_id")
    @classmethod
    def strip_current_location_id(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be empty")
        return value

    @model_validator(mode="after")
    def validate_references(self) -> "GameState":
        validate_keyed_entities("characters", self.characters)
        validate_keyed_entities("locations", self.locations)
        validate_keyed_entities("item_definitions", self.item_definitions)
        validate_inventory_keys(self.inventory)
        validate_keyed_entities("quests", self.quests)

        if self.player.id in self.characters:
            raise ValueError("player.id must be unique and not repeated in characters")
        if self.current_location_id not in self.locations:
            raise ValueError("current_location_id must reference an existing location")
        if self.player.current_location_id and self.player.current_location_id not in self.locations:
            raise ValueError("player.current_location_id must reference an existing location")

        for character in self.characters.values():
            if character.current_location_id and character.current_location_id not in self.locations:
                raise ValueError(f"character {character.id} references unknown current_location_id")

        for item_id, entry in self.inventory.items():
            if item_id not in self.item_definitions:
                raise ValueError(f"inventory item {item_id} has no item definition")
            if entry.item_id != item_id:
                raise ValueError(f"inventory key {item_id} must match entry.item_id")

        seen_present = set()
        for character_id in self.present_character_ids:
            if not character_id.strip():
                raise ValueError("present_character_ids must not contain empty IDs")
            if character_id in seen_present:
                raise ValueError(f"present_character_ids contains duplicate ID: {character_id}")
            seen_present.add(character_id)
            if character_id != self.player.id and character_id not in self.characters:
                raise ValueError(f"present character {character_id} does not exist")
        return self


class StateChange(StrictGameModel):
    operation: StateChangeOperation
    target_id: str | None = None
    parameters: dict[str, JsonValue] = Field(default_factory=dict)
    reason: str = Field(min_length=1)

    @field_validator("target_id")
    @classmethod
    def strip_target_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("target_id must not be empty when provided")
        return value

    @field_validator("reason")
    @classmethod
    def strip_reason(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("reason must not be empty")
        return value

    @field_validator("parameters")
    @classmethod
    def reject_arbitrary_paths(cls, value: dict[str, JsonValue]) -> dict[str, JsonValue]:
        for key in value:
            if not key.strip():
                raise ValueError("parameter keys must not be empty")
            if "." in key or "[" in key or "]" in key:
                raise ValueError("parameter keys must be structured names, not arbitrary paths")
        return value

    @model_validator(mode="after")
    def validate_operation_shape(self) -> "StateChange":
        operations_requiring_target = {
            StateChangeOperation.REMOVE_FLAG,
            StateChangeOperation.ADD_ITEM,
            StateChangeOperation.REMOVE_ITEM,
            StateChangeOperation.MOVE_CHARACTER,
            StateChangeOperation.UPDATE_CHARACTER,
            StateChangeOperation.DISCOVER_LOCATION,
            StateChangeOperation.UPDATE_QUEST,
            StateChangeOperation.COMPLETE_QUEST,
            StateChangeOperation.FAIL_QUEST,
        }
        operations_without_target = {
            StateChangeOperation.SET_FLAG,
            StateChangeOperation.CREATE_CHARACTER,
            StateChangeOperation.CREATE_LOCATION,
            StateChangeOperation.START_QUEST,
            StateChangeOperation.SET_GAME_TIME,
            StateChangeOperation.ADVANCE_GAME_TIME,
            StateChangeOperation.SET_PRESENT_CHARACTERS,
        }
        if self.operation in operations_requiring_target and not self.target_id:
            raise ValueError(f"target_id is required for {self.operation.value}")
        if self.operation in operations_without_target and self.target_id is not None:
            raise ValueError(f"target_id is not allowed for {self.operation.value}")
        return self


class InitialGameState(VersionedModel):
    opening_narrative: str = Field(min_length=1)
    state: GameState
    initial_choices: list[Choice] = Field(default_factory=list)

    @field_validator("opening_narrative")
    @classmethod
    def strip_opening_narrative(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("opening_narrative must not be empty")
        return value

    @field_validator("initial_choices")
    @classmethod
    def validate_unique_choices(cls, value: list[Choice]) -> list[Choice]:
        validate_unique_ids("initial_choices", [choice.id for choice in value])
        return value


class LoreEntry(StrictGameModel):
    id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    category: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    content: str = Field(min_length=1)
    aliases: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    related_entity_ids: list[str] = Field(default_factory=list)
    evidence_turn_ids: list[str] = Field(default_factory=list)
    source_type: Literal["initial", "dynamic"]

    @field_validator("id", "title", "category", "summary", "content")
    @classmethod
    def strip_text_fields(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be empty")
        return value

    @field_validator("aliases", "tags", "related_entity_ids", "evidence_turn_ids")
    @classmethod
    def strip_string_lists(cls, value: list[str]) -> list[str]:
        return [item.strip() for item in value if item.strip()]


class NarratorTurn(VersionedModel):
    narrative: str = Field(min_length=1)
    choices: list[Choice] = Field(default_factory=list)
    state_changes: list[StateChange] = Field(default_factory=list)
    memory_signals: list[LoreEntry] = Field(default_factory=list)
    image_request: str | None = None

    @field_validator("narrative")
    @classmethod
    def strip_narrative(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("narrative must not be empty")
        return value

    @field_validator("image_request")
    @classmethod
    def strip_image_request(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None

    @field_validator("choices")
    @classmethod
    def validate_unique_choices(cls, value: list[Choice]) -> list[Choice]:
        validate_unique_ids("choices", [choice.id for choice in value])
        return value


class StorySummary(VersionedModel):
    text: str = ""
    updated_at: datetime = Field(default_factory=utc_now)
    covered_turn_ids: list[str] = Field(default_factory=list)


class TurnRecord(VersionedModel):
    id: str = Field(min_length=1)
    turn_number: int = Field(ge=0, strict=True)
    player_action: PlayerAction
    narrator_turn: NarratorTurn
    applied_state_changes: list[StateChange] = Field(default_factory=list)
    state_after: GameState
    created_at: datetime = Field(default_factory=utc_now)


class TurnEvent(VersionedModel):
    id: str = Field(min_length=1)
    game_id: str = Field(min_length=1)
    turn_id: str | None = None
    event_type: str = Field(min_length=1)
    payload: dict[str, JsonValue] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)


class GameSave(VersionedModel):
    campaign: CampaignDefinition
    state: GameState
    initial_lore: list[LoreEntry] = Field(default_factory=list)
    dynamic_lore: list[LoreEntry] = Field(default_factory=list)
    story_summary: StorySummary = Field(default_factory=StorySummary)
    recent_turns: list[TurnRecord] = Field(default_factory=list)
    current_choices: list[Choice] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def validate_lore_and_choices(self) -> "GameSave":
        validate_unique_ids("initial_lore", [entry.id for entry in self.initial_lore])
        validate_unique_ids("dynamic_lore", [entry.id for entry in self.dynamic_lore])
        validate_unique_ids("current_choices", [choice.id for choice in self.current_choices])
        for entry in self.initial_lore:
            if entry.source_type != "initial":
                raise ValueError("initial_lore entries must use source_type='initial'")
        for entry in self.dynamic_lore:
            if entry.source_type != "dynamic":
                raise ValueError("dynamic_lore entries must use source_type='dynamic'")
        return self


class GameMetadata(VersionedModel):
    id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    updated_at: datetime
    turn_number: int = Field(ge=0, strict=True)


class GameViewState(VersionedModel):
    game_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    narrative: str = ""
    choices: list[Choice] = Field(default_factory=list)
    state: GameState
    story_summary: StorySummary = Field(default_factory=StorySummary)
    dynamic_lore: list[LoreEntry] = Field(default_factory=list)

    @field_validator("choices")
    @classmethod
    def validate_unique_choices(cls, value: list[Choice]) -> list[Choice]:
        validate_unique_ids("choices", [choice.id for choice in value])
        return value


def validate_keyed_entities(name: str, entities: dict[str, Any]) -> None:
    for key, entity in entities.items():
        if not key.strip():
            raise ValueError(f"{name} contains an empty key")
        if getattr(entity, "id", None) != key:
            raise ValueError(f"{name} key {key} must match entity.id")


def validate_inventory_keys(inventory: dict[str, InventoryEntry]) -> None:
    for key, entry in inventory.items():
        if not key.strip():
            raise ValueError("inventory contains an empty key")
        if entry.item_id != key:
            raise ValueError(f"inventory key {key} must match entry.item_id")


def validate_unique_ids(name: str, ids: list[str]) -> None:
    seen = set()
    for value in ids:
        if value in seen:
            raise ValueError(f"{name} contains duplicate ID: {value}")
        seen.add(value)
