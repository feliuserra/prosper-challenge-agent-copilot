#
# Edit operations (ADR 0012): how the Copilot changes an agent. The same rules as the
# editor store (frontend/src/store/agentStore.ts): a node's name is its identifier, so
# a rename cascades to edge targets and the start node; deleting a node removes the
# edges into it and refuses the start node; function names are unique per node; in a
# patch, null removes a key.
#
# Operations are applied to a copy and the result is validated with validate_agent.
# The first operation that fails stops the run, and an agent with errors comes back
# with ok false: callers write or propose only agents that are ok. The errors are
# worded for the model, which gets them back to repair its operations (copilot/repair.py).
#
# Requirement map (ADR 0015, narrowed on 2026-10-15): an operation may cite the
# requirement ids it serves. The citations live in the workspace, not in the agent:
#
#   carriers = {"configuration": {entry: [ids]}, "nodes": {node: [ids]}, "persona": [ids]}
#
# Node operations and edge operations cite for the node (an edge's node), update_agent
# for the persona. Renames move a node's list and deletes drop it, so the map follows
# the operations. Edits made later in the editor do not update it (#31 shows the gaps).
#
# Python only: the TypeScript copy and the cases shared with Vitest were cut on
# 2026-10-15. The browser only shows the agent the backend streams.
#

import copy
from dataclasses import dataclass, field

from agent_builder.validation import FUNCTION_NAME_RE, validate_agent
from clinic.catalog import TOOLS

STRINGS = {"type": "array", "items": {"type": "string"}}
REQUIREMENTS = {**STRINGS, "description": "The requirement ids this operation serves, such as R3 or B1."}
OBJECT = {"type": "object"}

# Operation -> (what it does, {argument: (JSON schema, required?)}). Drives both the
# argument checks and the tool definitions the model sees (tool_schemas).
OPERATIONS: dict[str, tuple[str, dict]] = {
    "add_node": (
        "Add a node. Connect it with add_edge.",
        {
            "name": ({"type": "string", "description": "The node's name, its identifier (snake_case)."}, True),
            "task_messages": ({"type": "array", "items": OBJECT, "description": "[{role, content}], as in the agent JSON."}, False),
            "role_message": ({"type": "string"}, False),
            "end": ({"type": "boolean", "description": "True for a node that ends the call after its reply."}, False),
            "stage": ({"type": "string", "description": "The stage the node belongs to on the canvas."}, False),
            "requirements": (REQUIREMENTS, False),
        },
    ),
    "update_node": (
        "Change a node's prompts, end flag, actions or stage. A null value removes the key.",
        {
            "name": ({"type": "string"}, True),
            "patch": (OBJECT, True),
            "requirements": (REQUIREMENTS, False),
        },
    ),
    "rename_node": (
        "Rename a node. Edges into it and the start node follow.",
        {"name": ({"type": "string"}, True), "new_name": ({"type": "string"}, True)},
    ),
    "delete_node": (
        "Delete a node and the edges into it. The start node cannot be deleted.",
        {"name": ({"type": "string"}, True)},
    ),
    "add_edge": (
        "Add an edge: a function the model calls in `node` to move to `target`.",
        {
            "node": ({"type": "string"}, True),
            "function": ({"type": "string", "description": "1 to 64 letters, digits, '_' or '-', unique in the node."}, True),
            "target": ({"type": "string"}, True),
            "description": ({"type": "string", "description": "When the model should call it."}, True),
            "properties": (OBJECT, False),
            "required": (STRINGS, False),
            "requirements": (REQUIREMENTS, False),
        },
    ),
    "update_edge": (
        "Change an edge's function name, description, target or fields. A null value removes the key.",
        {
            "node": ({"type": "string"}, True),
            "function": ({"type": "string"}, True),
            "patch": (OBJECT, True),
            "requirements": (REQUIREMENTS, False),
        },
    ),
    "delete_edge": (
        "Delete an edge.",
        {"node": ({"type": "string"}, True), "function": ({"type": "string"}, True)},
    ),
    "set_initial_node": ("Choose the node the call starts in.", {"name": ({"type": "string"}, True)}),
    "set_tools": (
        "Set the catalog tools a node offers (replaces its list; an empty list removes them).",
        {
            "node": ({"type": "string"}, True),
            "tools": (STRINGS, True),
            "requirements": (REQUIREMENTS, False),
        },
    ),
    "update_agent": (
        "Change the agent's name, persona, voice, model or clinic. A null value removes the key.",
        {"patch": (OBJECT, True), "requirements": (REQUIREMENTS, False)},
    ),
}

NODE_PATCH_KEYS = ("role_message", "task_messages", "pre_actions", "post_actions", "end", "stage")
EDGE_PATCH_KEYS = ("function", "description", "target", "properties", "required")
AGENT_PATCH_KEYS = ("name", "persona", "voice_id", "model", "clinic")
JSON_TYPES = {"string": str, "boolean": bool, "array": list, "object": dict}


class OpError(ValueError):
    """An operation that cannot apply. The message is meant for the model."""


@dataclass
class Applied:
    agent: dict  # the agent after the operations (a copy; the input is never changed)
    carriers: dict
    errors: list[str] = field(default_factory=list)
    applied: int = 0  # operations applied before the first failure

    @property
    def ok(self) -> bool:
        return not self.errors


def empty_carriers() -> dict:
    return {"configuration": {}, "nodes": {}, "persona": []}


def apply_operations(agent: dict, operations: list, carriers: dict | None = None, requirements=None) -> Applied:
    """Apply `operations` in order to a copy of `agent`, then validate the result.
    `requirements`, when given, are the ids operations may cite."""
    state = _State(copy.deepcopy(agent), copy.deepcopy(carriers) if carriers else empty_carriers(), requirements)
    if not isinstance(operations, list):
        return Applied(state.agent, state.carriers, ["Operations must be a list."])
    for i, op in enumerate(operations):
        try:
            state.apply(op)
        except OpError as error:
            name = op.get("op") if isinstance(op, dict) and isinstance(op.get("op"), str) else "?"
            return Applied(state.agent, state.carriers, [f"Operation {i + 1} ({name}): {error}"], applied=i)
    issues = validate_agent(state.agent)
    errors = [_issue_text(issue) for issue in issues]
    return Applied(state.agent, state.carriers, errors, applied=len(operations))


def tool_schemas() -> list[dict]:
    """The operations as OpenAI function tools, for the build (#30)."""
    tools = []
    for name, (description, params) in OPERATIONS.items():
        properties = {param: schema for param, (schema, _) in params.items()}
        required = [param for param, (_, needed) in params.items() if needed]
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": description,
                    "parameters": {"type": "object", "properties": properties, "required": required},
                },
            }
        )
    return tools


class _State:
    def __init__(self, agent: dict, carriers: dict, requirements):
        self.agent = agent
        self.carriers = carriers
        self.known = set(requirements) if requirements is not None else None
        if not isinstance(agent.get("nodes"), list):
            agent["nodes"] = []

    def apply(self, op) -> None:
        if not isinstance(op, dict) or op.get("op") not in OPERATIONS:
            raise OpError(f"Each operation needs an `op`: one of {', '.join(OPERATIONS)}.")
        args = {key: value for key, value in op.items() if key != "op"}
        _check_args(op["op"], args)
        cited = self._cited(args.pop("requirements", []))
        getattr(self, op["op"])(cited=cited, **args)

    # ---- nodes ---------------------------------------------------------------------
    def add_node(self, name, cited, task_messages=None, role_message=None, end=None, stage=None):
        name = _name(name)
        if self._find(name, missing_ok=True):
            raise OpError(f"A node called '{name}' already exists.")
        node = {"name": name}
        if stage is not None and stage.strip():
            node["stage"] = stage.strip()
        if role_message is not None:
            node["role_message"] = role_message
        node["task_messages"] = task_messages if task_messages is not None else [{"role": "developer", "content": ""}]
        node["edges"] = []
        if end is not None:
            node["end"] = end
        self.agent["nodes"].append(node)
        self._carry(name, cited)

    def update_node(self, name, patch, cited):
        node = self._find(name)
        _merge(node, patch, NODE_PATCH_KEYS, "a node", hint="Use rename_node, set_tools or the edge operations for the rest.")
        self._carry(name, cited)

    def rename_node(self, name, new_name, cited):
        node = self._find(name)
        new_name = _name(new_name)
        if new_name == name:
            return
        if self._find(new_name, missing_ok=True):
            raise OpError(f"A node called '{new_name}' already exists.")
        node["name"] = new_name
        for other in self.agent["nodes"]:
            for edge in _edges(other):
                if edge.get("target") == name:
                    edge["target"] = new_name
        if self.agent.get("initial_node") == name:
            self.agent["initial_node"] = new_name
        nodes = self.carriers["nodes"]
        if name in nodes:
            nodes[new_name] = _union(nodes.pop(name), nodes.get(new_name, []))

    def delete_node(self, name, cited):
        self._find(name)
        if self.agent.get("initial_node") == name:
            raise OpError("This is the start node. Choose another start node with set_initial_node before deleting it.")
        self.agent["nodes"] = [n for n in self.agent["nodes"] if n.get("name") != name]
        for other in self.agent["nodes"]:
            if any(edge.get("target") == name for edge in _edges(other)):
                other["edges"] = [edge for edge in _edges(other) if edge.get("target") != name]
        self.carriers["nodes"].pop(name, None)

    def set_initial_node(self, name, cited):
        self._find(name)
        self.agent["initial_node"] = name

    def set_tools(self, node, tools, cited):
        target = self._find(node)
        unknown = [t for t in tools if t not in TOOLS]
        if unknown:
            raise OpError(f"Unknown tool {', '.join(map(repr, unknown))}. Tools: {', '.join(TOOLS)}.")
        if len(set(tools)) != len(tools):
            raise OpError("A tool is listed twice.")
        clash = [t for t in tools if any(edge.get("function") == t for edge in _edges(target))]
        if clash:
            raise OpError(f"'{clash[0]}' is already an edge function in node '{node}'.")
        if tools:
            target["tools"] = list(tools)
        else:
            target.pop("tools", None)
        self._carry(node, cited)

    # ---- edges ---------------------------------------------------------------------
    def add_edge(self, node, function, target, description, cited, properties=None, required=None):
        source = self._find(node)
        _function_name(function)
        if any(edge.get("function") == function for edge in _edges(source)):
            raise OpError(f"'{function}' is already used by another edge of node '{node}'.")
        if function in source.get("tools", []):
            raise OpError(f"'{function}' is a tool of node '{node}'; edge functions and tools need different names.")
        self._find(target, what="target node")
        edge = {"function": function, "description": description, "target": target}
        if properties is not None:
            edge["properties"] = properties
        if required is not None:
            edge["required"] = required
        source.setdefault("edges", []).append(edge)
        self._carry(node, cited)

    def update_edge(self, node, function, patch, cited):
        source = self._find(node)
        edge = self._edge(source, function)
        renamed = patch.get("function", function)
        if renamed != function:
            if renamed is None:
                raise OpError("An edge needs a function name; it cannot be removed.")
            _function_name(renamed)
            if any(other.get("function") == renamed for other in _edges(source)):
                raise OpError(f"'{renamed}' is already used by another edge of node '{node}'.")
        if patch.get("target") is not None:
            self._find(patch["target"], what="target node")
        _merge(edge, patch, EDGE_PATCH_KEYS, "an edge")
        self._carry(node, cited)

    def delete_edge(self, node, function, cited):
        source = self._find(node)
        self._edge(source, function)
        source["edges"] = [edge for edge in _edges(source) if edge.get("function") != function]

    # ---- the agent -----------------------------------------------------------------
    def update_agent(self, patch, cited):
        _merge(self.agent, patch, AGENT_PATCH_KEYS, "the agent", hint="Use the node operations and set_initial_node for the rest.")
        self.carriers["persona"] = _union(self.carriers["persona"], cited)

    # ---- helpers -------------------------------------------------------------------
    def _find(self, name, missing_ok=False, what="node"):
        for node in self.agent["nodes"]:
            if isinstance(node, dict) and node.get("name") == name:
                return node
        if missing_ok:
            return None
        names = ", ".join(str(n.get("name")) for n in self.agent["nodes"] if isinstance(n, dict))
        raise OpError(f"No {what} '{name}'. Nodes: {names}.")

    @staticmethod
    def _edge(node, function):
        for edge in _edges(node):
            if edge.get("function") == function:
                return edge
        functions = ", ".join(str(e.get("function")) for e in _edges(node)) or "none"
        raise OpError(f"No edge '{function}' in node '{node['name']}'. Its edges: {functions}.")

    def _cited(self, ids) -> list[str]:
        if self.known is not None:
            unknown = [i for i in ids if i not in self.known]
            if unknown:
                raise OpError(f"Unknown requirement id {', '.join(map(repr, unknown))}.")
        return list(ids)

    def _carry(self, node, cited) -> None:
        if cited:
            nodes = self.carriers["nodes"]
            nodes[node] = _union(nodes.get(node, []), cited)


def _check_args(name: str, args: dict) -> None:
    params = OPERATIONS[name][1]
    unknown = [key for key in args if key not in params]
    if unknown:
        raise OpError(f"Unknown argument {', '.join(map(repr, unknown))}. Arguments: {', '.join(params)}.")
    for param, (schema, required) in params.items():
        if param not in args or args[param] is None:
            if required:
                raise OpError(f"Needs `{param}`.")
            args.pop(param, None)
            continue
        kind = JSON_TYPES[schema["type"]]
        value = args[param]
        if not isinstance(value, kind) or (kind is not bool and isinstance(value, bool)):
            raise OpError(f"`{param}` must be {'an' if schema['type'][0] in 'ao' else 'a'} {schema['type']}.")
        if schema["type"] == "array" and schema.get("items", {}).get("type") == "string":
            if not all(isinstance(item, str) for item in value):
                raise OpError(f"`{param}` must be a list of strings.")


def _merge(target: dict, patch: dict, allowed, what: str, hint: str = "") -> None:
    bad = [key for key in patch if key not in allowed]
    if bad:
        raise OpError(f"Cannot set {', '.join(map(repr, bad))} on {what} here. Keys: {', '.join(allowed)}. {hint}".strip())
    for key, value in patch.items():
        if value is None:
            target.pop(key, None)
        else:
            target[key] = value


def _name(name: str) -> str:
    name = name.strip()
    if not name:
        raise OpError("Node name cannot be empty.")
    return name


def _function_name(function: str) -> None:
    if not FUNCTION_NAME_RE.fullmatch(function):
        raise OpError(f"Function name '{function}' must be 1 to 64 letters, digits, '_' or '-' (no spaces).")


def _edges(node: dict) -> list:
    edges = node.get("edges")
    return edges if isinstance(edges, list) else []


def _union(a: list, b: list) -> list:
    return a + [x for x in b if x not in a]


def _issue_text(issue) -> str:
    where = " ".join(part for part in (f"node '{issue.node}'" if issue.node else "", f"edge '{issue.edge}'" if issue.edge else "") if part)
    return f"Invalid agent{f' ({where})' if where else ''}: {issue.message}"
