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
        params = change.parameters.model_dump(exclude_none=True)

        if operation == StateChangeOperation.SET_FLAG:
            pass
        elif operation == StateChangeOperation.REMOVE_FLAG:
            if change.target_id not in state.world_flags:
                raise InvalidStateChangeError(f"Cannot remove unknown flag: {change.target_id}")
        elif operation == StateChangeOperation.ADD_ITEM:
            item_id = str(change.target_id)
            if item_id not in state.item_definitions:
                raise InvalidStateChangeError(f"Cannot add undefined item: {item_id}")
            quantity = params["quantity"]
        elif operation == StateChangeOperation.REMOVE_ITEM:
            item_id = str(change.target_id)
            if item_id not in state.inventory:
                raise InvalidStateChangeError(f"Cannot remove unowned item: {item_id}")
            quantity = params["quantity"]
            if state.inventory[item_id].quantity - quantity < 0:
                raise InvalidStateChangeError(f"Cannot reduce inventory below zero for item: {item_id}")
        elif operation == StateChangeOperation.MOVE_CHARACTER:
            location_id = str(params["location_id"])
            if location_id not in state.locations:
                raise InvalidStateChangeError(f"Cannot move to unknown location: {location_id}")
            self.require_character(state, str(change.target_id))
        elif operation == StateChangeOperation.CREATE_CHARACTER:
            character = CharacterState.model_validate(params)
            if character.id == state.player.id or character.id in state.characters:
                raise InvalidStateChangeError(f"Cannot create duplicate character: {character.id}")
            if character.current_location_id and character.current_location_id not in state.locations:
                raise InvalidStateChangeError(f"Character references unknown location: {character.current_location_id}")
        elif operation == StateChangeOperation.UPDATE_CHARACTER:
            self.require_character(state, str(change.target_id))
            if "current_location_id" in params and params["current_location_id"] not in state.locations:
                raise InvalidStateChangeError(f"Character update references unknown location: {params['current_location_id']}")
        elif operation == StateChangeOperation.CREATE_LOCATION:
            location = LocationState.model_validate(params)
            if location.id in state.locations:
                raise InvalidStateChangeError(f"Cannot create duplicate location: {location.id}")
        elif operation == StateChangeOperation.DISCOVER_LOCATION:
            if change.target_id not in state.locations:
                raise InvalidStateChangeError(f"Cannot discover unknown location: {change.target_id}")
        elif operation == StateChangeOperation.START_QUEST:
            quest = QuestState.model_validate(params)
            if quest.id in state.quests:
                raise InvalidStateChangeError(f"Cannot create duplicate quest: {quest.id}")
        elif operation == StateChangeOperation.UPDATE_QUEST:
            self.require_quest(state, str(change.target_id))
        elif operation in {StateChangeOperation.COMPLETE_QUEST, StateChangeOperation.FAIL_QUEST}:
            self.require_quest(state, str(change.target_id))
        elif operation in {StateChangeOperation.SET_GAME_TIME, StateChangeOperation.ADVANCE_GAME_TIME}:
            pass
        elif operation == StateChangeOperation.SET_PRESENT_CHARACTERS:
            character_ids = params["character_ids"]
            for character_id in character_ids:
                self.require_character(state, character_id)

    def require_character(self, state: GameState, character_id: str) -> None:
        if character_id != state.player.id and character_id not in state.characters:
            raise InvalidStateChangeError(f"Unknown character: {character_id}")

    def require_quest(self, state: GameState, quest_id: str) -> None:
        if quest_id not in state.quests:
            raise InvalidStateChangeError(f"Unknown quest: {quest_id}")
