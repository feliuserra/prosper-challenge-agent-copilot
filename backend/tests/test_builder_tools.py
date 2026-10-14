import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest
from pipecat.processors.frameworks.rtvi import RTVIServerMessageFrame

from agent_builder import AgentBuilder
from agent_builder.builder import TRANSFER_TASK
from clinic import ClinicWorld

# The #25 clinic, without configuration (ADR 0016).
SEED = Path(__file__).parent / "fixtures" / "clinic-plain.json"


class FakeFlowManager:
    def __init__(self):
        self.state = {}
        self.frames = []

        async def queue_frame(frame):
            self.frames.append(frame)

        self.worker = SimpleNamespace(queue_frame=queue_frame)


@pytest.fixture
def world() -> ClinicWorld:
    return ClinicWorld.from_file(SEED)


def node_config(agent: dict, world, name: str = "greeting"):
    builder = AgentBuilder.from_dict(agent, world)
    return builder._make_node(next(n for n in builder.config.nodes if n.name == name))


def function(config, name):
    return next(f for f in config["functions"] if f.name == name)


def test_tools_are_offered_after_the_edges(agent, world):
    agent["nodes"][0]["tools"] = ["lookup_patient", "find_slots"]
    config = node_config(agent, world)
    assert [f.name for f in config["functions"]] == ["choose_intent", "lookup_patient", "find_slots"]
    find_slots = function(config, "find_slots")
    assert "earliest first" in find_slots.description
    assert set(find_slots.properties) == {"date_from", "date_to", "provider", "time_of_day"}


def test_the_clinic_date_is_added_to_the_system_message(agent, world):
    role = node_config(agent, world)["role_message"]
    assert role.startswith(agent["persona"])
    assert role.endswith(world.date_line())


def test_without_a_clinic_the_system_message_is_unchanged(agent):
    builder = AgentBuilder.from_dict(agent)
    assert builder.build_initial_node()["role_message"] == agent["persona"]


def test_a_tool_runs_stays_in_the_node_and_tells_the_ui(agent, world):
    agent["nodes"][0]["tools"] = ["lookup_patient"]
    flow = FakeFlowManager()
    args = {"full_name": "Ana Lopez", "date_of_birth": "1984-03-12"}
    result, next_node = asyncio.run(function(node_config(agent, world), "lookup_patient").handler(args, flow))
    assert result["found"] is True
    assert next_node is None
    [frame] = flow.frames
    assert isinstance(frame, RTVIServerMessageFrame)
    assert frame.data == {"type": "tool_call", "node": "greeting", "tool": "lookup_patient", "args": args, "result": result}


def test_a_tool_changes_the_world(agent, world):
    agent["nodes"][0]["tools"] = ["book_appointment"]
    args = {"patient_id": "pat-001", "slot_id": "dr-patel-2026-10-12-0930", "reason": "x"}
    asyncio.run(function(node_config(agent, world), "book_appointment").handler(args, FakeFlowManager()))
    assert world.call("book_appointment", args) == {"error": "That slot is no longer free. Call find_slots again."}


def test_transfer_says_one_line_then_ends_the_call(agent, world):
    agent["nodes"][0]["tools"] = ["transfer_to_human"]
    result, next_node = asyncio.run(
        function(node_config(agent, world), "transfer_to_human").handler({"reason": "Asked for a person"}, FakeFlowManager())
    )
    assert result == {"transferred": True}
    assert next_node["task_messages"] == [{"role": "developer", "content": TRANSFER_TASK}]
    assert next_node["functions"] == []
    assert next_node["post_actions"] == [{"type": "end_conversation"}]
    assert next_node["role_message"].endswith(world.date_line())


def test_a_tool_without_a_clinic_answers_an_error(agent):
    agent["nodes"][0]["tools"] = ["find_slots"]
    builder = AgentBuilder.from_dict(agent)
    config = builder.build_initial_node()
    result, next_node = asyncio.run(function(config, "find_slots").handler({}, FakeFlowManager()))
    assert "error" in result and next_node is None


def test_the_example_agent_builds_every_node_with_its_tools(example, world):
    builder = AgentBuilder.from_dict(example, world)
    for node in builder.config.nodes:
        names = [f.name for f in builder._make_node(node)["functions"]]
        assert names == [e.function for e in node.edges] + node.tools
