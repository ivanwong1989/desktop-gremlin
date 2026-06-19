from __future__ import annotations


class GameDomainError(ValueError):
    """Raised by game-domain services when a typed model is semantically invalid."""


class InitialStateGenerationError(GameDomainError):
    """Raised when the LLM cannot produce a valid initial game state."""


class NarratorTurnError(GameDomainError):
    """Raised when the narrator cannot produce a valid turn."""


class InvalidStateChangeError(GameDomainError):
    """Raised when a proposed state change is not valid for the current game state."""
