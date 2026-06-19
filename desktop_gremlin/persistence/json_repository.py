from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from datetime import datetime, timezone
import json
import logging
import os
import re
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from desktop_gremlin.game.models import SCHEMA_VERSION, GameMetadata, GameSave, TurnEvent

from .atomic_files import append_jsonl_line, atomic_write_text
from .errors import CorruptSaveError, GameNotFoundError, SaveValidationError, UnsafeGameIdError


SAVE_FILE = "save.json"
BACKUP_FILE = "save.json.bak"
EVENT_LOG_FILE = "turns.jsonl"
SAFE_GAME_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


class JsonGameRepository:
    def __init__(self, campaigns_dir: str | Path = Path("data") / "campaigns"):
        self.campaigns_dir = Path(campaigns_dir)

    def create_game(self, save: GameSave) -> None:
        game_dir = self._game_dir(save.campaign.id)
        save_path = game_dir / SAVE_FILE
        if save_path.exists():
            raise FileExistsError(f"Game already exists: {save.campaign.id}")
        self._write_save(save)

    def load_game(self, game_id: str) -> GameSave:
        save_path = self._save_path(game_id)
        if not save_path.exists():
            raise GameNotFoundError(f"Save file not found for game: {game_id}")
        return self._read_save(save_path)

    def save_game(self, save: GameSave) -> None:
        self._write_save(save)

    def list_games(self) -> list[GameMetadata]:
        if not self.campaigns_dir.exists():
            return []

        games: list[GameMetadata] = []
        for child in self.campaigns_dir.iterdir():
            if not child.is_dir():
                continue
            save_path = child / SAVE_FILE
            if not save_path.exists():
                continue
            save = self._read_save(save_path)
            games.append(
                GameMetadata(
                    id=save.campaign.id,
                    title=save.campaign.title,
                    updated_at=save.updated_at,
                    turn_number=save.state.turn_number,
                )
            )

        games.sort(key=lambda item: item.updated_at, reverse=True)
        return games

    def append_turn_event(self, event: TurnEvent) -> None:
        event_path = self._game_dir(event.game_id) / EVENT_LOG_FILE
        line = event.model_dump_json()
        append_jsonl_line(event_path, line)

    def list_turn_events(self, game_id: str) -> list[TurnEvent]:
        event_path = self._game_dir(game_id) / EVENT_LOG_FILE
        if not event_path.exists():
            return []
        events: list[TurnEvent] = []
        with open(event_path, "r", encoding="utf-8") as file:
            for line_number, line in enumerate(file, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    events.append(TurnEvent.model_validate(data))
                except (json.JSONDecodeError, ValidationError) as exc:
                    raise CorruptSaveError(
                        f"Invalid event log record in {event_path} at line {line_number}: {exc}"
                    ) from exc
        return events

    def recover_from_backup(self, game_id: str) -> GameSave:
        game_dir = self._game_dir(game_id)
        backup_path = game_dir / BACKUP_FILE
        save_path = game_dir / SAVE_FILE
        if not backup_path.exists():
            raise GameNotFoundError(f"Backup save file not found for game: {game_id}")

        recovered = self._read_save(backup_path)
        logging.warning("Recovering game %s from backup: %s", game_id, backup_path)
        atomic_write_text(save_path, backup_path.read_text(encoding="utf-8"), backup_path=None)
        return recovered

    def commit_game_update(self, save: GameSave, update: Callable[[GameSave], None]) -> GameSave:
        candidate = save.model_copy(deep=True)
        try:
            update(candidate)
            candidate.updated_at = datetime.now(timezone.utc).replace(microsecond=0)
            candidate = GameSave.model_validate(candidate.model_dump())
        except ValidationError as exc:
            raise SaveValidationError(f"Candidate save failed validation: {exc}") from exc
        self.save_game(candidate)
        return candidate

    def _write_save(self, save: GameSave) -> None:
        try:
            validated = GameSave.model_validate(save.model_dump())
        except ValidationError as exc:
            raise SaveValidationError(f"Save failed validation: {exc}") from exc
        game_dir = self._game_dir(validated.campaign.id)
        save_path = game_dir / SAVE_FILE
        backup_path = game_dir / BACKUP_FILE
        payload = validated.model_dump_json(indent=2)
        atomic_write_text(save_path, payload, backup_path=backup_path)

    def _read_save(self, save_path: Path) -> GameSave:
        try:
            with open(save_path, "r", encoding="utf-8") as file:
                data = json.load(file)
        except FileNotFoundError as exc:
            raise GameNotFoundError(f"Save file not found: {save_path}") from exc
        except json.JSONDecodeError as exc:
            raise CorruptSaveError(f"Invalid JSON in save file {save_path}: {exc}") from exc
        except OSError as exc:
            raise CorruptSaveError(f"Could not read save file {save_path}: {exc}") from exc

        if not isinstance(data, dict):
            raise SaveValidationError(f"Save file {save_path} must contain a JSON object")

        self._validate_schema_version(data, save_path)
        try:
            return GameSave.model_validate(data)
        except ValidationError as exc:
            raise SaveValidationError(f"Save file {save_path} failed validation: {exc}") from exc

    def _validate_schema_version(self, data: dict[str, Any], save_path: Path) -> None:
        version = data.get("schema_version")
        if version != SCHEMA_VERSION:
            raise SaveValidationError(
                f"Save file {save_path} uses schema_version={version!r}; expected {SCHEMA_VERSION}"
            )

    def _save_path(self, game_id: str) -> Path:
        return self._game_dir(game_id) / SAVE_FILE

    def _game_dir(self, game_id: str) -> Path:
        safe_id = self._validate_game_id(game_id)
        base = self.campaigns_dir.resolve()
        path = (base / safe_id).resolve()
        if os.path.commonpath([str(base), str(path)]) != str(base):
            raise UnsafeGameIdError(f"Game ID escapes campaigns directory: {game_id!r}")
        return path

    def _validate_game_id(self, game_id: str) -> str:
        value = str(game_id).strip()
        if not value or not SAFE_GAME_ID.fullmatch(value):
            raise UnsafeGameIdError(f"Unsafe game ID: {game_id!r}")
        if value in {".", ".."}:
            raise UnsafeGameIdError(f"Unsafe game ID: {game_id!r}")
        return value
