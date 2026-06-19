from __future__ import annotations

from copy import deepcopy

from .actions import StateChangeOperation
from .models import CharacterState, GameState, InventoryEntry, ItemDefinition, LocationState, QuestState, StateChange


class StateApplier:
    def apply_all(self, state: GameState, changes: list[StateChange]) -> GameState:
        candidate = state.model_copy(deep=True)
        for change in changes:
            self.apply_one(candidate, change)
        return GameState.model_validate(candidate.model_dump())

    def apply_one(self, state: GameState, change: StateChange) -> None:
        operation = change.operation
        params = deepcopy(change.parameters)

        if operation == StateChangeOperation.SET_FLAG:
            state.world_flags[str(params["key"])] = params.get("value", True)
        elif operation == StateChangeOperation.REMOVE_FLAG:
            state.world_flags.pop(str(change.target_id), None)
        elif operation == StateChangeOperation.ADD_ITEM:
            item_id = str(change.target_id)
            quantity = int(params.get("quantity", 1))
            if item_id in state.inventory:
                state.inventory[item_id].quantity += quantity
            else:
                state.inventory[item_id] = InventoryEntry(item_id=item_id, quantity=quantity)
        elif operation == StateChangeOperation.REMOVE_ITEM:
            item_id = str(change.target_id)
            quantity = int(params.get("quantity", 1))
            state.inventory[item_id].quantity -= quantity
            if state.inventory[item_id].quantity == 0:
                del state.inventory[item_id]
        elif operation == StateChangeOperation.MOVE_CHARACTER:
            character = state.player if change.target_id == state.player.id else state.characters[str(change.target_id)]
            character.current_location_id = str(params["location_id"])
            if change.target_id == state.player.id:
                state.current_location_id = str(params["location_id"])
        elif operation == StateChangeOperation.CREATE_CHARACTER:
            character = CharacterState.model_validate(params["character"])
            state.characters[character.id] = character
        elif operation == StateChangeOperation.UPDATE_CHARACTER:
            character = state.player if change.target_id == state.player.id else state.characters[str(change.target_id)]
            self.update_model_fields(character, params, {"name", "description", "status", "current_location_id", "attributes"})
        elif operation == StateChangeOperation.CREATE_LOCATION:
            location = LocationState.model_validate(params["location"])
            state.locations[location.id] = location
        elif operation == StateChangeOperation.DISCOVER_LOCATION:
            state.locations[str(change.target_id)].discovered = True
        elif operation == StateChangeOperation.START_QUEST:
            quest = QuestState.model_validate(params["quest"])
            state.quests[quest.id] = quest
        elif operation == StateChangeOperation.UPDATE_QUEST:
            quest = state.quests[str(change.target_id)]
            self.update_model_fields(quest, params, {"title", "description", "status", "stage", "attributes"})
        elif operation == StateChangeOperation.COMPLETE_QUEST:
            state.quests[str(change.target_id)].status = "completed"
        elif operation == StateChangeOperation.FAIL_QUEST:
            state.quests[str(change.target_id)].status = "failed"
        elif operation == StateChangeOperation.SET_GAME_TIME:
            state.game_time = str(params["value"])
        elif operation == StateChangeOperation.ADVANCE_GAME_TIME:
            state.game_time = str(params["value"])
        elif operation == StateChangeOperation.SET_PRESENT_CHARACTERS:
            state.present_character_ids = list(params["character_ids"])

    def update_model_fields(self, model, params: dict, allowed_fields: set[str]) -> None:
        for key, value in params.items():
            if key in allowed_fields:
                setattr(model, key, value)
