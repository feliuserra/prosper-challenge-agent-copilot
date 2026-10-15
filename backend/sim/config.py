#
# Pinned models and runner settings (ADR 0010), in one place.
#
# The agent runs with its own `model` from the agent JSON and no other parameters,
# exactly as bot.py does (OpenAI's defaults, so temperature 1). The caller and the
# judge are pinned to dated versions here. Chosen on 2026-10-12 from what the
# company key lists (see the #26 PR): every model there allows 10k+ requests and
# 30M+ tokens a minute, so the limit on parallel requests is for politeness, not
# to stay under a quota.
#

from pathlib import Path

# A small, fast, non-reasoning model plays the caller (about 0.5 s a reply).
CALLER_MODEL = "gpt-4.1-mini-2025-04-14"
# Provisional: #27 picks the cheapest judge that reaches the calibration bar (ADR 0011).
JUDGE_MODEL = "gpt-4.1-2025-04-14"

# Bump when the runner changes how it runs or grades a call: cached results
# from an older runner are then ignored.
RUNNER_VERSION = "27.1"

# Default for a test without `max_turns`: the most caller turns before the runner
# stops the call.
DEFAULT_MAX_TURNS = 20
# Model calls the agent may make in a row without the caller speaking (tool after
# tool). Past this the call ends as `agent_loop`.
MAX_AGENT_STEPS = 8

# OpenAI client: the SDK retries 408/409/429/5xx and connection errors with
# exponential backoff; after that the test is reported as `error`.
MAX_RETRIES = 5
REQUEST_TIMEOUT_SECS = 60
MAX_PARALLEL_REQUESTS = 16

CACHE_DIR = Path(__file__).parent.parent / ".sim-cache"

# The spend log (#27): one line per model request, written by the model client.
SPEND_LEDGER = Path(__file__).parent.parent / ".spend" / "ledger.jsonl"

# USD per million tokens (input, cached input, output), OpenAI's list prices, for
# the cost estimates. Cached input is the part of the prompt OpenAI served from its
# prompt cache (a repeated prefix of 1,024 tokens or more), billed at the lower rate.
# Matched by the longest prefix of the model name the API reports.
PRICES = {
    "gpt-4o-mini": (0.15, 0.075, 0.60),
    "gpt-4o": (2.50, 1.25, 10.00),
    "gpt-4.1-nano": (0.10, 0.025, 0.40),
    "gpt-4.1-mini": (0.40, 0.10, 1.60),
    "gpt-4.1": (2.00, 0.50, 8.00),
}


def price(model: str) -> tuple[float, float, float] | None:
    matches = [prefix for prefix in PRICES if model.startswith(prefix)]
    return PRICES[max(matches, key=len)] if matches else None


def cost(model: str, input_tokens: int, cached_tokens: int, output_tokens: int) -> float | None:
    """Estimated USD for one model's tokens, or None when it has no price. `input_tokens`
    counts the cached ones too, as the API does."""
    prices = price(model)
    if prices is None:
        return None
    uncached = input_tokens - cached_tokens
    return (uncached * prices[0] + cached_tokens * prices[1] + output_tokens * prices[2]) / 1_000_000
