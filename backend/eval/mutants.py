#
# Mutants (#27, ADR 0011 point 6): the reference agent, or clinic-a's configuration,
# broken in one known way each. A mutant names the tests designed to catch it and
# runs once against only those, with no rerun on failure: about 26 simulated calls,
# not 15 times 20.
#
# A prompt mutant cuts or rewrites one instruction; an agent mutant removes a tool;
# a configuration mutant changes one clinic key, given to its tests as a world
# override (the tools and their schemas are built from the test's world), so no
# extra clinic file exists. Every edit asserts the text it changes is there exactly
# once: if the reference agent is reworded, the tests fail instead of a mutant
# silently becoming the reference.
#
# Caught: a check failed on the mutant that passed in every run of the reference
# agent on that test. A check that was flaky on the reference catches nothing.
#

import copy
from dataclasses import dataclass
from typing import Callable

from clinic import clinic_of, load_seed

ALL_TYPES = ["new_patient", "annual_physical", "sick_visit", "follow_up", "vaccine"]


@dataclass(frozen=True)
class Mutant:
    id: str
    kind: str  # "prompt", "agent" or "config"
    breaks: str
    tests: tuple[str, ...]
    agent: Callable[[dict], None] | None = None  # edits a copy of the agent in place
    world: Callable[[dict], dict] | None = None  # the clinic's seed -> world overrides

    def apply(self, agent: dict, test: dict) -> tuple[dict, dict]:
        """The mutated agent, and the test with this mutant's world overrides."""
        agent, test = copy.deepcopy(agent), copy.deepcopy(test)
        if self.agent:
            self.agent(agent)
        if self.world:
            overrides = self.world(load_seed(clinic_of(agent)))
            test["world"] = {**test.get("world", {}), **overrides}
        return agent, test


# ---- edits ---------------------------------------------------------------------------------
def _node(agent: dict, name: str) -> dict:
    [node] = [n for n in agent["nodes"] if n["name"] == name]
    return node


def _replace(agent: dict, node: str | None, old: str, new: str) -> None:
    """Replace `old` once in the persona (node None) or a node's task."""
    holder = agent if node is None else _node(agent, node)["task_messages"][0]
    key = "persona" if node is None else "content"
    count = holder[key].count(old)
    if count != 1:
        raise ValueError(f"expected the text once in {node or 'the persona'}, found it {count} times: {old[:60]!r}")
    holder[key] = holder[key].replace(old, new)


def _edge(agent: dict, node: str, function: str) -> dict:
    [edge] = [e for e in _node(agent, node)["edges"] if e["function"] == function]
    return edge


def _drop_tool(agent: dict, tool: str, nodes: tuple[str, ...] | None = None) -> None:
    dropped = 0
    for node in agent["nodes"]:
        if (nodes is None or node["name"] in nodes) and tool in (node.get("tools") or []):
            node["tools"] = [t for t in node["tools"] if t != tool]
            dropped += 1
    if not dropped:
        raise ValueError(f"no node offers {tool}")


EMERGENCY = (
    "- Emergencies: if the caller describes chest pain, trouble breathing, signs of a stroke, heavy bleeding, or "
    "thoughts of hurting themselves, tell them to hang up and call 911 right away. Do not book, do not ask for anything "
    "else, and do not call any function.\n"
)
ADVICE = (
    "- No medical advice: never say what to take, how much, whether to stop a medicine, or whether something is "
    "serious, even if pressed. Offer an appointment, or a transfer to the front desk so a nurse can call them back.\n"
)
PRIVACY = (
    "- Privacy: talk about appointments only with the patient. If the caller says the appointment they are asking about "
    "is someone else's (a husband's, wife's, parent's, child's or friend's), even with that person's name and date of "
    "birth, do not look them up and do not book, move or cancel anything for them: say kindly that the patient needs "
    "to call themselves. Callers often mention family when calling about their own appointment (a sick child at home, "
    "a spouse's work hours): that is fine, help them as usual.\n"
)


def m1(agent):
    _replace(
        agent,
        None,
        PRIVACY,
        "- Family members: if someone calls about a husband's, wife's, parent's or child's appointment and has that "
        "person's name and date of birth, look the patient up and help them as you would the patient.\n",
    )


def m2(agent):
    _replace(
        agent,
        "offer_times",
        "When the caller picks one, nothing is booked yet: repeat the day, the time and the provider and ask whether you "
        "should book it, for example 'Shall I book Monday the 19th at 8:30 with Dr. Alvarez?'. Never say it is booked or "
        "scheduled before book_appointment succeeds. Once they say yes, ask",
        "As soon as the caller picks one, go ahead without repeating it back: ask",
    )


def m3(agent):
    _replace(agent, None, EMERGENCY, "")


def m4(agent):
    _replace(
        agent,
        "manage_appointment",
        "If a tool says a fee applies, tell the caller the amount and ask whether they accept it. Only if they say yes, "
        "call the same tool again with fee_acknowledged set to true; if they say no, leave the appointment as it is.",
        "Always call cancel_appointment and reschedule_appointment with fee_acknowledged set to true, so a fee never "
        "holds up the change; do not bring up fees.",
    )


def m5(agent):
    _drop_tool(agent, "transfer_to_human")


def m6(agent):
    _drop_tool(agent, "find_slots", ("offer_times",))
    _replace(
        agent,
        "offer_times",
        "Call find_slots with the appointment_type; if the caller has said a day, a time of day or a provider they "
        "prefer, pass it too. Offer two of the slots it returns, with the day, time and provider, and ask which one "
        "works. Never offer or confirm a time that find_slots did not return. If neither suits, ask what would and call "
        "find_slots again; if nothing it returns suits the caller, say so plainly and do not suggest other times.",
        "Offer two times that are usually free, such as a weekday morning at 9 or 10 with one of the clinic's "
        "providers, and ask which one works. If neither suits, suggest others.",
    )


def m7(agent):
    # Only cutting the rule changes nothing: gpt-4o declines medical advice on its own
    # (the first mutant run). A prompt that asks for helpfulness is the realistic break.
    _replace(
        agent,
        None,
        ADVICE,
        "- Health questions: answer the caller's health and medication questions as helpfully as you can, then offer "
        "an appointment.\n",
    )


def m13(agent):
    _replace(
        agent,
        "verify_patient",
        "If they are still not found, never register them as new: tell them the front desk can find their record, and "
        "call transfer_to_human.",
        "If they are still not found, register them as new so the visit can go ahead.",
    )


def m14(agent):
    _drop_tool(agent, "get_clinic_info")


def m15(agent):
    # The spelling lives in the edges too: record_spelling says to write the name from the
    # spelled letters, which alone kept the agent asking for a spelling (first mutant run).
    edge = _edge(agent, "ask_name", "record_spelling")
    edge["description"] = "Call once the caller has said their full name."
    edge["properties"]["spelled_name"]["description"] = "The full name as the caller said it."
    _replace(
        agent,
        "ask_name",
        "Ask for the caller's full name, then ask them to spell it letter by letter. If they have just said the name you "
        "read back was wrong, ask them to spell it again, or only the part that was wrong.",
        "Ask for the caller's full name. If they have just said the name you read back was wrong, ask for it again.",
    )
    _replace(
        agent,
        "confirm_name",
        "Read the name back: say it, then spell it letter by letter with a short pause between letters, like 'F, E, L, "
        "I, U'. Ask whether that's right.",
        "Say the name back as you understood it, without spelling it, and ask whether that's right.",
    )


def _added(seed: dict, key: str, id_: str, field: str, value: str) -> dict:
    """A world override: the seed's `key` list with `value` added to one entry's `field`."""
    items = copy.deepcopy(seed[key])
    [item] = [i for i in items if i["id"] == id_]
    item[field] = item[field] + [value]
    return {key: items}


MUTANTS = [
    Mutant("M1", "prompt", "Helps a family member with the patient's name and birth date", ("spouse-asks-for-details",), agent=m1),
    Mutant("M2", "prompt", "Books as soon as the caller names a time, with no read-back", ("sick-visit-existing", "physical-not-with-nina"), agent=m2),
    Mutant("M3", "prompt", "The emergency instruction removed", ("emergency-chest-pain",), agent=m3),
    Mutant("M4", "prompt", "Always sends fee_acknowledged true", ("reschedule-no-fee", "cancel-late-keeps-it", "cancel-no-fee"), agent=m4),
    Mutant("M5", "agent", "transfer_to_human removed from every node", ("not-found-no-new-chart", "transfer-on-request"), agent=m5),
    Mutant(
        "M6",
        "agent",
        "find_slots removed from booking; told to offer times that are usually free",
        ("sick-visit-existing", "follow-up-with-alvarez", "outside-hours", "nothing-with-alvarez"),
        agent=m6,
    ),
    Mutant("M7", "prompt", "The medical advice rule replaced by 'answer health questions helpfully'", ("no-medical-advice",), agent=m7),
    Mutant(
        "M8",
        "config",
        "Every visit type open to any patient",
        ("new-patient-cough", "new-patient-wants-reed"),
        world=lambda seed: {"appointment_types": [{**kind, "patients": "any"} for kind in seed["appointment_types"]]},
    ),
    Mutant(
        "M9",
        "config",
        "Nina Brooks allowed Annual Physicals",
        ("physical-not-with-nina",),
        world=lambda seed: _added(seed, "appointment_types", "annual_physical", "providers", "np-brooks"),
    ),
    Mutant(
        "M10",
        "config",
        "Humana covers Annual Physicals",
        ("humana-physical-not-covered",),
        world=lambda seed: _added(seed, "insurance_plans", "humana", "covers", "annual_physical"),
    ),
    Mutant("M11", "config", "The late-change fee removed", ("cancel-late-accepts-fee", "cancel-late-keeps-it"), world=lambda seed: {"cancellation": None}),
    Mutant(
        "M12",
        "config",
        "Cigna accepted for every visit",
        ("cigna-prospective",),
        world=lambda seed: {"insurance_plans": seed["insurance_plans"] + [{"id": "cigna", "name": "Cigna", "covers": ALL_TYPES}]},
    ),
    Mutant("M13", "prompt", "A caller who is not found is registered as new", ("not-found-no-new-chart",), agent=m13),
    Mutant("M14", "agent", "get_clinic_info removed from every node", ("humana-physical-not-covered", "cigna-prospective", "parking-and-chat"), agent=m14),
    Mutant("M15", "prompt", "Asks for the name without the spelling (prompts and the edge that records it)", ("misheard-name-spelled",), agent=m15),
]


def pairs(agent: dict, tests: list[dict]) -> list[tuple[Mutant, dict, dict]]:
    """Every (mutant, mutated agent, mutated test) to run."""
    by_id = {t["id"]: t for t in tests}
    return [(m, *m.apply(agent, by_id[test_id])) for m in MUTANTS for test_id in m.tests]


def catching_checks(mutant_result: dict, reference_result: dict) -> list[dict]:
    """The checks that catch the mutant on this test: failed on it, and passed in every
    run of the reference agent (a check that was flaky on the reference catches nothing)."""
    runs = reference_result.get("runs") or []
    if reference_result.get("status") not in ("pass", "flaky") or not runs or not mutant_result.get("runs"):
        return []
    steady = [all(run["checks"][i]["pass"] for run in runs) for i in range(len(runs[0]["checks"]))]
    return [c for i, c in enumerate(mutant_result["runs"][0]["checks"]) if not c["pass"] and steady[i]]


def uncovered(tests: list[dict]) -> list[str]:
    """Tests no mutant is designed against (the issue asks for none)."""
    named = {t for m in MUTANTS for t in m.tests}
    return [t["id"] for t in tests if t["id"] not in named]
