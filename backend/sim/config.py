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
RUNNER_VERSION = "26.1"

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

SEED = Path(__file__).parent.parent / "clinic" / "seed.json"
CACHE_DIR = Path(__file__).parent.parent / ".sim-cache"

# USD per million tokens (input, output), list prices, for the cost estimate the
# CLI prints. Cached-input discounts are ignored, so the estimate is an upper bound.
# Matched by the longest prefix of the model name the API reports.
PRICES = {
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
    "gpt-4.1-nano": (0.10, 0.40),
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4.1": (2.00, 8.00),
}


def price(model: str) -> tuple[float, float] | None:
    matches = [prefix for prefix in PRICES if model.startswith(prefix)]
    return PRICES[max(matches, key=len)] if matches else None
