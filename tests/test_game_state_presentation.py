from __future__ import annotations

import pytest

from desktop_gremlin.game.actions import StateChangeOperation
from desktop_gremlin.game.errors import InvalidStateChangeError
from desktop_gremlin.game.game_controller import GameController
from desktop_gremlin.game.initial_state_generator import InitialStateGenerator
from desktop_gremlin.game.models import StateChange
from desktop_gremlin.persistence.json_repository import JsonGameRepository
from desktop_gremlin.ui.developer_inspector import developer_inspector_text
from desktop_gremlin.ui.game_state_panel import game_state_text
from tests.test_initial_state_generation import FakeInitialStateLLM, json_response
from tests.test_turn_processor import build_turn_controller, narrator_payload, text_action


def test_game_state_view_updates_only_after_successful_commit(tmp_path) -> None:
    changes = [
        {
            "operation": "set_flag",
            "parameters": {"key": "door_inspected", "value": True},
            "reason": "The player inspected the door.",
        }
    ]
    controller, save, _llm = build_turn_controller(tmp_path, [json_response(narrator_payload(changes))])
    before = controller.get_game_view(save.campaign.id)

    after = controller.submit_action(save.campaign.id, text_action("Inspect the old door."))

    assert "Turn: 0" in game_state_text(before)
    assert "Turn: 1" in game_state_text(after)
    assert "The guard gives a curt nod" not in game_state_text(after)


def test_failed_turn_does_not_alter_displayed_state(tmp_path) -> None:
    invalid_change = {
        "operation": "remove_item",
        "target_id": "letter",
        "parameters": {"quantity": 99},
        "reason": "Invalid over-removal.",
    }
    controller, save, _llm = build_turn_controller(tmp_path, [json_response(narrator_payload([invalid_change]))])
    before_text = game_state_text(controller.get_game_view(save.campaign.id))

    with pytest.raises(InvalidStateChangeError):
        controller.submit_action(save.campaign.id, text_action("Throw away everything."))

    after_text = game_state_text(controller.get_game_view(save.campaign.id))
    assert after_text == before_text


def test_load_restores_displayed_state(tmp_path) -> None:
    controller, save, _llm = build_turn_controller(tmp_path, [json_response(narrator_payload())])
    controller.submit_action(save.campaign.id, text_action("Ask the guard."))

    reloaded_controller = GameController(
        repository=JsonGameRepository(tmp_path / "campaigns"),
        generator=InitialStateGenerator(FakeInitialStateLLM([])),
    )
    view = reloaded_controller.get_game_view(save.campaign.id)

    assert "Player: Mira (healthy)" in game_state_text(view)
    assert "Location: Old Crossroads" in game_state_text(view)
    assert "Turn: 1" in game_state_text(view)


def test_manual_correction_creates_audit_event(tmp_path) -> None:
    controller, save, _llm = build_turn_controller(tmp_path, [json_response(narrator_payload())])

    view = controller.set_flag(save.campaign.id, "manual_note", "checked", "Developer correction.")
    events = controller.list_turn_events(save.campaign.id)

    assert view.state.world_flags["manual_note"] == "checked"
    assert events[-1].event_type == "manual_correction"
    assert events[-1].payload["state_change"]["operation"] == "set_flag"


def test_invalid_manual_correction_is_rejected(tmp_path) -> None:
    controller, save, _llm = build_turn_controller(tmp_path, [json_response(narrator_payload())])
    change = StateChange(
        operation=StateChangeOperation.REMOVE_ITEM,
        target_id="letter",
        parameters={"quantity": 99},
        reason="Invalid correction.",
    )

    with pytest.raises(InvalidStateChangeError):
        controller.apply_manual_correction(save.campaign.id, change)

    reloaded = controller.load_game(save.campaign.id)
    assert reloaded.state.inventory["letter"].quantity == 1
    assert [event.event_type for event in controller.list_turn_events(save.campaign.id)] == ["game_created"]


def test_developer_inspector_uses_canonical_state_and_debug_data(tmp_path) -> None:
    changes = [
        {
            "operation": "set_flag",
            "parameters": {"key": "guard_questioned", "value": True},
            "reason": "The guard was questioned.",
        }
    ]
    controller, save, _llm = build_turn_controller(tmp_path, [json_response(narrator_payload(changes))])
    view = controller.submit_action(save.campaign.id, text_action("Question the guard."))
    text = developer_inspector_text(
        controller.load_game(save.campaign.id),
        view,
        controller.get_debug_snapshot(save.campaign.id),
        controller.list_turn_events(save.campaign.id),
    )

    assert "Complete canonical state" in text
    assert "Latest player action" in text
    assert "Latest parsed NarratorTurn" in text
    assert "Proposed state changes" in text
    assert "Applied state changes" in text
    assert "Latest model context" in text
    assert "Event-log records" in text
    assert "Current choices" in text
