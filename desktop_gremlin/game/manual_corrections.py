from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from pydantic import ValidationError

from .actions import StateChangeOperation
from .models import GameSave, GameViewState, StateChange, TurnEvent
from .state_applier import StateApplier
from .state_validator import StateValidator
from .turn_processor import view_from_save
from desktop_gremlin.persistence.errors import SaveValidationError
from desktop_gremlin.persistence.repository import GameRepository


class ManualCorrectionService:
    def __init__(
        self,
        repository: GameRepository,
        state_validator: StateValidator | None = None,
        state_applier: StateApplier | None = None,
    ):
        self.repository = repository
        self.state_validator = state_validator or StateValidator()
        self.state_applier = state_applier or StateApplier()

    def apply_correction(self, game_id: str, change: StateChange) -> GameViewState:
        save = self.repository.load_game(game_id)
        self.state_validator.validate_all(save.state, [change])

        candidate = save.model_copy(deep=True)
        candidate.state = self.state_applier.apply_all(candidate.state, [change])
        candidate.updated_at = datetime.now(timezone.utc).replace(microsecond=0)
        try:
            candidate = GameSave.model_validate(candidate.model_dump())
        except ValidationError as exc:
            raise SaveValidationError(f"Manual correction save failed validation: {exc}") from exc

        self.repository.save_game(candidate)
        self.repository.append_turn_event(
            TurnEvent(
                id=f"event-{uuid4().hex[:12]}",
                game_id=game_id,
                event_type="manual_correction",
                payload={"state_change": change.model_dump(mode="json")},
            )
        )
        return view_from_save(candidate)

    def add_item(self, game_id: str, item_id: str, quantity: int, reason: str) -> GameViewState:
        return self.apply_correction(
            game_id,
            StateChange(
                operation=StateChangeOperation.ADD_ITEM,
                target_id=item_id,
                parameters={"quantity": quantity},
                reason=reason,
            ),
        )

    def remove_item(self, game_id: str, item_id: str, quantity: int, reason: str) -> GameViewState:
        return self.apply_correction(
            game_id,
            StateChange(
                operation=StateChangeOperation.REMOVE_ITEM,
                target_id=item_id,
                parameters={"quantity": quantity},
                reason=reason,
            ),
        )

    def move_character(self, game_id: str, character_id: str, location_id: str, reason: str) -> GameViewState:
        return self.apply_correction(
            game_id,
            StateChange(
                operation=StateChangeOperation.MOVE_CHARACTER,
                target_id=character_id,
                parameters={"location_id": location_id},
                reason=reason,
            ),
        )

    def set_flag(self, game_id: str, key: str, value, reason: str) -> GameViewState:
        return self.apply_correction(
            game_id,
            StateChange(
                operation=StateChangeOperation.SET_FLAG,
                parameters={"key": key, "value": value},
                reason=reason,
            ),
        )

    def remove_flag(self, game_id: str, key: str, reason: str) -> GameViewState:
        return self.apply_correction(
            game_id,
            StateChange(
                operation=StateChangeOperation.REMOVE_FLAG,
                target_id=key,
                reason=reason,
            ),
        )

    def adjust_quest_status(self, game_id: str, quest_id: str, status: str, reason: str) -> GameViewState:
        return self.apply_correction(
            game_id,
            StateChange(
                operation=StateChangeOperation.UPDATE_QUEST,
                target_id=quest_id,
                parameters={"status": status},
                reason=reason,
            ),
        )

    def correct_current_location(self, game_id: str, location_id: str, reason: str) -> GameViewState:
        save = self.repository.load_game(game_id)
        return self.move_character(game_id, save.state.player.id, location_id, reason)
