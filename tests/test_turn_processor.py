from __future__ import annotations

import json

import pytest

from desktop_gremlin.game.actions import PlayerActionSource
from desktop_gremlin.game.context_assembler import ContextAssembler
from desktop_gremlin.game.errors import InvalidStateChangeError, NarratorTurnError
from desktop_gremlin.game.game_controller import GameController
from desktop_gremlin.game.initial_state_generator import InitialStateGenerator
from desktop_gremlin.game.models import Choice, PlayerAction, TurnRecord
from desktop_gremlin.game.narrator_service import NarratorService
from desktop_gremlin.game.state_applier import StateApplier
from desktop_gremlin.game.state_validator import StateValidator
from desktop_gremlin.game.turn_processor import TurnProcessor
from desktop_gremlin.persistence.errors import SaveValidationError
from desktop_gremlin.persistence.json_repository import JsonGameRepository
from desktop_gremlin.ui.choice_panel import ChoicePanelState
from tests.test_initial_state_generation import FakeInitialStateLLM, build_campaign, initial_state_payload, json_response


class FakeNarratorLLM:
    def __init__(self, responses: list[str] | None = None, error: Exception | None = None):
        self.responses = list(responses or [])
        self.error = error
        self.messages: list[list[dict[str, str]]] = []

    def complete(self, messages: list[dict[str, str]]) -> str:
        self.messages.append(messages)
        if self.error is not None:
            raise self.error
        if not self.responses:
            raise AssertionError("FakeNarratorLLM received more calls than expected")
        return self.responses.pop(0)


class FailingSaveRepository(JsonGameRepository):
    def save_game(self, save):
        raise OSError("simulated save failure")


def narrator_payload(
    state_changes: list[dict] | None = None,
    narrative: str = "The guard gives a curt nod.",
    choices: list[dict] | None = None,
) -> dict:
    return {
        "schema_version": 1,
        "narrative": narrative,
        "choices": choices
        if choices is not None
        else [
            {
                "id": "walk-north",
                "label": "Walk north",
                "action_text": "Walk north toward the abbey.",
            }
        ],
        "state_changes": state_changes or [],
        "memory_signals": [],
        "image_request": None,
    }


def build_turn_controller(tmp_path, narrator_responses: list[str], repository=None, initial_payload=None):
    repository = repository or JsonGameRepository(tmp_path / "campaigns")
    initial_llm = FakeInitialStateLLM([json_response(initial_payload or initial_state_payload())])
    narrator_llm = FakeNarratorLLM(narrator_responses)
    turn_processor = TurnProcessor(
        repository=repository,
        context_assembler=ContextAssembler(),
        narrator_service=NarratorService(narrator_llm),
        state_validator=StateValidator(),
        state_applier=StateApplier(),
    )
    controller = GameController(
        repository=repository,
        generator=InitialStateGenerator(initial_llm),
        turn_processor=turn_processor,
    )
    campaign = build_campaign(controller)
    save = controller.accept_initial_review(controller.generate_initial_review(campaign))
    return controller, save, narrator_llm


def text_action(text: str = "Ask the guard about the abbey road.") -> PlayerAction:
    return PlayerAction(source=PlayerActionSource.TEXT, text=text)


def choice_action(choice_id: str = "ask-guard", text: str = "Ask the guard about the abbey road.") -> PlayerAction:
    return PlayerAction(source=PlayerActionSource.CHOICE, text=text, choice_id=choice_id)


def test_valid_free_text_turn_persists_and_returns_view(tmp_path) -> None:
    controller, save, _llm = build_turn_controller(
        tmp_path,
        [
            json_response(
                narrator_payload(
                    [
                        {
                            "operation": "set_flag",
                            "parameters": {"key": "guard_questioned", "value": True},
                            "reason": "The player asked the guard about the road.",
                        }
                    ]
                )
            )
        ],
    )

    view = controller.submit_action(save.campaign.id, text_action())
    reloaded = controller.load_game(save.campaign.id)

    assert view.narrative == "The guard gives a curt nod."
    assert view.state.turn_number == 1
    assert reloaded.state.turn_number == 1
    assert reloaded.state.world_flags["guard_questioned"] is True
    assert reloaded.current_choices[0].id == "walk-north"
    assert reloaded.recent_turns[0].player_action.text == "Ask the guard about the abbey road."


def test_zero_choice_response_is_valid_and_persisted(tmp_path) -> None:
    controller, save, _llm = build_turn_controller(
        tmp_path,
        [json_response(narrator_payload(choices=[]))],
    )

    view = controller.submit_action(save.campaign.id, text_action())
    reloaded = controller.load_game(save.campaign.id)

    assert view.choices == []
    assert reloaded.current_choices == []


def test_multiple_choices_are_persisted_and_reloaded(tmp_path) -> None:
    choices = [
        {"id": "inspect-door", "label": "Inspect the door", "action_text": "I inspect the old door."},
        {"id": "listen", "label": "Listen", "action_text": "I listen for movement."},
    ]
    controller, save, _llm = build_turn_controller(
        tmp_path,
        [json_response(narrator_payload(choices=choices))],
    )

    view = controller.submit_action(save.campaign.id, text_action())
    reloaded = controller.load_game(save.campaign.id)

    assert [choice.id for choice in view.choices] == ["inspect-door", "listen"]
    assert [choice.id for choice in reloaded.current_choices] == ["inspect-door", "listen"]


def test_choice_action_uses_same_turn_engine_and_maps_text(tmp_path) -> None:
    controller, save, _llm = build_turn_controller(
        tmp_path,
        [json_response(narrator_payload(narrative="The guard points north."))],
    )

    view = controller.submit_action(save.campaign.id, choice_action())
    reloaded = controller.load_game(save.campaign.id)

    assert view.state.turn_number == 1
    assert reloaded.recent_turns[0].player_action.source == PlayerActionSource.CHOICE
    assert reloaded.recent_turns[0].player_action.choice_id == "ask-guard"
    assert reloaded.recent_turns[0].player_action.text == "Ask the guard about the abbey road."


def test_stale_choice_id_is_rejected_before_model_call(tmp_path) -> None:
    controller, save, narrator_llm = build_turn_controller(
        tmp_path,
        [json_response(narrator_payload())],
    )

    with pytest.raises(InvalidStateChangeError, match="stale choice"):
        controller.submit_action(save.campaign.id, choice_action(choice_id="missing", text="No longer valid."))

    assert narrator_llm.messages == []
    assert controller.load_game(save.campaign.id).state.turn_number == 0


def test_choice_text_mismatch_is_rejected_before_model_call(tmp_path) -> None:
    controller, save, narrator_llm = build_turn_controller(
        tmp_path,
        [json_response(narrator_payload())],
    )

    with pytest.raises(InvalidStateChangeError, match="does not match"):
        controller.submit_action(save.campaign.id, choice_action(text="Tampered text."))

    assert narrator_llm.messages == []
    assert controller.load_game(save.campaign.id).state.turn_number == 0


def test_choice_panel_state_prevents_double_click_and_rejects_stale_ids() -> None:
    panel_state = ChoicePanelState()
    panel_state.set_choices(
        [
            Choice(id="inspect-door", label="Inspect", action_text="Inspect the door."),
        ]
    )

    first = panel_state.choose("inspect-door")
    second = panel_state.choose("inspect-door")

    assert first is not None
    assert second is None
    panel_state.set_enabled(True)
    with pytest.raises(ValueError, match="stale choice"):
        panel_state.choose("missing")


def test_multiple_valid_state_changes_apply_atomically(tmp_path) -> None:
    changes = [
        {
            "operation": "create_location",
            "parameters": {
                "id": "abbey-road",
                "name": "Abbey Road",
                "description": "A wet road climbing north.",
                "discovered": True,
                "attributes": {},
            },
            "reason": "The road becomes relevant.",
        },
        {
            "operation": "move_character",
            "target_id": "player",
            "parameters": {"location_id": "abbey-road"},
            "reason": "The player walks north.",
        },
        {
            "operation": "remove_item",
            "target_id": "letter",
            "parameters": {"quantity": 1},
            "reason": "The guard takes the letter for inspection.",
        },
    ]
    controller, save, _llm = build_turn_controller(tmp_path, [json_response(narrator_payload(changes))])

    view = controller.submit_action(save.campaign.id, text_action("Walk north and hand over the letter."))

    assert view.state.current_location_id == "abbey-road"
    assert view.state.player.current_location_id == "abbey-road"
    assert "abbey-road" in view.state.locations
    assert "letter" not in view.state.inventory


def test_invalid_mutation_rolls_back_save_and_choices(tmp_path) -> None:
    invalid_change = {
        "operation": "remove_item",
        "target_id": "letter",
        "parameters": {"quantity": 2},
        "reason": "The model tries to remove too many letters.",
    }
    controller, save, _llm = build_turn_controller(tmp_path, [json_response(narrator_payload([invalid_change]))])

    with pytest.raises(InvalidStateChangeError, match="below zero"):
        controller.submit_action(save.campaign.id, text_action())

    reloaded = controller.load_game(save.campaign.id)
    assert reloaded.state.turn_number == 0
    assert reloaded.state.inventory["letter"].quantity == 1
    assert reloaded.current_choices[0].id == "ask-guard"


def test_model_error_rolls_back(tmp_path) -> None:
    repository = JsonGameRepository(tmp_path / "campaigns")
    initial_llm = FakeInitialStateLLM([json_response(initial_state_payload())])
    narrator_llm = FakeNarratorLLM(error=NarratorTurnError("model unavailable"))
    controller = GameController(
        repository=repository,
        generator=InitialStateGenerator(initial_llm),
        turn_processor=TurnProcessor(
            repository=repository,
            context_assembler=ContextAssembler(),
            narrator_service=NarratorService(narrator_llm),
            state_validator=StateValidator(),
            state_applier=StateApplier(),
        ),
    )
    campaign = build_campaign(controller)
    save = controller.accept_initial_review(controller.generate_initial_review(campaign))

    with pytest.raises(NarratorTurnError):
        controller.submit_action(save.campaign.id, text_action())

    assert controller.load_game(save.campaign.id).state.turn_number == 0


def test_invalid_json_rolls_back(tmp_path) -> None:
    controller, save, _llm = build_turn_controller(tmp_path, ["not json"])

    with pytest.raises(NarratorTurnError, match="Invalid narrator JSON"):
        controller.submit_action(save.campaign.id, text_action())

    assert controller.load_game(save.campaign.id).state.turn_number == 0


def test_save_error_rolls_back_existing_save(tmp_path) -> None:
    repository = FailingSaveRepository(tmp_path / "campaigns")
    controller, save, _llm = build_turn_controller(
        tmp_path,
        [json_response(narrator_payload())],
        repository=repository,
    )

    with pytest.raises(OSError, match="simulated save failure"):
        controller.submit_action(save.campaign.id, text_action())

    reloaded = JsonGameRepository(tmp_path / "campaigns").load_game(save.campaign.id)
    assert reloaded.state.turn_number == 0


def test_turn_number_increments_exactly_once(tmp_path) -> None:
    controller, save, _llm = build_turn_controller(
        tmp_path,
        [
            json_response(narrator_payload(narrative="First turn.")),
            json_response(narrator_payload(narrative="Second turn.")),
        ],
    )

    first = controller.submit_action(save.campaign.id, text_action("First action."))
    second = controller.submit_action(save.campaign.id, text_action("Second action."))

    assert first.state.turn_number == 1
    assert second.state.turn_number == 2
    assert controller.load_game(save.campaign.id).state.turn_number == 2


def test_narrative_state_consistency_after_move(tmp_path) -> None:
    changes = [
        {
            "operation": "create_location",
            "parameters": {
                "id": "gatehouse",
                "name": "Gatehouse",
                "description": "A stone gatehouse.",
                "discovered": True,
                "attributes": {},
            },
            "reason": "The gatehouse is reached.",
        },
        {
            "operation": "move_character",
            "target_id": "player",
            "parameters": {"location_id": "gatehouse"},
            "reason": "The player enters the gatehouse.",
        },
    ]
    controller, save, _llm = build_turn_controller(
        tmp_path,
        [json_response(narrator_payload(changes, narrative="You enter the gatehouse."))],
    )

    view = controller.submit_action(save.campaign.id, text_action("Enter the gatehouse."))

    assert "gatehouse" in view.narrative
    assert view.state.player.current_location_id == "gatehouse"


def test_context_ordering(tmp_path) -> None:
    controller, save, narrator_llm = build_turn_controller(tmp_path, [json_response(narrator_payload())])

    controller.submit_action(save.campaign.id, text_action())

    content = narrator_llm.messages[0][1]["content"]
    expected = [
        "## Narrator rules",
        "## Campaign premise",
        "## Relevant initial canon",
        "## Canonical current state",
        "## Current scene",
        "## Relevant dynamic lore",
        "## Rolling summary",
        "## Recent turns",
        "## Current player action",
        "## Required output schema",
    ]
    positions = [content.index(section) for section in expected]
    assert positions == sorted(positions)


def test_coffee_run_creates_location_then_moves_player_sequentially(tmp_path) -> None:
    payload = initial_state_payload()
    state = payload["state"]
    state["player"].update({"id": "ivan", "name": "Ivan", "current_location_id": "office-floor"})
    state["locations"] = {
        "office-floor": {
            "id": "office-floor",
            "name": "Office Floor",
            "description": "An open-plan office.",
            "discovered": True,
            "attributes": {},
        }
    }
    state["characters"] = {}
    state["current_location_id"] = "office-floor"
    state["present_character_ids"] = ["ivan"]
    changes = [
        {
            "operation": "create_location",
            "parameters": {
                "id": "office-pantry",
                "name": "Office Pantry",
                "description": "A small pantry near the office floor.",
                "discovered": True,
                "attributes": {},
            },
            "reason": "Ivan chooses to get coffee.",
        },
        {
            "operation": "move_character",
            "target_id": "ivan",
            "parameters": {"location_id": "office-pantry"},
            "reason": "Ivan walks into the pantry.",
        },
    ]
    controller, save, _llm = build_turn_controller(
        tmp_path,
        [json_response(narrator_payload(changes, narrative="Ivan walks to the pantry for coffee."))],
        initial_payload=payload,
    )

    view = controller.submit_action(save.campaign.id, text_action("Get coffee."))

    assert list(view.state.locations)[-1] == "office-pantry"
    assert view.state.current_location_id == "office-pantry"
    assert view.state.player.current_location_id == "office-pantry"


def test_narrator_validation_error_retains_raw_output_index_and_operation(tmp_path) -> None:
    invalid = narrator_payload([
        {
            "operation": "create_location",
            "target_id": "office-pantry",
            "parameters": {"name": "Office Pantry"},
            "reason": "An invalid create payload.",
        }
    ])
    raw = json_response(invalid)
    controller, save, _llm = build_turn_controller(tmp_path, [raw])

    with pytest.raises(NarratorTurnError, match=r"state_changes\[0\] operation=create_location"):
        controller.submit_action(save.campaign.id, text_action())

    debug = controller.get_debug_snapshot(save.campaign.id)
    assert debug.raw_model_output == raw
    assert "Extra inputs are not permitted" in debug.validation_failure
    assert controller.load_game(save.campaign.id).state.turn_number == 0


def test_recent_turn_ordering(tmp_path) -> None:
    controller, save, _llm = build_turn_controller(
        tmp_path,
        [
            json_response(narrator_payload(narrative="First.")),
            json_response(narrator_payload(narrative="Second.")),
        ],
    )
    controller.submit_action(save.campaign.id, text_action("First action."))
    controller.submit_action(save.campaign.id, text_action("Second action."))

    context = ContextAssembler().build_context_text(controller.load_game(save.campaign.id), text_action("Third action."))

    assert context.index("Turn 1") < context.index("Turn 2")
