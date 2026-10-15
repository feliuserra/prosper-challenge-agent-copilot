import copy
import json
from pathlib import Path

import pytest

from agent_builder import validate_agent
from copilot.ops import OPERATIONS, apply_operations, empty_carriers, tool_schemas

CASES = Path(__file__).parent / "fixtures" / "ops"
BASE = json.loads((CASES / "base.json").read_text())


def cases():
    return sorted(p for p in CASES.glob("*.json") if p.name != "base.json")


@pytest.mark.parametrize("path", cases(), ids=lambda p: p.stem)
def test_operation_cases(path):
    """Operations in, expected agent and requirement map out (or the error), on the base agent."""
    case = json.loads(path.read_text())
    agent, carriers = copy.deepcopy(BASE["agent"]), copy.deepcopy(BASE["carriers"])
    result = apply_operations(agent, case["operations"], carriers, case.get("requirements"))

    assert agent == BASE["agent"] and carriers == BASE["carriers"]  # applied to a copy
    if "error" in case:
        assert not result.ok
        assert any(case["error"] in error for error in result.errors), result.errors
    else:
        assert result.ok, result.errors
        assert result.agent == case["expected"]
        assert result.carriers == case["carriers"]
        assert result.applied == len(case["operations"])


def test_the_base_agent_is_valid():
    assert validate_agent(BASE["agent"]) == []


def test_a_failed_operation_stops_the_run():
    ops = [
        {"op": "rename_node", "name": "ask", "new_name": "ask_name"},
        {"op": "delete_node", "name": "missing"},
        {"op": "rename_node", "name": "end", "new_name": "goodbye"},
    ]
    result = apply_operations(BASE["agent"], ops)
    assert result.errors == ["Operation 2 (delete_node): No node 'missing'. Nodes: start, ask_name, end."]
    assert result.applied == 1
    assert [n["name"] for n in result.agent["nodes"]] == ["start", "ask_name", "end"]


def test_an_empty_list_validates_the_agent_as_it_is():
    result = apply_operations(BASE["agent"], [])
    assert result.ok and result.agent == BASE["agent"] and result.carriers == empty_carriers()
    broken = {**BASE["agent"], "initial_node": "nowhere"}
    assert apply_operations(broken, []).errors == ["Invalid agent: initial_node 'nowhere' is not a defined node."]


def test_the_template_can_be_customised():
    """A small customisation of the real template, as #30 will make it."""
    template = json.loads((Path(__file__).parent.parent / "agents" / "prosper-scheduler.json").read_text())
    ops = [
        {"op": "update_agent", "patch": {"name": "Linden Grove Scheduler"}, "requirements": ["R1"]},
        {"op": "update_node", "name": "greeting", "patch": {"task_messages": [{"role": "developer", "content": "Say: Thank you for calling."}]}, "requirements": ["R2"]},
        {"op": "rename_node", "name": "confirm", "new_name": "booked"},
    ]
    result = apply_operations(template, ops, requirements=["R1", "R2"])
    assert result.ok, result.errors
    assert result.carriers == {"configuration": {}, "nodes": {"greeting": ["R2"]}, "persona": ["R1"]}
    offer = next(n for n in result.agent["nodes"] if n["name"] == "offer_times")
    assert offer["edges"][0]["target"] == "booked"


def test_tool_schemas_cover_every_operation():
    tools = tool_schemas()
    assert [t["function"]["name"] for t in tools] == list(OPERATIONS)
    rename = next(t for t in tools if t["function"]["name"] == "rename_node")["function"]["parameters"]
    assert rename["required"] == ["name", "new_name"]
