#
# The Copilot's model and settings (ADR 0014), in one place. Its requests go through
# the runner's model client (sim/llm.py), so they land in the spend log as `copilot`.
#

from pathlib import Path

# Writes the spec. gpt-4.1 is the model the judge calibration trusted (32 of 32 labels,
# #27), follows strict JSON schemas, and costs a few cents per part. Temperature 0, so a
# rerun on the same guidelines gives about the same spec.
MODEL = "gpt-4.1-2025-04-14"
TEMPERATURE = 0

# A part whose answer has problems (a configuration the loader rejects, a test that does
# not validate) gets them back for at most this many more tries (ADR 0012).
MAX_REPAIRS = 2

# Tests: a person reviews every one, and each costs a few cents per run. The plan names
# them; batches of this size are then written at the same time.
MAX_TESTS = 25
TESTS_PER_BATCH = 5

# The clock of a clinic the Copilot drafts: a fixed Monday morning, so a test that says
# "tomorrow" or "in five hours" means the same on every run and cached results stay valid.
CLINIC_NOW = "2026-10-19T08:00"

# The build's loop (#30): at most this many rounds of diagnose, change and rerun. A round
# whose change no failing test passes with costs no full rerun.
MAX_ROUNDS = 3

PROMPTS = Path(__file__).parent / "prompts"


def prompt(name: str) -> str:
    return (PROMPTS / name).read_text()
