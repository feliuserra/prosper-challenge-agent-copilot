# The demo

Two acts, about 15 minutes, on one laptop. Act 1 builds a clinic's agent from its guidelines. Act 2 finds what goes wrong in a clinic's calls and fixes it. Everything runs live, and every long step has a switch to the result recorded in the rehearsal, so a slow model call never stalls the demo.

## Before: reset and start

```bash
make demo-reset
make dev
```

`make demo-reset` makes no model calls:

- It archives the demo agents and their workspaces to `backend/.demo-archive/<time>/`. They hold accepted fixes and builds that cost model calls and are not in git.
- It installs the weak Linden Grove agent (version 1), its 22 mock production calls, the judge's stored results and the 3 tickets.
- It removes Act 1's agent `linden-grove-new`.
- It resets the clinics' bookings and writes the synthetic call logs again (85,495 calls, about 5 s).

Then open http://localhost:5173. Check that `backend/.env` has the OpenAI and voice keys, and that the microphone works (Test call tab, one short call).

**The cached switch.** While a Copilot step runs (spec, build, tests or fix), its card shows **Use the rehearsal's result** next to Stop, when the agent has a recording of that step. It stops the live run and replays the recording: real model output from a rehearsal, about 0.6 s between events, no model calls. The card then says "rehearsal's result". Recordings live in `backend/copilot/recordings/<agent id>/`.

- `linden-grove-new/` holds spec, build and tests: clinic-a's stored spec and its first build with the test loop (#30), 15 of 25 tests passing.
- `linden-grove/` holds the fix: #33's third real run on call `lg-1019-0804`.

## Act 1: from guidelines to a live call

1. **New from example**, named `Linden Grove New` (the id becomes `linden-grove-new`, which has the recordings). Save.
2. **Copilot tab.** Paste `backend/eval/clinic-a/guidelines.md` and click **Create from guidelines**.
   - Live: about 2 minutes and $0.38 (requirements, then the configuration, then tests). Switch to the rehearsal after the requirements appear if it is slow.
   - Show: 45 requirements with their sources (baseline and question defaults marked), the client questions with **Copy for the client**, the configuration grids, and 25 tests with tiers.
3. **Approve all.** The tests are the contract: the build has to pass them.
4. **Build and test.** The template is customized in front of you: operations appear on the canvas.
   - Once the tests start, click **Use the rehearsal's result**. A live loop takes about 8 minutes and $10. The live build call itself costs cents.
5. **The honest result.** The proposal is **blocked**: 15 of 25 tests pass after the loop (14 before; one of three rounds kept). Show the diagnosis per failing test:
   - a missing transfer reason
   - get_clinic_info not offered for records
   - check_coverage not called for Cigna
   - the late-fee order
   - and so on

   This is what the tests are for: they say what the build got wrong before a patient finds it. Click **Accept anyway**. The version says "accepted while blocked".
6. **Live call** (Test call tab). Book a sick visit as a new patient. Spell the name when asked.

## Act 2: from production calls to an accepted fix

1. **Open `linden-grove`** (version 1, the weak agent that has been "in production").
2. **Call heatmap** (canvas actions). The issues panel ranks what tier 1 found on every call, with no model:
   - Linden Grove's hang-ups at Offer times against the other clinics
   - the judge's groups (the `judge` chip, "6 of 22 judged calls")

   Click an issue: the node lights up, with its evidence (Holm p-values, the weekly trend, example calls).
3. **Calls tab.** Open the wrong-name issue on `lg-1019-0804`:
   - Sarah Burrell was registered as "Sara Boreal". Speech-to-text garbled the name, and the agent never asked for the spelling.
   - Show the judge's quote, the decisive turn (4, in ask_name, selected on the canvas), the caller card and the matched ticket T1.
4. **Fix this issue.** The Copilot tab shows:
   - the reproduction from the call corrected by the ticket
   - 5 of 5 continuations failing on the current agent
   - three candidate changes, each replayed on the decisive turn (5/5, 3/5, 0/5), then reproduced in full (3/5, 4/5, 5/5)

   The turn replay ranked them in reverse, so the full rate chooses: candidate 3, a self-loop that asks for the spelling again.
   - Live: about 4 minutes and $6. Switch to the rehearsal once the candidates are listed.
5. **The proposal.** The reproduction passes 5 of 5 after the fix. 12 of the 13 tests rerun pass. It is blocked only by `transfer-running-late`, which was flaky before the fix and fails in greeting, a node the fix does not touch. **Accept anyway**: version 2, and the issue shows "fixed in v2".
6. **Live call.** Give a name that is easy to mishear. The agent asks for the spelling, and `register_patient` gets the spelled name. This is the call the user made on 2026-10-18 against version 2.

#35 (inspector, chart, ablation) was not built, so it is not in the demo.

## Rehearsal

The acceptance criterion: from `make demo-reset`, both acts run end to end twice in a row with no manual fixes.

- **Rehearsal with the switch (no model calls but the live ones).** `make demo-reset`, `make dev`, and both acts with the switch at every long step. Costs the live calls, the spec if it is run live (about $0.38) and the start of the build (cents).
- **Refreshing a recording.** `make dev REHEARSE=1` records every live step that ends well into its agent's folder, replacing the old recording. A folder must hold one run's spec and build: a new spec with an old build would accept carriers for other requirements. So with `REHEARSE=1`, run Act 1's spec and its whole Build and test live (about $10), or neither. A live Act 2 fix (about $6) refreshes `linden-grove/fix.jsonl` on its own. The stored fix ran on the seed's 26 tests; the seed has 27 since the reminder test (#79), so a fresh fix would include it.
- `make dev STUB=name` (#31) still replays a whole folder for every agent. That is for checking the UI, not for the demo.

## If something goes wrong

| What | Do |
|---|---|
| A step is slow | **Use the rehearsal's result**. |
| "No recording at …" | The agent id is not the one with recordings (`linden-grove-new` or `linden-grove`), or the step has none. Run it live or skip it. |
| Accept refused: "saved after this build started" | The agent was saved during the build. Build again (cached). |
| Fix refused: "Save the draft first" | Save, then **Fix this issue** again. |
| The canvas has no width at 1024 px with the inbox and the right column open | Close one of them (known, not new). |
| A live call misbehaves | It is live: say what happened. Live calls are not recorded, so there is nothing to replay. |
| Anything else | `make demo-reset` takes seconds. What it replaced is in `backend/.demo-archive/`. |
