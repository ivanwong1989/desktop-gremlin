from __future__ import annotations

from enum import StrEnum


class PlayerActionSource(StrEnum):
    TEXT = "text"
    CHOICE = "choice"


class StateChangeOperation(StrEnum):
    SET_FLAG = "set_flag"
    REMOVE_FLAG = "remove_flag"
    ADD_ITEM = "add_item"
    REMOVE_ITEM = "remove_item"
    MOVE_CHARACTER = "move_character"
    CREATE_CHARACTER = "create_character"
    UPDATE_CHARACTER = "update_character"
    CREATE_LOCATION = "create_location"
    DISCOVER_LOCATION = "discover_location"
    START_QUEST = "start_quest"
    UPDATE_QUEST = "update_quest"
    COMPLETE_QUEST = "complete_quest"
    FAIL_QUEST = "fail_quest"
    SET_GAME_TIME = "set_game_time"
    ADVANCE_GAME_TIME = "advance_game_time"
    SET_PRESENT_CHARACTERS = "set_present_characters"
