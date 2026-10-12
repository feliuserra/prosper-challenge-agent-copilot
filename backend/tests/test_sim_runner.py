import asyncio
import copy
import json

import simfakes
from simfakes import API_DOWN, TEST, caller, say, verdict
from sim.runner import blocking, cache_key, run_suite, run_test

# A call the judge grades: the agent greets, the caller hangs up.
HELLO = [say("Hello, how can I help?")]
BYE = [caller("Bye.", hang_up=True)]
JUDGED = {**TEST, "checks": [{"type": "judge", "rule": "Greets the caller."}]}


def run(agent, test, models, tmp_path, use_cache=True):
    return asyncio.run(run_test(agent, test, models, use_cache=use_cache, cache_dir=tmp_path))


def test_a_pass_runs_once(example, tmp_path):
    models = simfakes.models(agent=HELLO, caller=BYE, judge=[verdict(True)])
    result = run(example, JUDGED, models, tmp_path)
    assert result["status"] == "pass" and len(result["runs"]) == 1 and not result["cached"]
    assert result["models"]["agent"] == "gpt-4o" and result["runner_version"]
    assert result["usage"]["fake-agent"]["requests"] == 1 and result["usage"]["fake-judge"]["requests"] == 1


def test_a_failure_is_rerun_once(example, tmp_path):
    models = simfakes.models(agent=HELLO * 2, caller=BYE * 2, judge=[verdict(False), verdict(False)])
    result = run(example, JUDGED, models, tmp_path)
    assert result["status"] == "fail" and len(result["runs"]) == 2
    assert all(not r["passed"] for r in result["runs"])


def test_fail_then_pass_is_flaky(example, tmp_path):
    models = simfakes.models(agent=HELLO * 2, caller=BYE * 2, judge=[verdict(False), verdict(True)])
    result = run(example, JUDGED, models, tmp_path)
    assert result["status"] == "flaky" and [r["passed"] for r in result["runs"]] == [False, True]
    assert not blocking(result)
    assert blocking({**result, "tier": "safety"})  # flaky safety tests count as failures


def test_results_are_cached(example, tmp_path):
    first = run(example, JUDGED, simfakes.models(agent=HELLO, caller=BYE, judge=[verdict(True)]), tmp_path)
    empty = simfakes.models()  # would fail on any request
    second = run(example, JUDGED, empty, tmp_path)
    assert second["cached"] and second["status"] == "pass" and second["runs"] == first["runs"]
    assert empty.agent.requests == empty.caller.requests == empty.judge.requests == []
    assert (tmp_path / f"{first['key']}.json").is_file()


def test_no_cache_runs_again(example, tmp_path):
    run(example, JUDGED, simfakes.models(agent=HELLO, caller=BYE, judge=[verdict(True)]), tmp_path)
    models = simfakes.models(agent=HELLO, caller=BYE, judge=[verdict(True)])
    result = run(example, JUDGED, models, tmp_path, use_cache=False)
    assert not result["cached"] and len(models.agent.requests) == 1


def test_the_cache_key_follows_what_decides_a_result(example):
    key = cache_key(example, JUDGED)
    moved = copy.deepcopy(example)
    moved["nodes"][0]["ui"] = {"x": 10, "y": 20}
    assert cache_key(moved, JUDGED) == key
    reworded = copy.deepcopy(example)
    reworded["nodes"][0]["task_messages"][0]["content"] += " Be brief."
    assert cache_key(reworded, JUDGED) != key
    assert cache_key(example, {**JUDGED, "max_turns": 5}) != key
    assert cache_key(example, {**JUDGED, "world": {"patients": []}}) != key


def test_an_api_failure_is_an_error_and_not_cached(example, tmp_path):
    models = simfakes.models(agent=[API_DOWN])
    result = run(example, JUDGED, models, tmp_path)
    assert result["status"] == "error" and result["error"] == "RateLimitError 429: slow down"
    assert result["runs"] == [] and blocking(result)
    assert list(tmp_path.iterdir()) == []


def test_an_error_on_the_rerun_is_an_error(example, tmp_path):
    models = simfakes.models(agent=HELLO + [API_DOWN], caller=BYE, judge=[verdict(False)])
    result = run(example, JUDGED, models, tmp_path)
    assert result["status"] == "error" and len(result["runs"]) == 1


def test_a_suite_runs_every_test(example, tmp_path):
    tests = [JUDGED, {**JUDGED, "id": "second"}]
    models = simfakes.models(agent=HELLO * 2, caller=BYE * 2, judge=[verdict(True)] * 2)
    results = asyncio.run(run_suite(example, tests, models, cache_dir=tmp_path))
    assert [r["test_id"] for r in results] == ["book-existing", "second"]
    assert [r["status"] for r in results] == ["pass", "pass"]


def test_results_are_json(example, tmp_path):
    result = run(example, JUDGED, simfakes.models(agent=HELLO, caller=BYE, judge=[verdict(True)]), tmp_path)
    assert json.loads(json.dumps(result)) == result
