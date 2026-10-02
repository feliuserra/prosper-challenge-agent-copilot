import pytest

from agent_builder import AgentBuilder, AgentConfig, ValidationError, validate_agent


def problems(data) -> list[tuple]:
    return [(e.node, e.edge, e.message) for e in validate_agent(data)]


def edge(agent, node="greeting", i=0) -> dict:
    return next(n for n in agent["nodes"] if n["name"] == node)["edges"][i]


def test_example_agent_is_valid(agent):
    assert validate_agent(agent) == []
    AgentBuilder.from_dict(agent)


def test_not_an_object():
    assert problems([]) == [(None, None, "Agent must be a JSON object.")]


def test_reports_every_error_at_once(agent):
    del agent["name"]
    agent["initial_node"] = "nowhere"
    edge(agent)["target"] = "missing"
    edge(agent, "offer_times")["function"] = "has space"
    assert len(validate_agent(agent)) == 4


def test_missing_required_keys_are_errors_not_keyerror():
    errors = problems({"nodes": [{"edges": [{}]}]})
    messages = [m for _, _, m in errors]
    assert "Agent needs a name." in messages
    assert "Agent needs an initial_node." in messages
    assert "Node #1 needs a name." in messages
    assert "Edge needs a description." in messages
    assert "Edge needs a target node." in messages


def test_no_nodes():
    assert (None, None, "Agent has no nodes.") in problems({"name": "a", "initial_node": "x", "nodes": []})


def test_unknown_initial_node(agent):
    agent["initial_node"] = "nowhere"
    assert problems(agent) == [(None, None, "initial_node 'nowhere' is not a defined node.")]


def test_duplicate_node_names(agent):
    agent["nodes"][1]["name"] = "greeting"
    assert ("greeting", None, "Duplicate node name 'greeting'.") in problems(agent)


def test_unknown_edge_target(agent):
    edge(agent)["target"] = "missing"
    assert problems(agent) == [("greeting", "choose_intent", "Edge targets unknown node 'missing'.")]


@pytest.mark.parametrize("name", ["has space", "", "a" * 65, "dot.ted", "trailing\n", 7])
def test_invalid_function_names(agent, name):
    edge(agent)["function"] = name
    [(node, _, message)] = problems(agent)
    assert node == "greeting"
    assert "function name must be" in message


@pytest.mark.parametrize("name", ["a", "choose-intent_2", "A" * 64])
def test_valid_function_names(agent, name):
    edge(agent)["function"] = name
    assert problems(agent) == []


def test_duplicate_function_names_in_a_node(agent):
    greeting = agent["nodes"][0]
    greeting["edges"].append(dict(greeting["edges"][0]))
    assert problems(agent) == [
        ("greeting", "choose_intent", "Duplicate function name 'choose_intent' in this node.")
    ]


def test_same_function_name_in_different_nodes_is_fine(agent):
    edge(agent, "collect_details")["function"] = "choose_intent"
    assert problems(agent) == []


@pytest.mark.parametrize(
    "properties, message",
    [
        (["intent"], "'properties' must be an object."),
        ({"intent": "string"}, "Property 'intent' must be an object."),
        ({"intent": {}}, "Property 'intent' needs a type"),
        ({"intent": {"type": "text"}}, "Property 'intent' needs a type"),
    ],
)
def test_malformed_properties(agent, properties, message):
    edge(agent)["properties"] = properties
    [(node, fn, got)] = problems(agent)
    assert (node, fn) == ("greeting", "choose_intent")
    assert got.startswith(message)


@pytest.mark.parametrize("required", ["intent", [1], {"intent": True}])
def test_malformed_required(agent, required):
    edge(agent)["required"] = required
    assert problems(agent) == [
        ("greeting", "choose_intent", "'required' must be a list of property names.")
    ]


def test_wrong_field_types(agent):
    node = agent["nodes"][0]
    node["task_messages"] = "hello"
    node["end"] = "yes"
    messages = [m for _, _, m in problems(agent)]
    assert "'task_messages' must be a list." in messages
    assert "'end' must be true or false." in messages


def test_messages_and_actions_need_role_and_type(agent):
    node = agent["nodes"][0]
    node["task_messages"] = ["Greet the caller"]
    node["pre_actions"] = [{"text": "hi"}]
    messages = [m for _, _, m in problems(agent)]
    assert messages == ["Each task message needs a role.", "Each of 'pre_actions' needs a type."]


def test_unknown_keys_are_allowed(agent):
    agent["nodes"][0]["ui"] = {"x": 10, "y": 20}
    agent["future_field"] = True
    assert problems(agent) == []


def test_builder_raises_validation_error_with_all_records(agent):
    del agent["name"]
    edge(agent)["target"] = "missing"
    with pytest.raises(ValidationError) as exc:
        AgentBuilder.from_dict(agent)
    assert len(exc.value.errors) == 2
    assert isinstance(exc.value, ValueError)  # existing `except ValueError` callers still work


def test_constructor_validates_config_too(agent):
    config = AgentConfig.from_dict(agent)
    config.initial_node = "nowhere"
    with pytest.raises(ValidationError):
        AgentBuilder(config)
