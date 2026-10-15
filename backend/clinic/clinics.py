#
# The clinics an agent can run against (ADR 0016): one JSON file per clinic in
# clinics/, named by its id. An agent names its clinic in an optional `clinic`
# field; without one it runs against the default clinic.
#
# A Copilot workspace's approved configuration (#30) is a clinic too: the build writes
# it to workspaces/<id>/clinic.json, and its id is the workspace's. So the runner, the
# bot and the Clinic tab find it by the agent's `clinic` field like any other. A file
# in clinics/ wins over a workspace with the same id.
#

import json
import re
from pathlib import Path

CLINICS_DIR = Path(__file__).parent / "clinics"
WORKSPACES_DIR = Path(__file__).parent.parent / "workspaces"
WORKSPACE_CLINIC = "clinic.json"
DEFAULT_CLINIC = "riverside"
CLINIC_ID_RE = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}")


def _paths() -> dict[str, Path]:
    paths = {p.parent.name: p for p in WORKSPACES_DIR.glob(f"*/{WORKSPACE_CLINIC}") if CLINIC_ID_RE.fullmatch(p.parent.name)}
    paths.update({p.stem: p for p in CLINICS_DIR.glob("*.json") if CLINIC_ID_RE.fullmatch(p.stem)})
    return paths


def clinic_ids() -> list[str]:
    return sorted(_paths())


def seed_path(clinic_id: str) -> Path:
    """The seed file of a clinic. Raises KeyError for an unknown clinic."""
    paths = _paths()
    if not isinstance(clinic_id, str) or clinic_id not in paths:
        raise KeyError(f"Unknown clinic '{clinic_id}'. Clinics: {', '.join(sorted(paths))}.")
    return paths[clinic_id]


def load_seed(clinic_id: str) -> dict:
    return json.loads(seed_path(clinic_id).read_text())


def clinic_of(agent) -> str:
    """The clinic an agent runs against."""
    clinic = agent.get("clinic") if isinstance(agent, dict) else None
    return clinic or DEFAULT_CLINIC
