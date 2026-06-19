from __future__ import annotations

from .actions import StateChangeOperation
from .errors import InvalidStateChangeError
from .models import CharacterState, GameState, LocationState, QuestState, StateChange
from .state_applier import StateApplier


class StateValidator:
    def __init__(self):
        self.applier = StateApplier()

    def validate_all(self, state: GameState, changes: list[StateChange]) -> None:
        candidate = state.model_copy(deep=True)
        for change in changes:
            self.validate_one(candidate, change)
            self.applier.apply_one(candidate, change)
            GameState.model_validate(candidate.model_dump())

    def validate_one(self, state: GameState, change: StateChange) -> None:
        operation = change.operation
        params = change.parameters

        if operation == StateChangeOperation.SET_FLAG:
            self.require_params(change, {"key"})
            self.ensure_string(params["key"], "key")
        elif operation == StateChangeOperation.REMOVE_FLAG:
            if change.target_id not in state.world_flags:
                raise InvalidStateChangeError(f"Cannot remove unknown flag: {change.target_id}")
        elif operation == StateChangeOperation.ADD_ITEM:
            item_id = str(change.target_id)
            if item_id not in state.item_definitions:
                raise InvalidStateChangeError(f"Cannot add undefined item: {item_id}")
            quantity = self.quantity(params)
            if quantity <= 0:
                raise InvalidStateChangeError("add_item quantity must be positive")
        elif operation == StateChangeOperation.REMOVE_ITEM:
            item_id = str(change.target_id)
            if item_id not in state.inventory:
                raise InvalidStateChangeError(f"Cannot remove unowned item: {item_id}")
            quantity = self.quantity(params)
            if quantity <= 0:
                raise InvalidStateChangeError("remove_item quantity must be positive")
            if state.inventory[item_id].quantity - quantity < 0:
                raise InvalidStateChangeError(f"Cannot reduce inventory below zero for item: {item_id}")
        elif operation == StateChangeOperation.MOVE_CHARACTER:
            self.require_params(change, {"location_id"})
            location_id = str(params["location_id"])
            if location_id not in state.locations:
                raise InvalidStateChangeError(f"Cannot move to unknown location: {location_id}")
            self.require_character(state, str(change.target_id))
        elif operation == StateChangeOperation.CREATE_CHARACTER:
            self.require_params(change, {"character"})
            character = CharacterState.model_validate(params["character"])
            if character.id == state.player.id or character.id in state.characters:
                raise InvalidStateChangeError(f"Cannot create duplicate character: {character.id}")
            if character.current_location_id and character.current_location_id not in state.locations:
                raise InvalidStateChangeError(f"Character references unknown location: {character.current_location_id}")
        elif operation == StateChangeOperation.UPDATE_CHARACTER:
            self.require_character(state, str(change.target_id))
            self.reject_protected(params, {"id"})
            self.ensure_allowed(params, {"name", "description", "status", "current_location_id", "attributes"})
            if "current_location_id" in params and params["current_location_id"] not in state.locations:
                raise InvalidStateChangeError(f"Character update references unknown location: {params['current_location_id']}")
        elif operation == StateChangeOperation.CREATE_LOCATION:
            self.require_params(change, {"location"})
            location = LocationState.model_validate(params["location"])
            if location.id in state.locations:
                raise InvalidStateChangeError(f"Cannot create duplicate location: {location.id}")
        elif operation == StateChangeOperation.DISCOVER_LOCATION:
            if change.target_id not in state.locations:
                raise InvalidStateChangeError(f"Cannot discover unknown location: {change.target_id}")
        elif operation == StateChangeOperation.START_QUEST:
            self.require_params(change, {"quest"})
            quest = QuestState.model_validate(params["quest"])
            if quest.id in state.quests:
                raise InvalidStateChangeError(f"Cannot create duplicate quest: {quest.id}")
        elif operation == StateChangeOperation.UPDATE_QUEST:
            self.require_quest(state, str(change.target_id))
            self.reject_protected(params, {"id"})
            self.ensure_allowed(params, {"title", "description", "status", "stage", "attributes"})
        elif operation in {StateChangeOperation.COMPLETE_QUEST, StateChangeOperation.FAIL_QUEST}:
            self.require_quest(state, str(change.target_id))
        elif operation in {StateChangeOperation.SET_GAME_TIME, StateChangeOperation.ADVANCE_GAME_TIME}:
            self.require_params(change, {"value"})
            self.ensure_string(params["value"], "value")
        elif operation == StateChangeOperation.SET_PRESENT_CHARACTERS:
            self.require_params(change, {"character_ids"})
            character_ids = params["character_ids"]
            if not isinstance(character_ids, list) or not all(isinstance(item, str) and item.strip() for item in character_ids):
                raise InvalidStateChangeError("set_present_characters requires non-empty string character_ids")
            if len(set(character_ids)) != len(character_ids):
                raise InvalidStateChangeError("set_present_characters contains duplicate character IDs")
            for character_id in character_ids:
                self.require_character(state, character_id)

    def require_character(self, state: GameState, character_id: str) -> None:
        if character_id != state.player.id and character_id not in state.characters:
            raise InvalidStateChangeError(f"Unknown character: {character_id}")

    def require_quest(self, state: GameState, quest_id: str) -> None:
        if quest_id not in state.quests:
            raise InvalidStateChangeError(f"Unknown quest: {quest_id}")

    def require_params(self, change: StateChange, required: set[str]) -> None:
        missing = required - set(change.parameters)
        if missing:
            raise InvalidStateChangeError(f"{change.operation.value} missing parameters: {', '.join(sorted(missing))}")

    def reject_protected(self, params: dict, protected: set[str]) -> None:
        blocked = protected & set(params)
        if blocked:
            raise InvalidStateChangeError(f"Cannot modify protected fields: {', '.join(sorted(blocked))}")

    def ensure_allowed(self, params: dict, allowed: set[str]) -> None:
        extra = set(params) - allowed
        if extra:
            raise InvalidStateChangeError(f"Unsupported state-change parameters: {', '.join(sorted(extra))}")

    def ensure_string(self, value, name: str) -> None:
        if not isinstance(value, str) or not value.strip():
            raise InvalidStateChangeError(f"{name} must be a non-empty string")

    def quantity(self, params: dict) -> int:
        value = params.get("quantity", 1)
        if not isinstance(value, int):
            raise InvalidStateChangeError("quantity must be an integer")
        return value
