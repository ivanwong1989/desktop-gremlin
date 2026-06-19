from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4

from .initial_state_generator import InitialStateGenerator
from .manual_corrections import ManualCorrectionService
from .models import (
    CampaignDefinition,
    GameViewState,
    GameSave,
    InitialGameState,
    LoreEntry,
    PlayerAction,
    StateChange,
    StorySummary,
    TurnEvent,
)
from .turn_processor import TurnDebugSnapshot, TurnProcessor, view_from_save
from desktop_gremlin.persistence.repository import GameRepository


@dataclass(frozen=True)
class InitialGameReview:
    campaign: CampaignDefinition
    initial_state: InitialGameState

    @property
    def game_id(self) -> str:
        return self.campaign.id

    @property
    def opening_narrative(self) -> str:
        return self.initial_state.opening_narrative

    def to_save(self) -> GameSave:
        now = datetime.now(timezone.utc).replace(microsecond=0)
        return GameSave(
            campaign=self.campaign,
            state=self.initial_state.state,
            initial_lore=[
                LoreEntry(
                    id=f"{self.campaign.id}-initial-canon",
                    title="Initial Canon",
                    category="initial_canon",
                    summary=self.campaign.initial_lore,
                    content=self.campaign.initial_lore,
                    source_type="initial",
                )
            ],
            dynamic_lore=[],
            story_summary=StorySummary(text="", updated_at=now),
            recent_turns=[],
            current_choices=self.initial_state.initial_choices,
            created_at=now,
            updated_at=now,
        )


class GameController:
    def __init__(
        self,
        repository: GameRepository,
        generator: InitialStateGenerator,
        turn_processor: TurnProcessor | None = None,
        manual_corrections: ManualCorrectionService | None = None,
    ):
        self.repository = repository
        self.generator = generator
        self.turn_processor = turn_processor
        self.manual_corrections = manual_corrections or ManualCorrectionService(repository)

    def build_campaign_definition(
        self,
        title: str,
        initial_lore: str,
        player_premise: str,
        tone: str,
        content_constraints: list[str] | None = None,
        campaign_id: str | None = None,
    ) -> CampaignDefinition:
        now = datetime.now(timezone.utc).replace(microsecond=0)
        return CampaignDefinition(
            schema_version=1,
            id=campaign_id or new_campaign_id(),
            title=title,
            initial_lore=initial_lore,
            player_premise=player_premise,
            tone=tone,
            content_constraints=content_constraints or [],
            created_at=now,
            updated_at=now,
        )

    def generate_initial_review(self, campaign: CampaignDefinition) -> InitialGameReview:
        initial_state = self.generator.generate(campaign)
        return InitialGameReview(campaign=campaign, initial_state=initial_state)

    def regenerate_initial_review(self, review: InitialGameReview) -> InitialGameReview:
        return self.generate_initial_review(review.campaign)

    def accept_initial_review(self, review: InitialGameReview) -> GameSave:
        save = review.to_save()
        self.repository.create_game(save)
        self.repository.append_turn_event(
            TurnEvent(
                id=f"{save.campaign.id}-created",
                game_id=save.campaign.id,
                event_type="game_created",
                payload={"opening_narrative": review.opening_narrative},
            )
        )
        return save

    def start_game(self, review: InitialGameReview) -> GameViewState:
        return view_from_save(self.accept_initial_review(review), narrative=review.opening_narrative)

    def load_game(self, game_id: str) -> GameSave:
        return self.repository.load_game(game_id)

    def get_game_view(self, game_id: str) -> GameViewState:
        return view_from_save(self.load_game(game_id))

    def submit_action(self, game_id: str, action: PlayerAction) -> GameViewState:
        if self.turn_processor is None:
            raise RuntimeError("Game turn processing is not configured.")
        return self.turn_processor.submit_action(game_id, action)

    def apply_manual_correction(self, game_id: str, change: StateChange) -> GameViewState:
        return self.manual_corrections.apply_correction(game_id, change)

    def set_flag(self, game_id: str, key: str, value, reason: str) -> GameViewState:
        return self.manual_corrections.set_flag(game_id, key, value, reason)

    def remove_flag(self, game_id: str, key: str, reason: str) -> GameViewState:
        return self.manual_corrections.remove_flag(game_id, key, reason)

    def add_item(self, game_id: str, item_id: str, quantity: int, reason: str) -> GameViewState:
        return self.manual_corrections.add_item(game_id, item_id, quantity, reason)

    def remove_item(self, game_id: str, item_id: str, quantity: int, reason: str) -> GameViewState:
        return self.manual_corrections.remove_item(game_id, item_id, quantity, reason)

    def move_character(self, game_id: str, character_id: str, location_id: str, reason: str) -> GameViewState:
        return self.manual_corrections.move_character(game_id, character_id, location_id, reason)

    def adjust_quest_status(self, game_id: str, quest_id: str, status: str, reason: str) -> GameViewState:
        return self.manual_corrections.adjust_quest_status(game_id, quest_id, status, reason)

    def correct_current_location(self, game_id: str, location_id: str, reason: str) -> GameViewState:
        return self.manual_corrections.correct_current_location(game_id, location_id, reason)

    def get_debug_snapshot(self, game_id: str) -> TurnDebugSnapshot:
        if self.turn_processor is None:
            return TurnDebugSnapshot(game_id=game_id)
        return self.turn_processor.get_debug_snapshot(game_id)

    def list_turn_events(self, game_id: str) -> list[TurnEvent]:
        return self.repository.list_turn_events(game_id)


def new_campaign_id() -> str:
    return f"campaign-{uuid4().hex[:12]}"
