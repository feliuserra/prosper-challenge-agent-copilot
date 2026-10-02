#
# Agent validation — every problem at once, each tied to a node and edge (ADR 0004).
#
# Works on the raw dict, before AgentConfig.from_dict, so a missing key or a wrong
# type becomes an error record instead of a KeyError that hides everything else.
# The checks cover what would otherwise fail at load time or, worse, mid-call when
# the conversation reaches a node (nodes are built lazily on transition).
#

import re
from dataclasses import asdict, dataclass
from typing import Any, Optional

# What the LLM APIs accept as a tool name.
FUNCTION_NAME_RE = re.compile(r"[a-zA-Z0-9_-]{1,64}")
JSON_SCHEMA_TYPES = {"string", "number", "integer", "boolean", "array", "object"}


@dataclass
class ValidationIssue:
    message: str
    node: Optional[str] = None  # node name, when the problem belongs to a node
    edge: Optional[str] = None  # edge function name, when it belongs to an edge

    def to_dict(self) -> dict:
        return asdict(self)


class ValidationError(ValueError):
    """Raised for an invalid agent; carries every problem found."""

    def __init__(self, errors: list[ValidationIssue]):
        self.errors = errors
        super().__init__("; ".join(e.message for e in errors))


def validate_agent(data: Any) -> list[ValidationIssue]:
    """Return every problem with an agent dict. An empty list means it is valid."""
    if not isinstance(data, dict):
        return [ValidationIssue("Agent must be a JSON object.")]

    errors: list[ValidationIssue] = []
    if not _is_text(data.get("name")):
        errors.append(ValidationIssue("Agent needs a name."))
    for key in ("persona", "voice_id", "model"):
        if key in data and not isinstance(data[key], str):
            errors.append(ValidationIssue(f"'{key}' must be a string."))

    nodes = data.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        errors.append(ValidationIssue("Agent has no nodes."))
        nodes = []

    # First pass: node names, so edge targets can be checked against all of them.
    names: set[str] = set()
    for i, node in enumerate(nodes):
        if not isinstance(node, dict):
            errors.append(ValidationIssue(f"Node #{i + 1} must be an object."))
            continue
        name = node.get("name")
        if not _is_text(name):
            errors.append(ValidationIssue(f"Node #{i + 1} needs a name."))
        elif name in names:
            errors.append(ValidationIssue(f"Duplicate node name '{name}'.", node=name))
        else:
            names.add(name)

    initial = data.get("initial_node")
    if not _is_text(initial):
        errors.append(ValidationIssue("Agent needs an initial_node."))
    elif names and initial not in names:
        errors.append(ValidationIssue(f"initial_node '{initial}' is not a defined node."))

    for node in nodes:
        if isinstance(node, dict):
            errors.extend(_validate_node(node, names))
    return errors


def _validate_node(node: dict, names: set[str]) -> list[ValidationIssue]:
    name = node.get("name") if _is_text(node.get("name")) else None
    errors: list[ValidationIssue] = []

    for key in ("task_messages", "pre_actions", "post_actions", "edges"):
        if key in node and not isinstance(node[key], list):
            errors.append(ValidationIssue(f"'{key}' must be a list.", node=name))
    # Messages and actions are passed to Pipecat Flows as they are; only check the
    # shape that would otherwise fail when the call reaches this node.
    for message in _list(node.get("task_messages")):
        if not isinstance(message, dict) or not _is_text(message.get("role")):
            errors.append(ValidationIssue("Each task message needs a role.", node=name))
    for key in ("pre_actions", "post_actions"):
        for action in _list(node.get(key)):
            if not isinstance(action, dict) or not _is_text(action.get("type")):
                errors.append(ValidationIssue(f"Each of '{key}' needs a type.", node=name))
    if "role_message" in node and not isinstance(node["role_message"], (str, type(None))):
        errors.append(ValidationIssue("'role_message' must be a string.", node=name))
    if "end" in node and not isinstance(node["end"], bool):
        errors.append(ValidationIssue("'end' must be true or false.", node=name))

    edges = node.get("edges")
    seen: set[str] = set()
    for i, edge in enumerate(_list(edges)):
        if not isinstance(edge, dict):
            errors.append(ValidationIssue(f"Edge #{i + 1} must be an object.", node=name))
            continue
        function = edge.get("function")
        if not isinstance(function, str) or not FUNCTION_NAME_RE.fullmatch(function):
            errors.append(
                ValidationIssue(
                    f"Edge #{i + 1} function name must be 1-64 letters, digits, '_' or '-'.",
                    node=name,
                    edge=function if isinstance(function, str) else None,
                )
            )
        elif function in seen:
            errors.append(
                ValidationIssue(
                    f"Duplicate function name '{function}' in this node.", node=name, edge=function
                )
            )
        else:
            seen.add(function)
        errors.extend(_validate_edge(edge, names, node=name))
    return errors


def _validate_edge(edge: dict, names: set[str], node: Optional[str]) -> list[ValidationIssue]:
    function = edge.get("function") if isinstance(edge.get("function"), str) else None
    errors: list[ValidationIssue] = []

    def issue(message: str) -> None:
        errors.append(ValidationIssue(message, node=node, edge=function))

    # Required by the schema; an empty description is only a client-side warning.
    if not isinstance(edge.get("description"), str):
        issue("Edge needs a description.")

    target = edge.get("target")
    if not _is_text(target):
        issue("Edge needs a target node.")
    elif target not in names:
        issue(f"Edge targets unknown node '{target}'.")

    properties = edge.get("properties", {})
    if not isinstance(properties, dict):
        issue("'properties' must be an object.")
        properties = {}
    for prop, spec in properties.items():
        if not isinstance(spec, dict):
            issue(f"Property '{prop}' must be an object.")
        elif spec.get("type") not in JSON_SCHEMA_TYPES:
            issue(f"Property '{prop}' needs a type: one of {', '.join(sorted(JSON_SCHEMA_TYPES))}.")

    required = edge.get("required", [])
    if not isinstance(required, list) or not all(isinstance(r, str) for r in required):
        issue("'required' must be a list of property names.")
    return errors


def _list(value: Any) -> list:
    return value if isinstance(value, list) else []


def _is_text(value: Any) -> bool:
    return isinstance(value, str) and value.strip() != ""
