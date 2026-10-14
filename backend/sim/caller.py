#
# The simulated caller (ADR 0009): a small model playing the patient from the
# test's caller card (persona, goal, facts, style).
#
# Recorded words. A test made from a real call carries `replay`: the caller's
# turns as speech-to-text heard them, each with the question it answered. Each
# turn the model says whether the agent's latest line asks for the same thing as
# a recorded question; if so, the caller says the recorded answer word for word
# (garbles included), and the code, not the model, puts the words in. Spelled
# letters are assumed to be heard right; only garbles from real calls come back.
#   - anchored (tests): any unused recorded answer can match, so a fixed agent
#     that asks one more question first still gets the recorded answers after it;
#   - strict (continue_from): only the next recorded answer, in order; the first
#     time the agent asks something else the call has diverged, and from then on
#     the caller improvises.
#

from . import config
from .llm import ChatModel, Usage, json_request, parse_json

SCHEMA = {
    "type": "object",
    "properties": {
        "say": {"type": "string"},
        "hang_up": {"type": "boolean"},
        "use_recorded": {"type": ["integer", "null"]},
    },
    "required": ["say", "hang_up", "use_recorded"],
    "additionalProperties": False,
}

RULES = """\
Speak as a person on the phone: one short turn, plain words, no lists, no stage directions. \
Say dates the way people do ("March 12th, 1984"). When asked to spell something, spell it letter \
by letter ("A, N, A"). Answer what the assistant asks; give a fact when it is asked for, not all \
at once. If you are asked something you do not know, say so. Never say you are an AI, a \
simulation or a test.

Hang up (hang_up: true) only when the call is over: the assistant has confirmed your goal is done \
(for example, said the appointment is booked or cancelled) and has said goodbye, the assistant says \
it is transferring you, or it clearly cannot help. Choosing an option or answering a question never \
ends the call: after you speak, wait for the assistant's reply. When you hang up, "say" holds your \
last words or is empty. Otherwise "say" is never empty."""


class Caller:
    def __init__(
        self,
        card: dict,
        model: ChatModel,
        replay: list[dict] | None = None,
        strict: bool = False,
        model_name: str = config.CALLER_MODEL,
    ):
        self.card = card
        self.model = model
        self.model_name = model_name
        self.replay = list(replay or [])
        self.strict = strict
        self.used: set[int] = set()
        self.diverged_at: int | None = None  # strict: turn number of the first improvised answer

    async def next(self, turns: list[dict], usage: Usage) -> tuple[str, bool, dict]:
        """What the caller says next given the call so far: (words, hang_up, extra turn fields)."""
        offered = self._offered()
        request = json_request(
            self.model_name,
            [
                {"role": "system", "content": self._system(offered)},
                {"role": "user", "content": f"The call so far:\n{transcript(turns)}\n\nWhat do you say next?"},
            ],
            "caller_turn",
            SCHEMA,
        )
        completion = await self.model.complete(request)
        usage.add(completion)
        answer = parse_json(completion)
        text, hang_up, index = answer["say"].strip(), bool(answer["hang_up"]), answer["use_recorded"]
        if index in offered:
            self.used.add(index)
            return self.replay[index]["answer"], hang_up, {"replayed": index}
        if self.strict and self.diverged_at is None:
            self.diverged_at = len(turns) + 1
        return text, hang_up, {}

    def _offered(self) -> list[int]:
        unused = [i for i in range(len(self.replay)) if i not in self.used]
        if not self.strict:
            return unused
        # Strict: the next answer in order, until the first divergence.
        return unused[:1] if self.diverged_at is None else []

    def _system(self, offered: list[int]) -> str:
        card = self.card
        facts = "\n".join(f"- {key}: {value}" for key, value in (card.get("facts") or {}).items()) or "- (none)"
        parts = [
            "You are role-playing a patient who has phoned a healthcare clinic. An automated voice "
            "assistant answers the line. Reply with what you say next, as the caller.",
            f"Who you are: {card['persona']}",
            f"Why you are calling: {card['goal']}",
            f"What you know (say each fact when it is asked for):\n{facts}",
        ]
        if card.get("style"):
            parts.append(f"How you talk: {card['style']}")
        parts.append(RULES)
        if offered:
            recorded = "\n".join(
                f'{i}. Question: "{self.replay[i]["question"]}" Answer: "{self.replay[i]["answer"]}"' for i in offered
            )
            parts.append(
                "Recorded answers. In the real call this comes from, you answered these questions with "
                f"these exact words:\n{recorded}\n"
                "If the assistant's latest message asks for the same thing as one of these questions, set "
                "use_recorded to its number: your words are then replaced by that answer exactly, as the real "
                "caller said it. Use it even when the recorded answer covers only part of what the assistant "
                "asked, as real callers often do; the assistant will ask again for the rest. Do not use it when "
                "it no longer makes sense: a time you pick must be among the times just offered, and a yes or "
                "no must answer what was just read back. Otherwise set use_recorded to null and answer yourself."
            )
        else:
            parts.append("Set use_recorded to null.")
        return "\n\n".join(parts)


def transcript(turns: list[dict]) -> str:
    """The spoken part of the call, as the caller heard it."""
    lines = []
    for turn in turns:
        if turn["speaker"] == "caller":
            lines.append(f"You: {turn['text']}")
        elif turn["text"]:
            lines.append(f"Assistant: {turn['text']}")
    if not any(turn["text"] for turn in _since_last_caller_turn(turns)):
        lines.append("Assistant: (says nothing)")
    return "\n".join(lines)


def _since_last_caller_turn(turns: list[dict]) -> list[dict]:
    for i in range(len(turns) - 1, -1, -1):
        if turns[i]["speaker"] == "caller":
            return turns[i + 1 :]
    return turns


def recorded_answers(turns: list[dict], from_turn: int = 1) -> list[dict]:
    """The caller's words from `from_turn` on, each with what the agent said just before."""
    answers, said = [], []
    for turn in turns:
        if turn["speaker"] == "agent":
            if turn["text"]:
                said.append(turn["text"])
            continue
        if turn["turn"] >= from_turn:
            answers.append({"question": " ".join(said), "answer": turn["text"]})
        said = []
    return answers
