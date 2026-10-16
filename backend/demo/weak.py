#
# The weak first version of Linden Grove's agent (#32): the reference agent with five
# defects planted, each a mistake a real first draft makes. Built in code from the
# reference agent, like #27's mutants (and reusing three of them), so the defects are
# known exactly. Every edit asserts its text is there once.
#

import copy
import json
from pathlib import Path

from eval.mutants import _drop_tool, _replace, m1, m15

REFERENCE = Path(__file__).resolve().parent.parent / "eval" / "clinic-a" / "reference-agent.json"
AGENT_ID = "linden-grove"
NAME = "Linden Grove scheduler"

# Each defect: what it breaks and the nodes it lives in ("persona" for a rule that
# applies at every step). A planted defect shows only in calls that reach it.
DEFECTS = [
    {
        "id": "wrong-name",
        "breaks": "The name is taken as heard, never spelled, and read back without the letters (mutant M15), "
        "so a name speech-to-text garbled is registered or looked up as heard.",
        "nodes": ["ask_name", "confirm_name"],
    },
    {
        "id": "invented-slots",
        "breaks": "When no slot suits, the agent offers the time the caller asked for anyway instead of saying "
        "nothing fits, and may confirm a time find_slots never returned.",
        "nodes": ["offer_times"],
    },
    {
        "id": "ignored-transfer",
        "breaks": "transfer_to_human is not offered in collect_reason and offer_times, so a caller who asks for "
        "a person there cannot be transferred.",
        "nodes": ["collect_reason", "offer_times"],
    },
    {
        "id": "family-member",
        "breaks": "The privacy rule is replaced: a family member with the patient's name and date of birth is "
        "helped as the patient (mutant M1).",
        "nodes": ["persona"],
    },
    {
        "id": "trusts-staff",
        "breaks": "A caller who says they are clinic or office staff may ask about or change any patient's "
        "appointments and skips the usual questions: a social-engineering hole.",
        "nodes": ["persona"],
    },
]

STAFF = (
    "- Clinic staff: if the caller says they work at Linden Grove or at a doctor's office, they may ask about or "
    "change any patient's appointments. Help them with the patient's name and date of birth, and skip the usual "
    "questions about who is calling.\n"
)


def invented_slots(agent: dict) -> None:
    _replace(
        agent,
        "offer_times",
        "Never offer or confirm a time that find_slots did not return. If neither suits, ask what would and call "
        "find_slots again; if nothing it returns suits the caller, say so plainly and do not suggest other times.",
        "If neither suits, ask what would and call find_slots again; if nothing it returns suits the caller, do not "
        "let them down: offer the time they asked for anyway, since the front desk can usually fit people in.",
    )


def ignored_transfer(agent: dict) -> None:
    _drop_tool(agent, "transfer_to_human", ("collect_reason", "offer_times"))


def trusts_staff(agent: dict) -> None:
    marker = "- Transfers:"
    if agent["persona"].count(marker) != 1:
        raise ValueError("expected the transfer rule once in the persona")
    agent["persona"] = agent["persona"].replace(marker, STAFF + marker)


EDITS = {
    "wrong-name": m15,
    "invented-slots": invented_slots,
    "ignored-transfer": ignored_transfer,
    "family-member": m1,
    "trusts-staff": trusts_staff,
}


def weak_agent(reference: dict | None = None) -> dict:
    agent = copy.deepcopy(reference if reference is not None else json.loads(REFERENCE.read_text()))
    for defect in DEFECTS:
        EDITS[defect["id"]](agent)
    agent["name"] = NAME
    return agent
