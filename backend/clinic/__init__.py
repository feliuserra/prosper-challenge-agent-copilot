"""The fake clinic behind the agents' tools (ADR 0008): the tool catalog, a
deterministic clinic world, and the live state shared by voice calls."""

from .catalog import TOOLS, ToolSpec, catalog
from .live import LiveClinic
from .world import ClinicWorld, normalize_name

__all__ = ["TOOLS", "ToolSpec", "catalog", "ClinicWorld", "LiveClinic", "normalize_name"]
