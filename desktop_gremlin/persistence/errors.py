from __future__ import annotations


class GamePersistenceError(RuntimeError):
    """Base class for game persistence failures."""


class GameNotFoundError(GamePersistenceError):
    """Raised when a requested campaign save does not exist."""


class CorruptSaveError(GamePersistenceError):
    """Raised when a save file exists but cannot be parsed as valid JSON."""


class SaveValidationError(GamePersistenceError):
    """Raised when parsed save data fails schema or domain validation."""


class UnsafeGameIdError(GamePersistenceError):
    """Raised when a game ID could escape the campaigns directory."""
