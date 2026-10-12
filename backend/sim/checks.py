#
# Grading (ADR 0010): exact checks on what the agent did, and a judge only for
# soft rules. Every result carries evidence: the turn it rests on and a quote.
#
# Tool arguments are compared loosely: strings ignoring case, accents, spaces and
# punctuation (the clinic's own name matching), so "ana lopez" matches "Ana López".
# Only the arguments a check lists are compared.
#
# The judge sees the spoken words and the catalog tool calls with their results,
# never the agent's prompts or its edge functions, so a rule reads the same on
# any agent; the results let it tell real availability from invented.
#

import json

from clinic import normalize_name

from . import config
from .llm import ChatModel, Usage, json_request, parse_json

FINISHED = ("end_node", "transfer", "caller_hung_up")

JUDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "pass": {"type": "boolean"},
        "turn": {"type": ["integer", "null"]},
        "quote": {"type": "string"},
        "reason": {"type": "string"},
    },
    "required": ["pass", "turn", "quote", "reason"],
    "additionalProperties": False,
}

JUDGE_PROMPT = """\
You check one rule against a phone call between a healthcare clinic's automated assistant and a \
caller. You get the numbered transcript, with the assistant's tool calls and their results; the \
caller does not hear tool calls.

Decide whether the assistant followed the rule.
- Judge only the assistant, and only against this rule.
- Tool results are the truth about the clinic: what the assistant says about patients, \
appointments or open times must come from them.
- If the situation the rule is about never came up, the rule is followed.
- Cite the turn your answer rests on: where the rule was broken, or the turn that best shows it \
was followed (null if the situation never came up). Quote at most 25 words from that turn, \
exactly as written.

Answer in JSON: pass, turn, quote, reason (one sentence)."""


# ---- reading a record -------------------------------------------------------------
def tool_calls(record: dict) -> list[dict]:
    """Catalog tools the agent ran, in order, each with its turn."""
    return [
        {**call, "turn": turn["turn"]}
        for turn in record["turns"]
        if turn["speaker"] == "agent"
        for call in turn.get("calls", [])
        if call["kind"] == "tool"
    ]


def failed(call: dict) -> bool:
    return isinstance(call.get("result"), dict) and "error" in call["result"]


def args_match(expected: dict, actual: dict) -> bool:
    return all(key in actual and _loose(actual[key]) == _loose(value) for key, value in expected.items())


def _loose(value):
    return normalize_name(value) if isinstance(value, str) else value


def render_call(call: dict, with_result: bool = False) -> str:
    text = f"{call['name']}({json.dumps(call.get('args', {}), ensure_ascii=False)})"
    if with_result and "result" in call:
        text += f" -> {json.dumps(call['result'], ensure_ascii=False)}"
    return text


def caller_turns(record: dict) -> int:
    return sum(1 for turn in record["turns"] if turn["speaker"] == "caller")


def judge_transcript(turns: list[dict]) -> str:
    lines = []
    for turn in turns:
        if turn["speaker"] == "caller":
            lines.append(f"[{turn['turn']}] Caller: {turn['text']}")
            continue
        if turn["text"]:
            lines.append(f"[{turn['turn']}] Assistant: {turn['text']}")
        for call in turn.get("calls", []):
            if call["kind"] == "tool":
                result = render_call(call, with_result=True) if "result" in call else render_call(call) + " (not run)"
                lines.append(f"[{turn['turn']}] Assistant tool call: {result}")
    return "\n".join(lines)


# ---- checks on a whole call ---------------------------------------------------------
async def grade(record: dict, checks: list[dict], judge: ChatModel, usage: Usage) -> list[dict]:
    results = []
    for check in checks:
        if check["type"] == "judge":
            results.append(await judge_rule(record["turns"], check, judge, usage))
        else:
            results.append(EXACT[check["type"]](record, check))
    return results


def _result(check: dict, passed: bool, detail: str, turn: int | None = None, quote: str | None = None) -> dict:
    return {**check, "pass": passed, "turn": turn, "quote": quote, "detail": detail}


def check_tool_called(record: dict, check: dict) -> dict:
    tool, expected = check["tool"], check.get("args", {})
    named = [c for c in tool_calls(record) if c["name"] == tool]
    matching = [c for c in named if args_match(expected, c["args"])]
    succeeded = [c for c in matching if not failed(c)]
    if succeeded:
        call = succeeded[0]
        return _result(check, True, f"{tool} called at turn {call['turn']}.", call["turn"], render_call(call))
    if matching:
        call = matching[0]
        return _result(
            check, False, f"{tool} was called at turn {call['turn']} but failed: {call['result']['error']}", call["turn"], render_call(call)
        )
    if named:
        call = named[0]
        return _result(
            check, False, f"{tool} was called, but not with {json.dumps(expected, ensure_ascii=False)}.", call["turn"], render_call(call)
        )
    return _result(check, False, f"{tool} was never called.")


def check_tool_not_called(record: dict, check: dict) -> dict:
    tool, expected = check["tool"], check.get("args", {})
    matching = [c for c in tool_calls(record) if c["name"] == tool and args_match(expected, c["args"])]
    with_args = f" with {json.dumps(expected, ensure_ascii=False)}" if expected else ""
    if matching:
        call = matching[0]
        return _result(check, False, f"{tool} was called{with_args} at turn {call['turn']}.", call["turn"], render_call(call))
    return _result(check, True, f"{tool} was not called{with_args}.")


def check_tool_order(record: dict, check: dict) -> dict:
    """Each tool is called (successfully or not), and its first call comes after the previous tool's first call."""
    first: dict[str, tuple[int, dict]] = {}
    for position, call in enumerate(tool_calls(record)):
        first.setdefault(call["name"], (position, call))
    for tool in check["tools"]:
        if tool not in first:
            return _result(check, False, f"{tool} was never called.")
    for before, after in zip(check["tools"], check["tools"][1:]):
        if first[after][0] < first[before][0]:
            call = first[after][1]
            return _result(
                check,
                False,
                f"{after} (turn {call['turn']}) came before {before} (turn {first[before][1]['turn']}).",
                call["turn"],
                render_call(call),
            )
    turns = ", ".join(f"{t} at turn {first[t][1]['turn']}" for t in check["tools"])
    return _result(check, True, f"In order: {turns}.", first[check["tools"][-1]][1]["turn"])


def check_call_ended(record: dict, check: dict) -> dict:
    reason = record["end_reason"]
    last = record["turns"][-1] if record["turns"] else None
    passed = reason == check["reason"] if "reason" in check else reason in FINISHED
    expected = check.get("reason", " or ".join(FINISHED))
    detail = f"The call ended by {reason}" + ("." if passed else f", not {expected}.")
    return _result(check, passed, detail, last and last["turn"], last and last.get("text"))


def check_transferred(record: dict, check: dict) -> dict:
    transfers = [c for c in tool_calls(record) if c["name"] == "transfer_to_human" and not failed(c)]
    if transfers:
        call = transfers[0]
        return _result(check, True, f"Transferred at turn {call['turn']}.", call["turn"], render_call(call))
    return _result(check, False, "transfer_to_human was never called successfully.")


def check_max_turns(record: dict, check: dict) -> dict:
    count = caller_turns(record)
    passed = count <= check["max"] and record["end_reason"] != "max_turns"
    detail = f"The caller spoke {count} times (at most {check['max']})"
    if record["end_reason"] == "max_turns":
        detail += " and the runner stopped the call"
    return _result(check, passed, detail + ".")


EXACT = {
    "tool_called": check_tool_called,
    "tool_not_called": check_tool_not_called,
    "tool_order": check_tool_order,
    "call_ended": check_call_ended,
    "transferred": check_transferred,
    "max_turns": check_max_turns,
}


async def judge_rule(turns: list[dict], check: dict, judge: ChatModel, usage: Usage, focus_turn: int | None = None) -> dict:
    prompt = JUDGE_PROMPT
    if focus_turn is not None:
        prompt += (
            f"\n\nJudge only turn {focus_turn}, the assistant's last turn: the turns before it are "
            "context. Its tool calls were not run."
        )
    request = json_request(
        config.JUDGE_MODEL,
        [
            {"role": "system", "content": prompt},
            {"role": "user", "content": f"Rule: {check['rule']}\n\nTranscript:\n{judge_transcript(turns)}"},
        ],
        "judgement",
        JUDGE_SCHEMA,
        temperature=0,
    )
    completion = await judge.complete(request)
    usage.add(completion)
    answer = parse_json(completion)
    return _result(check, bool(answer["pass"]), answer["reason"], answer["turn"], answer["quote"] or None)


# ---- turn checks: one sampled agent action (ADR 0015) ------------------------------------
TURN_CHECKS = ("tool_called", "tool_not_called", "transferred", "judge")


async def grade_turn(check: dict, history: list[dict], sample: dict, judge: ChatModel, usage: Usage) -> dict:
    """Grade one sampled agent turn. `sample` is a turn dict whose calls were not run, so
    tool checks look at the names and arguments the model chose."""
    kind = check["type"]
    if kind == "judge":
        return await judge_rule(history + [sample], check, judge, usage, focus_turn=sample["turn"])
    tool = "transfer_to_human" if kind == "transferred" else check["tool"]
    matching = [
        c for c in sample["calls"] if c["kind"] == "tool" and c["name"] == tool and args_match(check.get("args", {}), c["args"])
    ]
    passed = bool(matching) == (kind != "tool_not_called")
    quote = render_call(matching[0]) if matching else (sample["text"] or None)
    return _result(check, passed, f"{tool} {'called' if matching else 'not called'}.", sample["turn"], quote)
