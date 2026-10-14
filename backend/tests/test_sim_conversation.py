import asyncio
import copy
import json

import pytest
from pipecat.adapters.schemas.tools_schema import ToolsSchema
from pipecat.adapters.services.open_ai_adapter import OpenAILLMAdapter
from pipecat.processors.aggregators import async_tool_messages

import simfakes
from simfakes import BOOKING_AGENT, BOOKING_CALLER, TEST, call, caller, say
from agent_builder import AgentBuilder
from agent_builder.builder import TRANSFER_TASK
from clinic import ClinicWorld
from sim import config
from sim.conversation import Conversation
from sim.runner import simulate
from sim.testfile import resolve_world


def run(coro):
    return asyncio.run(coro)


def seed_world() -> ClinicWorld:
    return ClinicWorld.from_file(config.SEED)


def booking(example, agent=BOOKING_AGENT, callers=BOOKING_CALLER, test=TEST):
    models = simfakes.models(agent=copy.deepcopy(agent), caller=copy.deepcopy(callers))
    return run(simulate(example, test, models)), models


# ---- conformance with the live bot (acceptance: same functions per node) -------------------
@pytest.mark.parametrize("which", ["example", "agent"])
def test_each_node_offers_what_the_bot_offers(which, request):
    agent = request.getfixturevalue(which)
    world = seed_world()
    builder = AgentBuilder.from_dict(agent, world)
    adapter = OpenAILLMAdapter()
    for node in agent["nodes"]:
        conversation = Conversation(agent, seed_world(), simfakes.models())
        conversation._enter(conversation.builder.build_node(node["name"]))
        config_ = builder.build_node(node["name"])
        # What Pipecat's OpenAI service sends for the node's functions.
        live_tools = adapter.to_provider_tools_format(
            ToolsSchema(standard_tools=[f.to_function_schema() for f in config_["functions"]])
        )
        assert conversation.tools == live_tools
        assert [t["function"]["name"] for t in conversation.tools] == [
            e["function"] for e in node.get("edges", [])
        ] + node.get("tools", [])
        assert conversation.system == config_["role_message"]
        assert conversation.system.endswith(world.date_line())
        assert conversation.messages == node["task_messages"]


def test_the_request_is_what_the_live_service_builds(example):
    conversation = Conversation(example, seed_world(), simfakes.models())
    conversation._enter(conversation.builder.build_initial_node())
    request = conversation.request()
    assert request["model"] == example["model"]
    assert request["messages"][0] == {"role": "system", "content": conversation.system}
    assert request["tools"] == conversation.tools
    # Same parameters as bot.py: none, so OpenAI's defaults (temperature 1).
    assert set(request) == {"model", "messages", "tools"}


# ---- a whole call ----------------------------------------------------------------------
def test_a_scripted_booking_runs_through_the_graph(example):
    record, models = booking(example)
    assert record["end_reason"] == "end_node"
    agent_turns = [t for t in record["turns"] if t["speaker"] == "agent"]
    assert [t["node"] for t in agent_turns] == [
        "greeting", "greeting", "ask_name", "ask_name", "confirm_name", "confirm_name", "verify_patient",
        "verify_patient", "verify_patient", "collect_reason", "collect_reason", "offer_times", "offer_times",
        "offer_times", "offer_times", "confirm",
    ]  # fmt: skip
    calls = [c for t in agent_turns for c in t["calls"]]
    lookup = next(c for c in calls if c["name"] == "lookup_patient")
    assert lookup["kind"] == "tool" and lookup["result"]["found"] is True
    edge = next(c for c in calls if c["name"] == "choose_intent")
    assert edge["kind"] == "edge" and edge["to"] == "ask_name" and edge["result"] == {"status": "success", "intent": "book"}
    booked = next(c for c in calls if c["name"] == "book_appointment")
    assert booked["result"]["appointment"]["appointment_id"] == "appt-0005"
    # Every caller line was answered and the agent spoke first and last.
    assert [t["text"] for t in record["turns"] if t["speaker"] == "caller"] == [
        json.loads(c.text)["say"] for c in BOOKING_CALLER
    ]
    assert record["turns"][0]["speaker"] == record["turns"][-1]["speaker"] == "agent"
    assert record["world"] == resolve_world(TEST)
    assert record["usage"]["fake-agent"]["requests"] == len(BOOKING_AGENT)


def test_calls_go_into_the_history_as_pipecat_writes_them(example):
    record, models = booking(example)
    # The request after lookup_patient carries the call, a started message and the result.
    lookup_turn = next(t for t in record["turns"] if any(c["name"] == "lookup_patient" for c in t.get("calls", [])))
    after = next(t for t in record["turns"] if t["turn"] == lookup_turn["turn"] + 1)
    call_ = lookup_turn["calls"][0]
    assert after["context"]["messages"][-3:] == [
        {
            "role": "assistant",
            "tool_calls": [
                {
                    "id": call_["id"],
                    "function": {"name": "lookup_patient", "arguments": json.dumps(call_["args"], ensure_ascii=False)},
                    "type": "function",
                }
            ],
        },
        async_tool_messages.build_started_message(call_["id"]),
        async_tool_messages.build_final_result_message(call_["id"], json.dumps(call_["result"], ensure_ascii=False)),
    ]
    # The tool kept the conversation in the node; the edge then moved it on.
    assert after["node"] == "verify_patient"


def test_a_transition_appends_the_next_nodes_task_messages(example):
    record, _ = booking(example)
    first_in_ask_name = next(t for t in record["turns"] if t.get("node") == "ask_name")
    ask_name = next(n for n in example["nodes"] if n["name"] == "ask_name")
    assert first_in_ask_name["context"]["messages"][-1] == ask_name["task_messages"][-1]
    greeting = next(n for n in example["nodes"] if n["name"] == "greeting")
    assert first_in_ask_name["context"]["messages"][0] == greeting["task_messages"][0]  # history kept (APPEND)


def test_the_world_is_fresh_for_every_test(example):
    first, _ = booking(example)
    second, _ = booking(example)  # books the same slot again: it was free again
    booked = [c for t in second["turns"] if t["speaker"] == "agent" for c in t["calls"] if c["name"] == "book_appointment"]
    assert "error" not in booked[0]["result"]


def test_the_caller_can_hang_up(example):
    record, _ = booking(
        example,
        agent=[say("Hello, how can I help?")],
        callers=[caller("Sorry, wrong number. Bye!", hang_up=True)],
    )
    assert record["end_reason"] == "caller_hung_up"
    assert record["turns"][-1] == {"turn": 2, "speaker": "caller", "text": "Sorry, wrong number. Bye!"}


def test_max_turns_stops_the_call(example):
    test = {**TEST, "max_turns": 2}
    record, _ = booking(
        example, agent=[say("Hello?"), say("Sorry?"), say("Pardon?")], callers=[caller("Hm."), caller("Hm.")], test=test
    )
    assert record["end_reason"] == "max_turns"
    assert sum(t["speaker"] == "caller" for t in record["turns"]) == 2


def test_an_agent_that_only_calls_tools_is_stopped(example):
    record, _ = booking(
        example,
        agent=[say("Hi!"), call("choose_intent", intent="book"), say("Name?"), call("record_spelling", spelled_name="A")]
        + [call("spell_again")] * 20,
        callers=[caller("Book."), caller("A.")],
    )
    assert record["end_reason"] == "agent_loop"


def test_transfer_says_one_line_then_ends(example):
    record, models = booking(
        example,
        agent=[say("Hello!"), call("transfer_to_human", reason="Asked for a person"), say("Transferring you now.")],
        callers=[caller("Can I talk to a person?")],
    )
    assert record["end_reason"] == "transfer"
    last = record["turns"][-1]
    assert last["node"] == "transfer_to_human" and last["text"] == "Transferring you now."
    assert last["context"]["messages"][-1] == {"role": "developer", "content": TRANSFER_TASK}
    assert last["context"]["tools"] == []
    assert "tools" not in models.agent.requests[-1]


def test_a_tool_error_keeps_the_call_in_the_node(example):
    record, _ = booking(
        example,
        agent=BOOKING_AGENT[:13]
        + [
            call("book_appointment", patient_id="pat-001", slot_id="dr-patel-2026-10-12-0800", reason="x"),
            say("Sorry, that time is not available. Would 9:30 work?"),
        ],
        callers=BOOKING_CALLER + [caller("No thanks, bye.", hang_up=True)],
    )
    failed = [c for t in record["turns"] for c in t.get("calls", []) if c["name"] == "book_appointment"][0]
    assert "error" in failed["result"]
    assert record["turns"][-2]["node"] == "offer_times"


def test_unknown_functions_and_bad_arguments(example):
    bad_args = say("")
    bad_args.tool_calls = [simfakes.ToolCall(id="call_x", name="choose_intent", arguments="{not json")]
    record, models = booking(
        example,
        agent=[say("Hi!"), call("book_appointment", patient_id="pat-001"), bad_args, say("Sorry, what was that?")],
        callers=[caller("Book me in."), caller("Bye.", hang_up=True)],
    )
    unknown, ignored = record["turns"][2]["calls"][0], record["turns"][3]["calls"][0]
    # A catalog tool the node does not offer is unknown, as in Pipecat: the model is told and runs again.
    assert unknown["kind"] == "unknown" and "not currently available" in unknown["result"]
    assert record["turns"][3]["context"]["messages"][-1] == {
        "role": "tool",
        "content": json.dumps(unknown["result"]),
        "tool_call_id": unknown["id"],
    }
    # Arguments that are not JSON: the call is dropped and the model is not run again for it.
    assert ignored["kind"] == "ignored"
    assert record["turns"][4]["speaker"] == "caller"


def test_tts_say_actions_are_spoken(example):
    agent = copy.deepcopy(example)
    agent["nodes"][0]["pre_actions"] = [{"type": "tts_say", "text": "Thanks for calling Riverside."}]
    agent["nodes"][0]["post_actions"] = [{"type": "tts_say", "text": "This call may be recorded."}]
    record, models = booking(agent, agent=[say("How can I help?")], callers=[caller("Bye.", hang_up=True)])
    assert [(t["text"], t.get("source")) for t in record["turns"][:3]] == [
        ("Thanks for calling Riverside.", "tts_say"),
        ("How can I help?", None),
        ("This call may be recorded.", "tts_say"),
    ]
    messages = models.agent.requests[0]["messages"]
    assert messages[1] == {"role": "assistant", "content": "Thanks for calling Riverside."}


def test_an_end_conversation_action_with_text(example):
    agent = copy.deepcopy(example)
    agent["nodes"][0]["post_actions"] = [{"type": "end_conversation", "text": "Goodbye."}]
    record, _ = booking(agent, agent=[say("We are closed today.")], callers=[])
    assert record["end_reason"] == "end_node"
    assert record["turns"][-1]["text"] == "Goodbye."


# ---- anchored replay in a test ------------------------------------------------------------
def test_recorded_answers_are_said_word_for_word(example):
    test = {**TEST, "replay": [{"question": "What is your full name?", "answer": "Anna Low pest."}]}
    callers = [caller("I'd like to book."), caller("Ana Lopez.", use_recorded=0), caller("Bye.", hang_up=True)]
    record, models = booking(example, callers=callers, test=test)
    spoken = [t for t in record["turns"] if t["speaker"] == "caller"]
    assert spoken[1] == {"turn": spoken[1]["turn"], "speaker": "caller", "text": "Anna Low pest.", "replayed": 0}
    assert record["replay"] == {"recorded": 1, "used": [0]}
    # Offered while unused, then no longer.
    assert "Anna Low pest." in models.caller.requests[1]["messages"][0]["content"]
    assert "Anna Low pest." not in models.caller.requests[2]["messages"][0]["content"]


def test_the_caller_sees_only_spoken_words(example):
    record, models = booking(example)
    seen = models.caller.requests[3]["messages"][1]["content"]  # before giving the date of birth
    assert "What is your date of birth?" in seen
    assert "choose_intent" not in seen and "name_confirmed" not in seen
    assert "Ana Lopez" in models.caller.requests[0]["messages"][0]["content"]  # the facts
