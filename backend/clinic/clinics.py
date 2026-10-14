#
# The clinics an agent can run against (ADR 0016): one JSON file per clinic in
# clinics/, named by its id. An agent names its clinic in an optional `clinic`
# field; without one it runs against the default clinic.
#

import json
import re
from pathlib import Path

CLINICS_DIR = Path(__file__).parent / "clinics"
DEFAULT_CLINIC = "riverside"
CLINIC_ID_RE = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}")


def clinic_ids() -> list[str]:
    return sorted(p.stem for p in CLINICS_DIR.glob("*.json") if CLINIC_ID_RE.fullmatch(p.stem))


def seed_path(clinic_id: str) -> Path:
    """The seed file of a clinic. Raises KeyError for an unknown clinic."""
    if not isinstance(clinic_id, str) or clinic_id not in clinic_ids():
        raise KeyError(f"Unknown clinic '{clinic_id}'. Clinics: {', '.join(clinic_ids())}.")
    return CLINICS_DIR / f"{clinic_id}.json"


def load_seed(clinic_id: str) -> dict:
    return json.loads(seed_path(clinic_id).read_text())


def clinic_of(agent) -> str:
    """The clinic an agent runs against."""
    clinic = agent.get("clinic") if isinstance(agent, dict) else None
    return clinic or DEFAULT_CLINIC
