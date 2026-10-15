#
# Ask, check, repair (ADR 0012): the model answers JSON matching a schema; code checks
# the answer (the clinic loader, validate_tests, validate_agent through the operations);
# problems go back to the model, which answers again in full, at most MAX_REPAIRS more
# times. An answer that still has problems is never returned.
#

from typing import Callable

from sim.llm import ChatModel, ModelError, Usage, json_request, parse_json

from . import config

# check(answer) -> (value, problems). The value is used only when there are no problems.
Check = Callable[[dict], tuple[object, list[str]]]


class StillInvalid(Exception):
    """The answer still had problems after the last repair."""

    def __init__(self, part: str, problems: list[str]):
        self.part = part
        self.problems = problems
        super().__init__(f"{part}: {len(problems)} problem(s) left after {config.MAX_REPAIRS} repairs")


async def ask(
    model: ChatModel,
    messages: list[dict],
    name: str,
    schema: dict,
    check: Check,
    usage: Usage,
    on_repair: Callable[[int, list[str]], None] = lambda attempt, problems: None,
    max_repairs: int = config.MAX_REPAIRS,
):
    messages = list(messages)
    for attempt in range(max_repairs + 1):
        request = json_request(config.MODEL, messages, name, schema, temperature=config.TEMPERATURE)
        completion = await model.complete(request)
        usage.add(completion)
        try:
            value, problems = check(parse_json(completion))
        except ModelError as error:  # cut off or not JSON: say so and ask again
            value, problems = None, [str(error)]
        if not problems:
            return value
        if attempt < max_repairs:
            on_repair(attempt + 1, problems)
            messages += [
                {"role": "assistant", "content": completion.text},
                {"role": "user", "content": repair_message(problems)},
            ]
    raise StillInvalid(name, problems)


def repair_message(problems: list[str]) -> str:
    listed = "\n".join(f"- {p}" for p in problems[:40])
    more = f"\n- ... and {len(problems) - 40} more." if len(problems) > 40 else ""
    return (
        "Your answer has these problems:\n"
        f"{listed}{more}\n\n"
        "Fix every one and answer again with the whole corrected JSON. Change nothing else."
    )
