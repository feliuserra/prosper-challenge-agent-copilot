#
# make eval SPEC=<workspace>:  uv run python -m eval --spec WORKSPACE
#
# Compares a workspace's spec (#29) with clinic-a's ground truth, which only the harness
# may read: the extracted configuration against backend/clinic/clinics/linden-grove.json,
# entry by entry. Entries are matched by name (providers by surname), since ids are the
# Copilot's choice; then every value the tools use is compared. No model calls.
#

import json
import re
import unicodedata

from clinic import load_seed

TRUTH_CLINIC = "linden-grove"


def compare(extracted: dict, truth: dict) -> tuple[int, list[str]]:
    """(entries that match, the differences). The clock, patients and appointments are the
    clinic system's, not the guidelines', and are not compared."""
    same, diffs = 0, []

    def check(label: str, ours, theirs) -> None:
        nonlocal same
        if ours == theirs:
            same += 1
        else:
            diffs.append(f"{label}: extracted {_show(ours)}, truth {_show(theirs)}")

    check("clinic name", extracted["clinic"]["name"], truth["clinic"]["name"])

    providers = _match(extracted["providers"], truth["providers"], _surname, "provider", diffs)
    provider_ids = {ours["id"]: theirs["id"] for ours, theirs in providers}
    for ours, theirs in providers:
        label = f"provider {theirs['name']}"
        check(f"{label}: slot_minutes", ours.get("slot_minutes", 30), theirs.get("slot_minutes", 30))
        check(f"{label}: schedule", ours.get("schedule", {}), theirs.get("schedule", {}))
        check(f"{label}: specialty", _norm(ours.get("specialty", "")), _norm(theirs.get("specialty", "")))

    types = _match(extracted.get("appointment_types", []), truth.get("appointment_types", []), lambda t: _norm(t["name"]), "appointment type", diffs)
    type_ids = {ours["id"]: theirs["id"] for ours, theirs in types}
    for ours, theirs in types:
        label = f"type {theirs['name']}"
        check(f"{label}: patients", ours.get("patients", "any"), theirs.get("patients", "any"))
        check(f"{label}: providers", sorted(provider_ids.get(p, p) for p in ours["providers"]), sorted(theirs["providers"]))

    plans = _match(extracted.get("insurance_plans", []), truth.get("insurance_plans", []), lambda p: _norm(p["name"]), "plan", diffs)
    for ours, theirs in plans:
        check(f"plan {theirs['name']}: covers", sorted(type_ids.get(t, t) for t in ours.get("covers", [])), sorted(theirs.get("covers", [])))

    for key in ("registration_fields", "booking_fields"):
        fields = _match(extracted.get(key, []), truth.get(key, []), lambda f: f["name"], key.replace("_", " ")[:-1], diffs, pair_rest=True)
        for ours, theirs in fields:
            check(f"{key} {theirs['name']}: required", bool(ours.get("required")), bool(theirs.get("required")))

    check("cancellation", extracted.get("cancellation"), truth.get("cancellation"))
    ours, theirs = set(extracted.get("facts", {})), set(truth.get("facts", {}))
    check("fact labels", sorted(ours), sorted(theirs))
    return same, diffs


def report(spec: dict, truth: dict | None = None) -> str:
    truth = truth or load_seed(TRUTH_CLINIC)
    lines = []
    requirements, tests = spec["requirements"], spec["tests"]
    tested = {r for t in tests for r in t.get("requirements", [])}
    lines.append(
        f"{len(requirements)} requirements ({sum(r['baseline'] for r in requirements)} baseline, "
        f"{sum(r['question'] is not None for r in requirements)} from client questions), "
        f"{len(spec['questions'])} client questions, {len(tests)} tests "
        f"({sum(t['tier'] == 'safety' for t in tests)} safety); untested: "
        f"{', '.join(r['id'] for r in requirements if r['id'] not in tested) or 'none'}"
    )
    if spec.get("configuration") is None:
        return "\n".join(lines + ["No configuration in the spec."])
    same, diffs = compare(spec["configuration"], truth)
    lines.append(f"Configuration against {TRUTH_CLINIC}.json: {same} values match, {len(diffs)} differ")
    lines += [f"  - {d}" for d in diffs]
    return "\n".join(lines)


def _match(ours: list[dict], theirs: list[dict], key, what: str, diffs: list[str], pair_rest: bool = False) -> list[tuple[dict, dict]]:
    """Pairs of entries with the same key. With `pair_rest`, entries left on both sides are
    paired in order and reported as named differently (a field's name is the Copilot's
    choice, like an id); the others are reported as extra or missing."""
    by_key = {key(t): t for t in theirs}
    pairs, seen, extra = [], set(), []
    for entry in ours:
        match = by_key.get(key(entry))
        if match is None:
            extra.append(entry)
        else:
            pairs.append((entry, match))
            seen.add(key(entry))
    missing = [t for k, t in by_key.items() if k not in seen]
    if pair_rest:
        for entry, match in zip(extra, missing):
            diffs.append(f"{what} named {_show(_label(entry))}, truth {_show(_label(match))}")
            pairs.append((entry, match))
        extra, missing = extra[len(missing):], missing[len(extra):]
    diffs += [f"extra {what}: {_show(_label(e))}" for e in extra]
    diffs += [f"missing {what}: {_show(_label(t))}" for t in missing]
    return pairs


def _label(entry: dict):
    return entry.get("name", entry.get("id"))


TITLES = {"dr", "np", "md", "do", "pa", "rn", "fnp", "mr", "mrs", "ms"}


def _surname(provider: dict) -> str:
    words = [w for w in _norm(provider["name"]).split() if w not in TITLES]
    return words[-1] if words else _norm(provider["name"])


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).casefold()
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def _show(value) -> str:
    return json.dumps(value, ensure_ascii=False)
