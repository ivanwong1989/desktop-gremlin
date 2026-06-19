from __future__ import annotations

import json

import pytest

from desktop_gremlin.game.errors import InitialStateGenerationError
from desktop_gremlin.game.game_controller import GameController
from desktop_gremlin.game.initial_state_generator import InitialStateGenerator
from desktop_gremlin.game.models import InitialGameState
from desktop_gremlin.persistence.errors import GameNotFoundError
from desktop_gremlin.persistence.json_repository import JsonGameRepository


class FakeInitialStateLLM:
    def __init__(self, responses: list[str]):
        self.responses = list(responses)
        self.messages: list[list[dict[str, str]]] = []

    def complete(self, messages: list[dict[str, str]]) -> str:
        self.messages.append(messages)
        if not self.responses:
            raise AssertionError("FakeInitialStateLLM received more calls than expected")
        return self.responses.pop(0)


def initial_state_payload(location_id: str = "crossroads") -> dict:
    return {
        "schema_version": 1,
        "opening_narrative": "Rain ticks against the old crossroads sign.",
        "state": {
            "schema_version": 1,
            "player": {
                "id": "player",
                "name": "Mira",
                "description": "A courier with a sealed letter.",
                "status": "healthy",
                "current_location_id": location_id,
                "attributes": {},
            },
            "characters": {
                "guard": {
                    "id": "guard",
                    "name": "Gate Guard",
                    "description": "A tired guard watching the road.",
                    "status": "alert",
                    "current_location_id": "crossroads",
                    "attributes": {},
                }
            },
            "locations": {
                "crossroads": {
                    "id": "crossroads",
                    "name": "Old Crossroads",
                    "description": "Four muddy roads meet beneath a leaning sign.",
                    "discovered": True,
                    "attributes": {},
                }
            },
            "item_definitions": {
                "letter": {
                    "id": "letter",
                    "name": "Sealed Letter",
                    "description": "A wax-sealed message.",
                    "attributes": {},
                }
            },
            "inventory": {
                "letter": {
                    "item_id": "letter",
                    "quantity": 1,
                    "attributes": {},
                }
            },
            "quests": {
                "deliver-letter": {
                    "id": "deliver-letter",
                    "title": "Deliver the Letter",
                    "description": "Bring the letter to the abbey.",
                    "status": "active",
                    "stage": "Find the abbey road.",
                    "attributes": {},
                }
            },
            "world_flags": {},
            "current_location_id": "crossroads",
            "present_character_ids": ["player", "guard"],
            "game_time": "Dusk",
            "turn_number": 0,
        },
        "initial_choices": [
            {
                "id": "ask-guard",
                "label": "Ask the guard",
                "action_text": "Ask the guard about the abbey road.",
            }
        ],
    }


def json_response(payload: dict) -> str:
    return json.dumps(payload)


def build_controller(tmp_path, responses: list[str]) -> tuple[GameController, FakeInitialStateLLM]:
    llm = FakeInitialStateLLM(responses)
    controller = GameController(
        repository=JsonGameRepository(tmp_path / "campaigns"),
        generator=InitialStateGenerator(llm),
    )
    return controller, llm


def build_campaign(controller: GameController, initial_lore: str = "The abbey controls the old northern road."):
    return controller.build_campaign_definition(
        campaign_id="campaign-1",
        title="The Rain Road",
        initial_lore=initial_lore,
        player_premise="A courier carrying a sealed letter.",
        tone="Low fantasy mystery",
        content_constraints=["No graphic gore"],
    )


def test_valid_result_creates_review_model(tmp_path) -> None:
    controller, llm = build_controller(tmp_path, [json_response(initial_state_payload())])
    campaign = build_campaign(controller)

    review = controller.generate_initial_review(campaign)

    assert isinstance(review.initial_state, InitialGameState)
    assert review.campaign.id == "campaign-1"
    assert review.opening_narrative.startswith("Rain")
    assert len(llm.messages) == 1


def test_accept_save_close_and_reload_generated_campaign(tmp_path) -> None:
    controller, _llm = build_controller(tmp_path, [json_response(initial_state_payload())])
    campaign = build_campaign(controller)
    review = controller.generate_initial_review(campaign)

    saved = controller.accept_initial_review(review)
    reloaded = controller.load_game(saved.campaign.id)

    assert reloaded.campaign.title == "The Rain Road"
    assert reloaded.state.current_location_id == "crossroads"
    assert reloaded.current_choices[0].id == "ask-guard"


def test_invalid_json_is_rejected_and_repair_can_recover(tmp_path) -> None:
    controller, llm = build_controller(
        tmp_path,
        [
            "{ invalid json",
            json_response(initial_state_payload()),
        ],
    )
    campaign = build_campaign(controller)

    review = controller.generate_initial_review(campaign)

    assert review.initial_state.state.player.name == "Mira"
    assert len(llm.messages) == 2
    assert "Validation errors:" in llm.messages[1][1]["content"]
    assert "{ invalid json" in llm.messages[1][1]["content"]


def test_cross_reference_errors_are_rejected(tmp_path) -> None:
    controller, _llm = build_controller(
        tmp_path,
        [
            json_response(initial_state_payload(location_id="missing")),
            json_response(initial_state_payload(location_id="also-missing")),
        ],
    )
    campaign = build_campaign(controller)

    with pytest.raises(InitialStateGenerationError, match="current_location_id"):
        controller.generate_initial_review(campaign)


def test_two_failed_attempts_create_no_save(tmp_path) -> None:
    controller, _llm = build_controller(tmp_path, ["not json", "still not json"])
    campaign = build_campaign(controller)

    with pytest.raises(InitialStateGenerationError):
        controller.generate_initial_review(campaign)

    with pytest.raises(GameNotFoundError):
        controller.load_game(campaign.id)


def test_regeneration_does_not_overwrite_an_accepted_game(tmp_path) -> None:
    first_payload = initial_state_payload()
    second_payload = initial_state_payload()
    second_payload["opening_narrative"] = "A different opening waits at the road."
    second_payload["state"]["turn_number"] = 3
    controller, _llm = build_controller(tmp_path, [json_response(first_payload), json_response(second_payload)])
    campaign = build_campaign(controller)

    accepted = controller.accept_initial_review(controller.generate_initial_review(campaign))
    regenerated_review = controller.generate_initial_review(campaign)
    reloaded = controller.load_game(campaign.id)

    assert accepted.state.turn_number == 0
    assert regenerated_review.initial_state.state.turn_number == 3
    assert reloaded.state.turn_number == 0


def test_initial_lore_remains_exactly_unchanged(tmp_path) -> None:
    initial_lore = "Line one of canon.\nLine two: The moon is glass."
    controller, _llm = build_controller(tmp_path, [json_response(initial_state_payload())])
    campaign = build_campaign(controller, initial_lore=initial_lore)
    review = controller.generate_initial_review(campaign)

    saved = controller.accept_initial_review(review)
    reloaded = controller.load_game(saved.campaign.id)

    assert reloaded.campaign.initial_lore == initial_lore
    assert reloaded.initial_lore[0].content == initial_lore
    assert reloaded.initial_lore[0].summary == initial_lore
