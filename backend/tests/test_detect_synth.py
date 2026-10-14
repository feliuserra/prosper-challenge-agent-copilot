import json

import pytest

from detect import summary, synth


def small_scenario() -> dict:
    """The demo scenario at a twentieth of the volume: same shape, quick to generate."""
    scene = synth.scenario()
    for clinic in scene["clinics"]:
        clinic["calls_per_week"] = max(30, clinic["calls_per_week"] // 20)
    return scene


@pytest.fixture(scope="module")
def demo(demo_logs):
    return demo_logs


# ---- the same seed gives the same logs ---------------------------------------------------

def test_same_seed_same_logs(tmp_path):
    synth.write(tmp_path / "a", seed=7, scene=small_scenario())
    synth.write(tmp_path / "b", seed=7, scene=small_scenario())
    for name in ("calls.jsonl", "records.jsonl", "labels.json"):
        assert (tmp_path / "a" / name).read_bytes() == (tmp_path / "b" / name).read_bytes()


def test_another_seed_other_logs():
    first, _, _ = synth.generate(small_scenario(), seed=7)
    second, _, _ = synth.generate(small_scenario(), seed=8)
    assert first != second


def test_a_clinic_does_not_change_the_others():
    """Each clinic draws from its own stream, so the scenario can grow without
    reshuffling the logs the measurements were made on."""
    scene = small_scenario()
    alone = dict(scene, clinics=[scene["clinics"][2]])
    calls, _, _ = synth.generate(scene, seed=7)
    only, _, _ = synth.generate(alone, seed=7)
    def shape(call):  # phone numbers are numbered by the clinic's place in the list
        return call["id"], call["start"], call["path"], call["tools"], call["ended"]

    assert [shape(c) for c in calls if c["clinic"] == "maple-street"] == [shape(c) for c in only]


def test_read_returns_what_was_written(tmp_path):
    calls, records, _ = synth.write(tmp_path, seed=7, scene=small_scenario())
    assert synth.read(tmp_path) == (calls, records)


# ---- planted rates ----------------------------------------------------------------------

def test_planted_rates_are_within_tolerance(demo):
    calls, records, labels = demo
    rows = synth.check(calls, records, labels)
    assert {row["id"] for row in rows} == {d["id"] for d in labels["defects"]} | {"below-min-effect"}
    for row in rows:
        assert row["ok"], row


def test_base_rates_hold_where_nothing_is_planted(demo):
    """The stall raises Confirm name's re-entries in version 3 only; before it they are
    at the clinic's base."""
    calls, records, labels = demo
    riverside = next(c for c in labels["clinics"] if c["id"] == "riverside")
    base = riverside["base"]["confirm_name.reentry"]
    k, n = synth.measure(calls, records, clinic="riverside", node="confirm_name", signal="reentry", versions=[1, 2])
    assert abs(k / n - base) < 0.004
    assert 0.018 <= base <= 0.022


def test_labels_list_defects_and_what_must_not_be_flagged(demo):
    _, _, labels = demo
    shapes = {d["shape"] for d in labels["defects"]}
    assert {"stall", "leak", "detour", "silent", "error"} <= shapes
    for defect in labels["defects"]:
        assert defect["rate"] > defect["base"]
        assert defect["versions"] and defect["node"] and defect["signal"] in synth.SIGNALS
    assert {m["id"] for m in labels["must_not_flag"]} == {"hang-up-after-cancel", "quiet-clinic-noise", "below-min-effect"}


def test_volumes_and_versions(demo):
    calls, _, labels = demo
    per_clinic = {c["id"]: c["calls"] for c in labels["clinics"]}
    assert per_clinic["riverside"] > 60_000  # about 50,000 calls a month
    assert 8_000 < per_clinic["linden-grove"] < 12_000
    assert 800 < per_clinic["maple-street"] < 1_300
    assert sum(per_clinic.values()) == len(calls)
    assert {(c["clinic"], c["version"]) for c in calls} == {
        ("riverside", 1), ("riverside", 2), ("riverside", 3), ("linden-grove", 1), ("linden-grove", 2),
        ("maple-street", 1), ("maple-street", 2)}


def test_sweep_plants_the_excess_over_the_clinics_base():
    calls, records, labels = synth.generate(synth.sweep_scenario(1500, 0.03), seed=3)
    (defect,) = labels["defects"]
    assert defect["rate"] == pytest.approx(defect["base"] + 0.03, abs=1e-5)
    (row,) = synth.check(calls, records, labels)
    assert row["ok"], row
    assert {c["version"] for c in calls} == {1, 2}


# ---- the logs follow the template's graph ------------------------------------------------

def test_every_path_follows_its_versions_graph(demo):
    calls, _, labels = demo
    template = json.loads(synth.TEMPLATE.read_text())
    graphs = {}
    for clinic in labels["clinics"]:
        for version in clinic["versions"]:
            agent = synth.graph_for(template, clinic, version["version"])
            graphs[(clinic["id"], version["version"])] = (agent["initial_node"], {n["name"]: n for n in agent["nodes"]})
    for call in calls:
        initial, nodes = graphs[(call["clinic"], call["version"])]
        assert call["path"][0][0] == initial
        for before, visit in zip(call["path"], call["path"][1:]):
            edge = next(e for e in nodes[before[0]]["edges"] if e["function"] == visit[2])
            assert edge["target"] == visit[0]
        for node, tool, ok in call["tools"]:
            assert tool in nodes[node].get("tools", []), (call["id"], node, tool)
        assert (call["ended"] == "completed") == bool(nodes[call["path"][-1][0]].get("end"))
        assert call["ended"] in summary.ENDINGS
        assert all(turns >= 1 for _, turns, *_ in call["path"])
        assert call["start"] < call["end"]


def test_transfers_only_where_the_version_has_the_tool(demo):
    calls, _, _ = demo
    from_verify = {(c["clinic"], c["version"]) for c in calls
                   if c["ended"] == "transfer" and c["path"][-1][0] == "verify_patient"}
    assert from_verify == {("linden-grove", 2)}


def test_records_point_at_their_calls(demo):
    calls, records, _ = demo
    by_id = {c["id"]: c for c in calls}
    for record in records:
        if record.get("call") is None:
            continue
        call = by_id[record["call"]]
        tool = {"patient": "register_patient", "booking": "book_appointment"}.get(record["type"])
        if record["type"] == "booking_change":
            tool = "cancel_appointment" if record["action"] == "cancelled" else "reschedule_appointment"
        assert any(t[1] == tool and t[2] for t in call["tools"]), record


def test_a_duplicate_shares_birth_date_and_phone_under_another_name(demo):
    _, records, _ = demo
    patients = [r for r in records if r["type"] == "patient" and r["clinic"] == "linden-grove"]
    by_key = {}
    for p in patients:
        by_key.setdefault((p["dob"], p["phone"]), []).append(p)
    pairs = [group for group in by_key.values() if len(group) > 1]
    assert pairs
    for group in pairs:
        assert len({p["name"] for p in group}) > 1
        assert group[-1]["call"]  # the new chart came from a call


# ---- a simulated call reduces to the same summary ----------------------------------------

def test_from_sim_record():
    record = {
        "start_node": "greeting",
        "end_reason": "transfer",
        "turns": [
            {"turn": 1, "speaker": "agent", "node": "greeting", "text": "Hi", "calls": []},
            {"turn": 2, "speaker": "caller", "text": "I'd like to book"},
            {"turn": 3, "speaker": "agent", "node": "greeting", "text": "",
             "calls": [{"name": "choose_intent", "kind": "edge", "to": "ask_name", "args": {}}]},
            {"turn": 4, "speaker": "agent", "node": "ask_name", "text": "Your name?", "calls": []},
            {"turn": 5, "speaker": "caller", "text": "Ana Lopez"},
            {"turn": 6, "speaker": "agent", "node": "ask_name", "text": "",
             "calls": [{"name": "lookup_patient", "kind": "tool", "args": {}, "result": {"error": "No patient"}},
                       {"name": "find_slots", "kind": "tool", "args": {}, "result": {"slots": []}},
                       {"name": "transfer_to_human", "kind": "tool", "args": {}, "result": {"status": "ok"}}]},
            {"turn": 7, "speaker": "agent", "node": "transfer_to_human", "text": "Transferring you.", "calls": []},
            {"turn": 8, "speaker": "agent", "node": "ask_name", "source": "tts_say", "text": "Bye"},
        ],
    }
    out = summary.from_sim_record(record, id="sim-1", clinic="riverside", version=1, start="2026-10-12T09:00:00",
                                  end="2026-10-12T09:02:00", caller="555-010-1234")
    assert out["path"] == [["greeting", 2], ["ask_name", 2, "choose_intent"]]
    assert out["tools"] == [["ask_name", "lookup_patient", False], ["ask_name", "find_slots", True],
                            ["ask_name", "transfer_to_human", True]]
    assert out["ended"] == "transfer"
    assert out["source"] == "simulated"
    assert summary.from_sim_record(dict(record, end_reason="max_turns"), id="x", clinic="c", version=1,
                                   start="", end="", caller="")["ended"] == "hang_up"
