#
# Speech-to-text and the phone line, simulated (#32, moved here for #33). A text caller
# reads every word the agent writes, so it corrects a garbled name on sight (why #27's
# mutant M15 survived). A test's `hearing` is a list of [said, heard] pairs that work both
# ways: what the caller says reaches the agent as speech-to-text heard it ("Sarah
# Burrell" becomes "Sara Boreal"), and the agent's words reach the caller as they sound
# ("Sara Boreal" is heard as "Sarah Burrell"). Letters spelled out are not touched, so an
# agent that spells the name back lets the caller catch it.
#

import re

from .llm import Usage


class Hearing:
    """[said, heard] pairs, longest first."""

    def __init__(self, pairs: list[list[str]] | None):
        self.pairs = sorted(pairs or [], key=lambda pair: -len(pair[0]))

    def to_agent(self, text: str) -> str:
        return _swap(text, [(said, heard) for said, heard in self.pairs])

    def to_caller(self, text: str) -> str:
        return _swap(text, [(heard, said) for said, heard in self.pairs])


def _swap(text: str, pairs: list[tuple[str, str]]) -> str:
    if not pairs or not text:
        return text
    # Whole words only: "Sara" heard for "Sarah" must not touch "Saratoga".
    pattern = re.compile(r"\b(?:" + "|".join(re.escape(old) for old, _ in pairs) + r")\b", re.IGNORECASE)
    lookup = {old.lower(): new for old, new in pairs}
    return pattern.sub(lambda m: lookup[m.group(0).lower()], text)


class HeardCaller:
    """A Caller that hears the agent through `hearing` and is heard through it. It
    remembers its own words as it said them, not as speech-to-text wrote them down.
    Anything else (`replay`, `used`, `diverged_at`) is the caller's."""

    def __init__(self, caller, hearing: Hearing):
        self.caller = caller
        self.hearing = hearing

    def __getattr__(self, name):
        return getattr(self.caller, name)

    async def next(self, turns: list[dict], usage: Usage) -> tuple[str, bool, dict]:
        heard = [{**t, "text": self.hearing.to_caller(t["text"])} if t["text"] else t for t in turns]
        text, hang_up, extra = await self.caller.next(heard, usage)
        return self.hearing.to_agent(text), hang_up, extra


def hearing_caller(caller, pairs: list[list[str]] | None):
    """The caller as is without pairs, else heard through them."""
    return HeardCaller(caller, Hearing(pairs)) if pairs else caller


def word_pairs(said: str, heard: str) -> list[list[str]]:
    """The pair itself plus each differing word when both have as many words: "Sarah
    Burrell" heard as "Sara Boreal" also makes "Burrell" heard as "Boreal", so the
    surname alone is misheard too."""
    pairs = [[said, heard]]
    a, b = said.split(), heard.split()
    if len(a) == len(b) > 1:
        pairs += [[x, y] for x, y in zip(a, b) if x.lower() != y.lower() and len(x) > 2]
    return pairs
