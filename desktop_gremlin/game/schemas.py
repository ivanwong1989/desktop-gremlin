from __future__ import annotations

from typing import Any, Type

from pydantic import BaseModel

from .models import InitialGameState, NarratorTurn


def model_json_schema(model_type: Type[BaseModel]) -> dict[str, Any]:
    return model_type.model_json_schema()


INITIAL_GAME_STATE_SCHEMA = InitialGameState.model_json_schema()
NARRATOR_TURN_SCHEMA = NarratorTurn.model_json_schema()
