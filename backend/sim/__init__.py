"""The text runner (ADR 0009, 0010, 0015): simulated calls against an agent JSON,
graded by tests, plus turn replay and continuing recorded calls.

    uv run python -m sim run <agent.json> <tests.json>
"""

from .conversation import Conversation, ReplayError
from .llm import ChatModel, Completion, ModelError, Models, ToolCall, models
from .replay import continue_from, replay_turn
from .runner import blocking, run_suite, run_test, simulate
from .testfile import load_tests, validate_tests

__all__ = [
    "ChatModel",
    "Completion",
    "Conversation",
    "ModelError",
    "Models",
    "ReplayError",
    "ToolCall",
    "blocking",
    "continue_from",
    "load_tests",
    "models",
    "replay_turn",
    "run_suite",
    "run_test",
    "simulate",
    "validate_tests",
]
