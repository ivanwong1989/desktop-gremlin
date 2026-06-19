from __future__ import annotations

import json

import pytest

from desktop_gremlin.game.models import (
    CampaignDefinition,
    GameSave,
    StorySummary,
    TurnEvent,
)
from desktop_gremlin.persistence.errors import (
    CorruptSaveError,
    GameNotFoundError,
    SaveValidationError,
    UnsafeGameIdError,
)
from desktop_gremlin.persistence.json_repository import JsonGameRepository
from tests.test_game_models import sample_state


def sample_save(game_id: str = "campaign-1", title: str = "The Rain Road") -> GameSave:
    return GameSave(
        campaign=CampaignDefinition(
            id=game_id,
            title=title,
            initial_lore="The abbey controls the old northern road.",
            player_premise="A courier carrying a sealed letter.",
            tone="Low fantasy mystery",
            content_constraints=["No graphic gore"],
        ),
        state=sample_state(),
        story_summary=StorySummary(text="Mira has just reached the crossroads."),
    )


def test_create_and_reload_game(tmp_path) -> None:
    repository = JsonGameRepository(tmp_path / "campaigns")
    save = sample_save()

    repository.create_game(save)
    loaded = repository.load_game(save.campaign.id)

    assert loaded.campaign.id == save.campaign.id
    assert loaded.campaign.title == "The Rain Road"
    assert loaded.state.current_location_id == "crossroads"


def test_list_games(tmp_path) -> None:
    repository = JsonGameRepository(tmp_path / "campaigns")
    first = sample_save("campaign-1", "First")
    second = sample_save("campaign-2", "Second")

    repository.create_game(first)
    repository.create_game(second)

    games = repository.list_games()

    assert {game.id for game in games} == {"campaign-1", "campaign-2"}
    assert {game.title for game in games} == {"First", "Second"}


def test_save_game_creates_backup_of_previous_valid_save(tmp_path) -> None:
    repository = JsonGameRepository(tmp_path / "campaigns")
    save = sample_save()
    repository.create_game(save)

    updated = save.model_copy(deep=True)
    updated.state.turn_number = 1
    repository.save_game(updated)

    backup_path = tmp_path / "campaigns" / save.campaign.id / "save.json.bak"
    backup = GameSave.model_validate(json.loads(backup_path.read_text(encoding="utf-8")))

    assert backup.state.turn_number == 0
    assert repository.load_game(save.campaign.id).state.turn_number == 1


def test_atomic_replace_failure_keeps_prior_save(tmp_path, monkeypatch) -> None:
    repository = JsonGameRepository(tmp_path / "campaigns")
    save = sample_save()
    repository.create_game(save)

    updated = save.model_copy(deep=True)
    updated.state.turn_number = 2

    def fail_replace(_source, _target):
        raise OSError("simulated replace failure")

    monkeypatch.setattr("desktop_gremlin.persistence.atomic_files.os.replace", fail_replace)

    with pytest.raises(OSError, match="simulated replace failure"):
        repository.save_game(updated)

    assert repository.load_game(save.campaign.id).state.turn_number == 0


def test_recover_from_damaged_current_save_uses_backup(tmp_path) -> None:
    repository = JsonGameRepository(tmp_path / "campaigns")
    save = sample_save()
    repository.create_game(save)
    updated = save.model_copy(deep=True)
    updated.state.turn_number = 1
    repository.save_game(updated)

    save_path = tmp_path / "campaigns" / save.campaign.id / "save.json"
    save_path.write_text("{ damaged json", encoding="utf-8")

    with pytest.raises(CorruptSaveError):
        repository.load_game(save.campaign.id)

    recovered = repository.recover_from_backup(save.campaign.id)

    assert recovered.state.turn_number == 0
    assert repository.load_game(save.campaign.id).state.turn_number == 0


def test_invalid_schema_version_is_rejected(tmp_path) -> None:
    repository = JsonGameRepository(tmp_path / "campaigns")
    save = sample_save()
    repository.create_game(save)
    save_path = tmp_path / "campaigns" / save.campaign.id / "save.json"
    data = json.loads(save_path.read_text(encoding="utf-8"))
    data["schema_version"] = 999
    save_path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(SaveValidationError, match="schema_version"):
        repository.load_game(save.campaign.id)


def test_missing_save_is_distinguished_from_corrupt_save(tmp_path) -> None:
    repository = JsonGameRepository(tmp_path / "campaigns")

    with pytest.raises(GameNotFoundError):
        repository.load_game("missing-game")


def test_failed_transaction_does_not_replace_live_state_or_save(tmp_path) -> None:
    repository = JsonGameRepository(tmp_path / "campaigns")
    live_save = sample_save()
    repository.create_game(live_save)

    def invalid_update(candidate: GameSave) -> None:
        candidate.state.turn_number = 5
        candidate.state.current_location_id = "missing-location"

    with pytest.raises(SaveValidationError):
        repository.commit_game_update(live_save, invalid_update)

    assert live_save.state.turn_number == 0
    assert live_save.state.current_location_id == "crossroads"
    assert repository.load_game(live_save.campaign.id).state.turn_number == 0


def test_successful_transaction_returns_persisted_candidate(tmp_path) -> None:
    repository = JsonGameRepository(tmp_path / "campaigns")
    live_save = sample_save()
    repository.create_game(live_save)

    def update(candidate: GameSave) -> None:
        candidate.state.turn_number = 1

    new_live_save = repository.commit_game_update(live_save, update)

    assert live_save.state.turn_number == 0
    assert new_live_save.state.turn_number == 1
    assert repository.load_game(live_save.campaign.id).state.turn_number == 1


def test_event_log_appending(tmp_path) -> None:
    repository = JsonGameRepository(tmp_path / "campaigns")
    save = sample_save()
    repository.create_game(save)

    repository.append_turn_event(
        TurnEvent(
            id="event-1",
            game_id=save.campaign.id,
            turn_id="turn-1",
            event_type="turn_completed",
            payload={"turn_number": 1},
        )
    )
    repository.append_turn_event(
        TurnEvent(
            id="event-2",
            game_id=save.campaign.id,
            event_type="summary_updated",
            payload={"summary": "A short summary."},
        )
    )

    event_path = tmp_path / "campaigns" / save.campaign.id / "turns.jsonl"
    lines = event_path.read_text(encoding="utf-8").splitlines()

    assert len(lines) == 2
    assert json.loads(lines[0])["id"] == "event-1"
    assert json.loads(lines[1])["event_type"] == "summary_updated"


@pytest.mark.parametrize(
    "game_id",
    [
        "../outside",
        "..\\outside",
        "/absolute",
        "nested/path",
        "",
    ],
)
def test_directory_traversal_is_rejected_for_game_ids(tmp_path, game_id: str) -> None:
    repository = JsonGameRepository(tmp_path / "campaigns")

    with pytest.raises(UnsafeGameIdError):
        repository.load_game(game_id)
