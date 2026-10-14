"""The fake clinic behind the agents' tools (ADR 0008): the tool catalog, the
clinics with their configuration (ADR 0016), a deterministic clinic world, and
the live state shared by voice calls."""

from .catalog import TOOLS, ToolSpec, catalog
from .clinics import DEFAULT_CLINIC, clinic_ids, clinic_of, load_seed, seed_path
from .config import CONFIG_KEYS, ConfigIssue, validate_clinic
from .live import LiveClinic
from .world import ClinicWorld, normalize_name

__all__ = [
    "TOOLS",
    "ToolSpec",
    "catalog",
    "DEFAULT_CLINIC",
    "clinic_ids",
    "clinic_of",
    "load_seed",
    "seed_path",
    "CONFIG_KEYS",
    "ConfigIssue",
    "validate_clinic",
    "ClinicWorld",
    "LiveClinic",
    "normalize_name",
]
