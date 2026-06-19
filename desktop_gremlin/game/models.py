from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Any, ClassVar, Literal, TypeAlias, get_args

from pydantic import BaseModel, ConfigDict, Field, JsonValue, TypeAdapter, field_validator, model_validator

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


class StateChangeParameters(StrictGameModel):
    """Base for operation-specific parameter objects."""


class EmptyParameters(StateChangeParameters):
    pass


class SetFlagParameters(StateChangeParameters):
    key: str = Field(min_length=1)
    value: JsonValue = True


class QuantityParameters(StateChangeParameters):
    quantity: int = Field(default=1, gt=0, strict=True)


class MoveCharacterParameters(StateChangeParameters):
    location_id: str = Field(min_length=1)


class CreateCharacterParameters(StateChangeParameters):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    status: str = Field(min_length=1)
    current_location_id: str | None = None
    attributes: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def accept_legacy_character_wrapper(cls, value: Any) -> Any:
        if isinstance(value, dict) and set(value) == {"character"} and isinstance(value["character"], dict):
            return value["character"]
        return value


class UpdateCharacterParameters(StateChangeParameters):
    name: str = Field(default=None, min_length=1)
    description: str = Field(default=None, min_length=1)
    status: str = Field(default=None, min_length=1)
    current_location_id: str = Field(default=None, min_length=1)
    attributes: dict[str, JsonValue] = None

    @model_validator(mode="after")
    def require_update(self) -> "UpdateCharacterParameters":
        if not self.model_fields_set:
            raise ValueError("at least one character field must be provided")
        return self


class CreateLocationParameters(StateChangeParameters):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    discovered: bool = False
    attributes: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def accept_legacy_location_wrapper(cls, value: Any) -> Any:
        if isinstance(value, dict) and set(value) == {"location"} and isinstance(value["location"], dict):
            return value["location"]
        return value


class StartQuestParameters(StateChangeParameters):
    id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    description: str = Field(min_length=1)
    status: Literal["not_started", "active", "completed", "failed"]
    stage: str = Field(min_length=1)
    attributes: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def accept_legacy_quest_wrapper(cls, value: Any) -> Any:
        if isinstance(value, dict) and set(value) == {"quest"} and isinstance(value["quest"], dict):
            return value["quest"]
        return value


class UpdateQuestParameters(StateChangeParameters):
    title: str = Field(default=None, min_length=1)
    description: str = Field(default=None, min_length=1)
    status: Literal["not_started", "active", "completed", "failed"] = None
    stage: str = Field(default=None, min_length=1)
    attributes: dict[str, JsonValue] = None

    @model_validator(mode="after")
    def require_update(self) -> "UpdateQuestParameters":
        if not self.model_fields_set:
            raise ValueError("at least one quest field must be provided")
        return self


class GameTimeParameters(StateChangeParameters):
    value: str = Field(min_length=1)


class PresentCharactersParameters(StateChangeParameters):
    character_ids: list[str]

    @field_validator("character_ids")
    @classmethod
    def validate_character_ids(cls, value: list[str]) -> list[str]:
        stripped = [item.strip() for item in value]
        if any(not item for item in stripped):
            raise ValueError("character_ids must contain non-empty strings")
        if len(set(stripped)) != len(stripped):
            raise ValueError("character_ids must not contain duplicates")
        return stripped


class StateChangeBase(StrictGameModel):
    entity_requirement: ClassVar[str] = "none"
    creates_entity: ClassVar[bool] = False
    reason: str = Field(min_length=1)

    @field_validator("reason")
    @classmethod
    def strip_reason(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("reason must not be empty")
        return value

class TargetedStateChange(StateChangeBase):
    target_id: str = Field(min_length=1)

    @field_validator("target_id")
    @classmethod
    def strip_target_id(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("target_id must not be empty")
        return value


class SetFlagChange(StateChangeBase):
    operation: Literal[StateChangeOperation.SET_FLAG]
    parameters: SetFlagParameters


class RemoveFlagChange(TargetedStateChange):
    operation: Literal[StateChangeOperation.REMOVE_FLAG]
    parameters: EmptyParameters = Field(default_factory=EmptyParameters)
    entity_requirement: ClassVar[str] = "world flag target_id must exist"


class AddItemChange(TargetedStateChange):
    operation: Literal[StateChangeOperation.ADD_ITEM]
    parameters: QuantityParameters = Field(default_factory=QuantityParameters)
    entity_requirement: ClassVar[str] = "item definition target_id must exist"


class RemoveItemChange(TargetedStateChange):
    operation: Literal[StateChangeOperation.REMOVE_ITEM]
    parameters: QuantityParameters = Field(default_factory=QuantityParameters)
    entity_requirement: ClassVar[str] = "inventory item target_id must exist"


class MoveCharacterChange(TargetedStateChange):
    operation: Literal[StateChangeOperation.MOVE_CHARACTER]
    parameters: MoveCharacterParameters
    entity_requirement: ClassVar[str] = "character target_id and parameters.location_id must exist"


class CreateCharacterChange(StateChangeBase):
    operation: Literal[StateChangeOperation.CREATE_CHARACTER]
    parameters: CreateCharacterParameters
    entity_requirement: ClassVar[str] = "parameters.current_location_id must exist when provided"
    creates_entity: ClassVar[bool] = True


class UpdateCharacterChange(TargetedStateChange):
    operation: Literal[StateChangeOperation.UPDATE_CHARACTER]
    parameters: UpdateCharacterParameters
    entity_requirement: ClassVar[str] = "character target_id and any current_location_id must exist"


class CreateLocationChange(StateChangeBase):
    operation: Literal[StateChangeOperation.CREATE_LOCATION]
    parameters: CreateLocationParameters
    creates_entity: ClassVar[bool] = True


class DiscoverLocationChange(TargetedStateChange):
    operation: Literal[StateChangeOperation.DISCOVER_LOCATION]
    parameters: EmptyParameters = Field(default_factory=EmptyParameters)
    entity_requirement: ClassVar[str] = "location target_id must exist"


class StartQuestChange(StateChangeBase):
    operation: Literal[StateChangeOperation.START_QUEST]
    parameters: StartQuestParameters
    creates_entity: ClassVar[bool] = True


class UpdateQuestChange(TargetedStateChange):
    operation: Literal[StateChangeOperation.UPDATE_QUEST]
    parameters: UpdateQuestParameters
    entity_requirement: ClassVar[str] = "quest target_id must exist"


class CompleteQuestChange(TargetedStateChange):
    operation: Literal[StateChangeOperation.COMPLETE_QUEST]
    parameters: EmptyParameters = Field(default_factory=EmptyParameters)
    entity_requirement: ClassVar[str] = "quest target_id must exist"


class FailQuestChange(TargetedStateChange):
    operation: Literal[StateChangeOperation.FAIL_QUEST]
    parameters: EmptyParameters = Field(default_factory=EmptyParameters)
    entity_requirement: ClassVar[str] = "quest target_id must exist"


class SetGameTimeChange(StateChangeBase):
    operation: Literal[StateChangeOperation.SET_GAME_TIME]
    parameters: GameTimeParameters


class AdvanceGameTimeChange(StateChangeBase):
    operation: Literal[StateChangeOperation.ADVANCE_GAME_TIME]
    parameters: GameTimeParameters


class SetPresentCharactersChange(StateChangeBase):
    operation: Literal[StateChangeOperation.SET_PRESENT_CHARACTERS]
    parameters: PresentCharactersParameters
    entity_requirement: ClassVar[str] = "every parameters.character_ids entry must exist"


STATE_CHANGE_MODELS = (
    SetFlagChange, RemoveFlagChange, AddItemChange, RemoveItemChange, MoveCharacterChange,
    CreateCharacterChange, UpdateCharacterChange, CreateLocationChange, DiscoverLocationChange,
    StartQuestChange, UpdateQuestChange, CompleteQuestChange, FailQuestChange,
    SetGameTimeChange, AdvanceGameTimeChange, SetPresentCharactersChange,
)

StateChange: TypeAlias = Annotated[
    SetFlagChange | RemoveFlagChange | AddItemChange | RemoveItemChange | MoveCharacterChange
    | CreateCharacterChange | UpdateCharacterChange | CreateLocationChange | DiscoverLocationChange
    | StartQuestChange | UpdateQuestChange | CompleteQuestChange | FailQuestChange
    | SetGameTimeChange | AdvanceGameTimeChange | SetPresentCharactersChange,
    Field(discriminator="operation"),
]
STATE_CHANGE_ADAPTER = TypeAdapter(StateChange)


def parse_state_change(value: Any) -> StateChange:
    """Validate one state change outside a containing NarratorTurn."""
    return STATE_CHANGE_ADAPTER.validate_python(value)


def state_change_operation_reference() -> str:
    """Build prompt guidance from the same models that generate the JSON schema."""
    lines: list[str] = []
    for model in STATE_CHANGE_MODELS:
        operation = get_args(model.model_fields["operation"].annotation)[0]
        operation_name = operation.value if isinstance(operation, StateChangeOperation) else str(operation)
        target_rule = "required" if "target_id" in model.model_fields else "forbidden"
        parameters_model = model.model_fields["parameters"].annotation
        parameter_schema = parameters_model.model_json_schema()
        required = set(parameter_schema.get("required", []))
        fields = []
        for name, schema in parameter_schema.get("properties", {}).items():
            requirement = "required" if name in required else "optional"
            fields.append(f"{name}:{_json_schema_type(schema)} {requirement}")
        parameter_text = ", ".join(fields) if fields else "none"
        creates = "; creates a new entity" if model.creates_entity else ""
        lines.append(
            f"- {operation_name}: target_id {target_rule}; parameters {{{parameter_text}}}; "
            f"existing state: {model.entity_requirement}{creates}."
        )
    return "\n".join(lines)


def _json_schema_type(schema: dict[str, Any]) -> str:
    if "$ref" in schema:
        return schema["$ref"].rsplit("/", 1)[-1]
    if "type" in schema:
        value = schema["type"]
        return "/".join(value) if isinstance(value, list) else str(value)
    if "anyOf" in schema:
        return "/".join(dict.fromkeys(_json_schema_type(item) for item in schema["anyOf"]))
    return "value"


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
