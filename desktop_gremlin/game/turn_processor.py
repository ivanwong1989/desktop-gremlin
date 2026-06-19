from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import uuid4

from pydantic import ValidationError

from .context_assembler import ContextAssembler
from .actions import PlayerActionSource
from .errors import InvalidStateChangeError
from .models import GameSave, GameViewState, NarratorTurn, PlayerAction, StateChange, TurnEvent, TurnRecord
from .narrator_service import NarratorService
from .state_applier import StateApplier
from .state_validator import StateValidator
from desktop_gremlin.persistence.errors import SaveValidationError
from desktop_gremlin.persistence.repository import GameRepository


@dataclass
class TurnDebugSnapshot:
    game_id: str = ""
    latest_player_action: PlayerAction | None = None
    latest_narrator_turn: NarratorTurn | None = None
    proposed_state_changes: list[StateChange] = field(default_factory=list)
    applied_state_changes: list[StateChange] = field(default_factory=list)
    validation_failure: str | None = None
    latest_model_context: list[dict[str, str]] = field(default_factory=list)


class TurnProcessor:
    def __init__(
        self,
        repository: GameRepository,
        context_assembler: ContextAssembler,
        narrator_service: NarratorService,
        state_validator: StateValidator,
        state_applier: StateApplier,
    ):
        self.repository = repository
        self.context_assembler = context_assembler
        self.narrator_service = narrator_service
        self.state_validator = state_validator
        self.state_applier = state_applier
        self.debug_by_game_id: dict[str, TurnDebugSnapshot] = {}

    def submit_action(self, game_id: str, action: PlayerAction) -> GameViewState:
        save = self.repository.load_game(game_id)
        action = PlayerAction.model_validate(action.model_dump())
        self.validate_player_action(save, action)
        messages = self.context_assembler.build_messages(save, action)
        debug = TurnDebugSnapshot(
            game_id=game_id,
            latest_player_action=action,
            latest_model_context=messages,
        )
        self.debug_by_game_id[game_id] = debug

        try:
            narrator_turn = self.narrator_service.narrate(messages)
            debug.latest_narrator_turn = narrator_turn
            debug.proposed_state_changes = list(narrator_turn.state_changes)
            self.state_validator.validate_all(save.state, narrator_turn.state_changes)
        except Exception as exc:
            debug.validation_failure = str(exc)
            raise

        candidate = save.model_copy(deep=True)
        candidate.state = self.state_applier.apply_all(candidate.state, narrator_turn.state_changes)
        candidate.state.turn_number += 1
        candidate.current_choices = narrator_turn.choices
        candidate.dynamic_lore.extend(narrator_turn.memory_signals)
        turn_id = f"turn-{uuid4().hex[:12]}"
        now = datetime.now(timezone.utc).replace(microsecond=0)
        turn_record = TurnRecord(
            id=turn_id,
            turn_number=candidate.state.turn_number,
            player_action=action,
            narrator_turn=narrator_turn,
            applied_state_changes=narrator_turn.state_changes,
            state_after=candidate.state,
            created_at=now,
        )
        candidate.recent_turns.append(turn_record)
        candidate.updated_at = now
        try:
            candidate = GameSave.model_validate(candidate.model_dump())
        except ValidationError as exc:
            raise SaveValidationError(f"Candidate turn save failed validation: {exc}") from exc

        self.repository.save_game(candidate)
        debug.applied_state_changes = list(narrator_turn.state_changes)
        self.repository.append_turn_event(
            TurnEvent(
                id=f"event-{uuid4().hex[:12]}",
                game_id=game_id,
                turn_id=turn_id,
                event_type="turn_completed",
                payload={
                    "turn_number": candidate.state.turn_number,
                    "state_change_count": len(narrator_turn.state_changes),
                },
            )
        )
        return view_from_save(candidate, narrative=narrator_turn.narrative)

    def validate_player_action(self, save: GameSave, action: PlayerAction) -> None:
        if action.source != PlayerActionSource.CHOICE:
            return
        choice = next((item for item in save.current_choices if item.id == action.choice_id), None)
        if choice is None:
            raise InvalidStateChangeError(f"Unknown or stale choice ID: {action.choice_id}")
        if action.text != choice.action_text:
            raise InvalidStateChangeError(f"Choice action text does not match current choice: {action.choice_id}")

    def get_debug_snapshot(self, game_id: str) -> TurnDebugSnapshot:
        return self.debug_by_game_id.get(game_id, TurnDebugSnapshot(game_id=game_id))


def view_from_save(save: GameSave, narrative: str = "") -> GameViewState:
    return GameViewState(
        game_id=save.campaign.id,
        title=save.campaign.title,
        narrative=narrative,
        choices=save.current_choices,
        state=save.state,
        story_summary=save.story_summary,
        dynamic_lore=save.dynamic_lore,
    )
