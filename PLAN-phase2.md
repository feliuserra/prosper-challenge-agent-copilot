# Phase 2 plan: Agent Copilot

Issues in build order, built on top of the Phase 1 editor ([`PLAN.md`](PLAN.md)). Context is in [`docs/handoff.md`](docs/handoff.md), decisions in [`docs/adr/`](docs/adr/README.md) (0008 to 0015 are Phase 2). Each item is a GitHub issue on the fork with the same number. One branch/PR per issue, `Closes #N`. GitHub is the source of truth for status; update this file only when scope changes.

## The brief, in short

- The deployment team spends its time on two manual workflows: (1) turning a client's natural-language guidelines into a working agent, and (2) refining agents from issues that clients flag or that show up in call data. Finding those issues in calls is itself a burden.
- Build an AI Copilot, integrated in the Phase 1 UI, that automates both, the way coding tools automate software work. There is no real call data: mock calls and flagged issues.
- What is valued: originality of the Copilot, how well it solves the two problems, pragmatic scoping (what to build, mock or leave out, and why), product sense (the real bottleneck, not tangential polish), and a live end-to-end demo.
- OpenAI and ElevenLabs keys are provided.

## The idea

Coding tools work because code comes with a spec, tests they can run and bug reports with evidence. Voice agents have none of these, which is why both workflows are manual. The Copilot creates them and then works the loop a coding agent works:

```
client guidelines --> requirements --> agent graph --> tests
        ^                                  ^             |
client tickets                        fix (diff)    run / audit
        |                                  |             v
        +------ issues with evidence <------+------- calls
```

- **Requirements are the spec.** The Copilot turns guidelines into numbered, checkable requirements (each with the sentence it came from) plus questions for the client where the guidelines have gaps, each with the default it uses meanwhile. A healthcare baseline (emergency, no medical advice, identity first, a human on request) is always added.
- **The human reviews tests, not prompts.** Checking 20 one-line tests against the client's guidelines takes minutes; reading every prompt in a graph takes an hour. Tests are approved before the graph exists, and approved tests are locked.
- **The Copilot loops until the tests pass,** then proposes one diff. You accept or reject it like a pull request; accepting is one undo step and a new version.
- **Issues are found for you and pinned to the graph.** Every call is checked against the requirements and common failures; issues carry quotes and the node where they happened, and show as badges through the Phase 1 problems list.
- **Every bad call becomes a regression test.** The test replays the caller's words exactly as speech-to-text heard them, then improvises. It must fail before the fix and pass after it, and it stays in the suite.
- **Fixes are tested, not guessed.** Every failure is traced to its cause ([ADR 0015](docs/adr/0015-debugging-by-cause.md)). For a rule from the guidelines: which link between the client's sentence and the answer broke (never extracted, in the wrong node, overridden by another instruction, a tool not used, or unclear in the guidelines). For a call: which turn decided it. The Copilot tries 2 to 3 candidate fixes by replaying that exact turn with each, checks the best one against every past turn it would change, and only then reruns the suite. What a call would have been with the fix is a forecast and is shown as one: observed up to the turn where the agent first differs, simulated after it.

Simulation testing alone is not new (several companies sell it for voice agents). What is new here is the loop: tests a human approves as the contract with the client, production calls turning into regression tests, and a Copilot that fixes against both by experiment: it finds the turn and the rule behind a failure and replays its candidate fixes on that turn and on past calls before proposing one.

## How we know it works

There is no technical guarantee: an agent written by a model, tested by a model playing the caller and graded by a model can agree with itself and still be wrong. We reduce that risk by checking the checkers, putting humans where review is cheapest, and bringing in evidence from outside the loop ([ADR 0011](docs/adr/0011-trusting-the-tests.md)):

- **Exact checks first.** Tests check tool calls and their arguments, their order, transfers and how the call ended. A fixed tool catalog makes these checks the same for any agent ([ADR 0008](docs/adr/0008-node-tools-from-a-mock-catalog.md)). An LLM judge is used only for soft rules.
- **A reference suite the Copilot never sees.** 20 hand-written tests for a fictional clinic, in `backend/eval/`, outside anything the Copilot can read. The Copilot loops on its own tests; the reference suite measures afterwards.
- **Mutation testing.** Deliberately broken versions of a hand-built reference agent must each fail at least one test, and each test must catch at least one of them.
- **A calibrated judge.** About 30 hand-labelled transcripts; each judged rule needs at least 90% agreement or becomes an exact check.
- **A measured call checker.** The mock production calls come from a deliberately weak agent, so we know which problems each call contains and can measure how many the checker finds and how many of its alarms are wrong.
- **Safety tests block.** Emergency, medical advice, identity and transfer tests must pass at 100% for a change to be offered.
- **Locked tests.** The Copilot cannot edit an approved test to make it pass.
- **No test facts in the agent.** An automatic check that names, dates of birth and phone numbers from tests never appear in an agent, so the Copilot cannot pass by special-casing a caller.
- **A blind second clinic.** Claude writes the reference suite and the Copilot's prompts, so neither is blind to the other. The user writes a second clinic's guidelines and about 6 tests and keeps them out of the repo until the final run in #34: the only check nobody tuned toward.
- **Messy data for the call checker.** The mock production calls mix simulated calls with our real recorded voice calls and hand-roughened ones (hesitations, real speech-to-text garbles from #13), so the checker is not measured only on clean text.
- **Checking the debugging.** The decisive turn must land in the node where a defect was planted; a turn replay must predict the full rerun; forecasts are compared with the true what-if from the mock calls' hidden callers; the line "N past turns affected" is compared with new calls. A fix is chosen on the flagged call and its numbers are reported on the other calls. Sentence ablation is not measured.
- **Effort numbers.** Human edits needed after generation, minutes from guidelines to all tests passing, minutes from issue to accepted fix.
- **Stated limits.** The README says what the tests do not catch (below).

## Decisions

| Topic | Decision | ADR |
| --- | --- | --- |
| Mock tools | Nodes list tools from a fixed catalog over a fake clinic calendar; tools return data and keep the conversation in the node; edges still move it | [0008](docs/adr/0008-node-tools-from-a-mock-catalog.md) |
| Simulated calls | Our own text runner over the agent JSON, same rules as `AgentBuilder`; a model plays the caller | [0009](docs/adr/0009-text-runner-for-simulated-calls.md) |
| Test format | JSON tests with a caller, a starting world, optional replayed turns and checks; exact checks first; safety and core tiers; a failure is rerun once; results cached; models pinned | [0010](docs/adr/0010-test-format-and-grading.md) |
| Trusting the tests | Test-first approval, locked tests, a held-out reference suite, mutation testing, judge calibration, planted issues | [0011](docs/adr/0011-trusting-the-tests.md) |
| Copilot edits | Validated edit operations, for creation too; loop until green (at most 3 rounds); one diff to accept | [0012](docs/adr/0012-copilot-edits-through-operations.md) |
| Concurrent edits | The Copilot works on the draft sent with each request; the canvas is locked while it runs, and a proposal based on an older draft cannot be accepted | [0012](docs/adr/0012-copilot-edits-through-operations.md) |
| Live clinic state | Live calls share one clinic calendar that persists until reset, so "book, then call back to reschedule" works; tests always start from their own world. The agent is told the clinic's date | [0008](docs/adr/0008-node-tools-from-a-mock-catalog.md) |
| Storage | One workspace per agent next to the agent file: guidelines, spec, versions, calls, tickets; the bot records every call | [0013](docs/adr/0013-workspaces-versions-and-calls.md) |
| Copilot service and UI | Backend under `/copilot` on the same runner, OpenAI only, chat with a few tools plus buttons that call the same endpoints, a tabbed right-hand column | [0014](docs/adr/0014-copilot-service-and-ui.md) |
| Cost | Cheap runs: a small model plays the caller, one run per test plus one rerun on failure, cached results. `make test` makes no model calls | [0010](docs/adr/0010-test-format-and-grading.md) |
| Live demo | Everything runs live; any long step can switch to results cached during the rehearsal | [0014](docs/adr/0014-copilot-service-and-ui.md) |
| Debugging by cause | Each failure is traced to the broken link in its rule chain and the turn that decided it; candidate fixes are tested by replaying that turn and past turns before a full rerun; what-ifs are forecasts with an observed part and a simulated part | [0015](docs/adr/0015-debugging-by-cause.md) |
| Flight recorder | Call records and test results keep, per agent turn, the node and the exact messages, functions and tool results the model was given | [0013](docs/adr/0013-workspaces-versions-and-calls.md), [0015](docs/adr/0015-debugging-by-cause.md) |
| Requirement map | Copilot operations cite requirement ids; nodes and the agent carry an optional `requirements` list that the runtime ignores | [0012](docs/adr/0012-copilot-edits-through-operations.md), [0015](docs/adr/0015-debugging-by-cause.md) |

## Time and cuts

About one week plus two days for the debugging tools (ADR 0015), so about two PRs a day to review. If we fall behind, cut in this order: sentence ablation, the win-probability chart, the canvas overlay of affected turns, the second clinic (if there is no time to write it), grouping issues across calls, any UI for versions, the client-question cards (plain text in the chat instead). Never cut mutation testing, the held-out reference suite or locked tests: those decide whether "20/20" means anything. Never cut the flight recorder, turn replay or the requirement map either: finding causes rests on them.

## Prerequisites (user)

- [ ] Review the demo clinic's guidelines and the 20 reference tests (#27).
- [ ] Review the judge labels: about 30, drafted with a reason each, about 45 minutes (#27).
- [ ] Add Prosper or industry practice to the authoring guide when reviewing #29.
- [ ] Write clinic B (guidelines and about 6 tests in the same format as #27) and keep it out of the repo until the final run in #34.
- [ ] Real calls for #25 (tools, turn timing), #33 (the fix) and the rehearsal in #34.

## Checklist

- [ ] [#25](https://github.com/feliuserra/prosper-challenge-agent-copilot/issues/25) Mock tools and turn timing
- [ ] [#26](https://github.com/feliuserra/prosper-challenge-agent-copilot/issues/26) Text runner and test format
- [ ] [#27](https://github.com/feliuserra/prosper-challenge-agent-copilot/issues/27) Demo clinic, reference suite and `make eval`
- [ ] [#28](https://github.com/feliuserra/prosper-challenge-agent-copilot/issues/28) Workspaces, versions and recorded calls
- [ ] [#29](https://github.com/feliuserra/prosper-challenge-agent-copilot/issues/29) Copilot service: edit operations and the spec step
- [ ] [#30](https://github.com/feliuserra/prosper-challenge-agent-copilot/issues/30) Copilot builds the agent and loops until green
- [ ] [#31](https://github.com/feliuserra/prosper-challenge-agent-copilot/issues/31) Copilot UI
- [ ] [#32](https://github.com/feliuserra/prosper-challenge-agent-copilot/issues/32) Calls inbox and audit
- [ ] [#33](https://github.com/feliuserra/prosper-challenge-agent-copilot/issues/33) Fix from an issue
- [ ] [#35](https://github.com/feliuserra/prosper-challenge-agent-copilot/issues/35) Turn inspector and causal views
- [ ] [#34](https://github.com/feliuserra/prosper-challenge-agent-copilot/issues/34) Demo readiness

Then [#11](https://github.com/feliuserra/prosper-challenge-agent-copilot/issues/11): README for both phases and the demo video.

---

## 25. Mock tools and turn timing

**Goal:** agents can look things up and act (find a patient, list open slots, book), so they behave like a real scheduler and tests can check exactly what they did.

**Depends on:** #13 merged (both change the example agent).

**Scope:**
- `backend/clinic/`: a fake clinic world (providers, patients, appointments, open slots) loaded from a seed JSON. Deterministic: a fixed "today" in the seed, no clock, no randomness.
- Live calls share one clinic state that persists across calls (`backend/clinic/state.json`, gitignored, created from the seed when missing; deleting it restores the seed, later `make demo-reset`), so a booking made in one call can be rescheduled in the next. Tests always start from their own fresh world (#26).
- The agent is told the clinic's date and weekday: the bot (and later the runner) adds one line with it to the system message, so "next Tuesday" means something.
- Strict formats in tool parameters and results (ISO dates and times, slot and appointment ids), so tests can compare values exactly; the model converts what the caller says.
- Tool catalog ([ADR 0008](docs/adr/0008-node-tools-from-a-mock-catalog.md)): `lookup_patient`, `register_patient`, `find_slots`, `book_appointment`, `reschedule_appointment`, `cancel_appointment`, `transfer_to_human`. Each has a description and a parameter schema the model sees. Policies (such as a cancellation fee) stay in the agent's prompts, not in the tools.
- Schema: optional `tools: [name]` on nodes. Validation: unknown tool, duplicate tool, a tool with the same name as an edge function in that node; each error tied to its node. zod mirror.
- Builder: each tool becomes a Flows function whose handler returns `(result, None)`, so the conversation stays in the node (`pipecat_flows/manager.py:480-501`). Logged like transitions and sent to the UI as an RTVI server message `{type: "tool_call", node, tool, args, result}`. `transfer_to_human` ends the call after the bot says it is transferring.
- `GET /composer/tools`: the catalog for the editor.
- Editor: tool checkboxes in the node panel; tool-call rows in the call transcript, like transition rows.
- Example agent: uses `lookup_patient`, `find_slots` and `book_appointment` instead of the two hard-coded times.
- Turn timing: short answers ("Book.") wait for the 3 s silence fallback today (handoff section 5). Tune the turn-end settings in `bot.py` and check by call.

**Acceptance criteria:**
- In a call, the bot can call a node's tools mid-node, the conversation stays in that node, and the call panel shows each tool call with its arguments and result.
- Validation reports unknown tools and name clashes on the right node.
- pytest for each tool on the seed world: patient found and not found, slot taken, unknown appointment, cancel and reschedule; and for the live state (persists, reset restores the seed).
- In a real call (user), a one-word answer gets a reply in about a second, and the example agent books a slot that came from `find_slots`.

## 26. Text runner and test format

**Goal:** run an agent against a simulated caller in text and grade the result, cheaply and repeatably. Everything else in Phase 2 rests on this.

**Depends on:** #25.

**Scope:**
- `backend/sim/` ([ADR 0009](docs/adr/0009-text-runner-for-simulated-calls.md)): interprets the agent JSON with the same rules as `AgentBuilder`: role and task messages per node, edges as functions that move to their target, tools that stay in the node, end nodes end the call, `tts_say` actions as bot lines. Uses the tool code from #25 and a fresh world per test.
- Caller: a model playing the patient from the test's persona, goal, facts and style. The call stops at an end node, a transfer, the caller hanging up, or `max_turns`.
- Anchored replay: a test can carry `replay`, the caller's turns from a real call as speech-to-text heard them, each with the question it answered. When the agent asks for the same thing, the caller says the recorded words exactly, garbles included ("Sara Boreal"); when the agent goes somewhere else (as it will after a fix), the caller improvises. Spelled letters are assumed to be heard correctly, a known limit.
- Test format ([ADR 0010](docs/adr/0010-test-format-and-grading.md)): `id`, `title`, `tier` (`safety` or `core`), `requirements`, `caller`, `world`, `replay`, `max_turns`, `checks`.
- Checks: `tool_called` (arguments matched loosely: case, spaces and punctuation ignored for names), `tool_not_called`, `tool_order`, `call_ended`, `transferred`, `max_turns`, and `judge` (one plain-language rule per check, graded on the transcript plus tool calls and their results, never the agent's prompts, so it can tell invented availability from real). No checks on node or function names, so a test works on any agent that uses the catalog.
- Results: pass or fail per check with evidence (turn number and quote), plus the transcript, tool calls and transitions. A failing test is rerun once; if the rerun passes it is marked flaky.
- Per-turn context ([ADR 0015](docs/adr/0015-debugging-by-cause.md)): results keep, for each agent turn, the node and the exact messages and functions the model was given, plus the tool results.
- `replay_turn(record, turn, agent, k=5)`: rebuild the context at that turn from a call record or a test result, swap in another agent, sample the agent's action k times at its live temperature, and grade it with a turn check (an expected action, or one judge rule on the reply) as a rate. No simulated caller.
- `continue_from(record, turn, agent, caller, k)`: continue a recorded call from a turn, reusing the recorded words while the agent asks the same things and simulating the caller after the first divergence. Reports the divergence turn and each run's outcome. Used for backcasts, what-if forecasts and rollouts (#32, #33, #35).
- Results cached by a hash of agent, test, models and runner version; `--no-cache` for honest numbers.
- Rate limits and API failures: retries with backoff and a limit on parallel calls; a test that could not run is reported as `error`, never as a failure of the agent.
- Before pinning models, list the models and rate limits the company key actually has, and record them.
- Models pinned in one config file. The agent runs with its own model and the same parameters as `bot.py`; the caller uses a small model; the judge model is chosen in #27.
- CLI: `uv run python -m sim run <agent.json> <tests.json>` prints a pass/fail table.
- Unit tests with a scripted fake model; `make test` makes no network calls.

**Acceptance criteria:**
- The runner offers the same functions per node as `AgentBuilder` on the example agent and on the fixture agent (a test compares them).
- Every check type has a passing and a failing unit test, and rerun and cache have tests.
- `replay_turn` with the same agent rebuilds exactly the messages recorded for that turn, and `continue_from` repeats the recorded caller words up to the divergence turn (unit tests with a scripted model).
- A real run of 3 hand-written tests against the example agent finishes in under a minute; time and cost are recorded in the PR.

## 27. Demo clinic, reference suite and `make eval`

**Goal:** a fixed, trusted measure: hand-written tests that a good agent passes and broken agents fail. It is the acceptance gate for the Copilot.

**Depends on:** #26.

**Scope:**
- `backend/eval/clinic-a/`:
  - `guidelines.md`: a fictional clinic, written like a real client document (3 providers, booking, rescheduling, a 24 h cancellation fee, new-patient rules, an insurance answer), slightly messy, with a few gaps on purpose (minors, double booking, what to do when nothing fits).
  - `world.json`: the seed for the tools.
  - `reference-agent.json`: built by hand in the editor, using the catalog.
  - `tests.json`: the 20 reference tests. About 5 safety tests (emergency, medical advice, identity before booking or sharing appointment details, a human on request) and about 15 core tests (book, new patient, reschedule, cancel inside and outside 24 h, nothing available, a misheard name corrected by spelling, a caller who changes their mind, an off-topic question, provider preference, an insurance question, a time outside opening hours). Personas vary on purpose: terse, elderly, non-native speaker, angry, rambling.
- Mutants: `backend/eval/mutants.py`, about 8 functions that each break the reference agent in one known way (remove the identity check, book without confirming, drop the emergency instruction, skip the fee warning, never transfer, ignore the new-patient rule, invent availability instead of calling `find_slots`, ...).
- Judge calibration: about 30 transcripts from real runs, passing and failing on the soft rules, labelled by hand (drafted by Claude, reviewed by the user) in `backend/eval/judge-labels.json`. Measure agreement per rule; pick the judge model; a rule under 90% is rewritten or turned into an exact check.
- `make eval`: runs the reference suite against an agent (default: the reference agent; `AGENT=...` for another) and prints a table and a summary. `make eval MUTANTS=1` runs it against every mutant. Results go to `backend/eval/results/` (gitignored). Not part of `make test`.

**Acceptance criteria:**
- The reference agent passes 20/20. Flaky results are allowed only in the core tier and are listed in the PR.
- Every mutant fails at least one test, and every test fails on at least one mutant, or the PR says why not.
- Judge agreement is at least 90% for every judged rule in the suite.
- The user has reviewed the guidelines and the tests.
- Time and cost of one `make eval` run are recorded.

## 28. Workspaces, versions and recorded calls

**Goal:** everything the Copilot works from lives next to the agent: guidelines, requirements, tests, versions, calls and tickets.

**Depends on:** #25 (#26 for the comparison with the runner).

**Scope:**
- `backend/workspaces/<agent-id>/` ([ADR 0013](docs/adr/0013-workspaces-versions-and-calls.md)): `guidelines.md`, `spec.json` (requirements, client questions, tests with a `draft` or `approved` state), `chat.json` (the Copilot conversation), `versions/`, `calls/`, `tickets/`. The agent file stays at `backend/agents/<id>.json`, so the Phase 1 API is unchanged and a workspace is optional.
- Versions: a snapshot on each save from the editor and each accepted Copilot change, with its source and a message. Saving an unchanged agent adds no version.
- Call records: the bot writes one when the call ends: a copy of the agent that ran and its hash (and the version, if it matches a saved one), the transcript (user turns as speech-to-text heard them, bot turns), transitions, tool calls with results, start and end times and how it ended. For each agent turn, the node and the exact messages and functions the model was given (the flight recorder, [ADR 0015](docs/adr/0015-debugging-by-cause.md)), taken from the bot's LLM context. Simulated and mock production calls use the same format, with a `source` field.
- API under `/copilot/workspaces/{id}/...`: guidelines (get, put), versions (list, get), calls (list, get), tickets (list).
- `backend/workspaces/` is gitignored; seed data for the demo lives elsewhere (#32). Decide the open item about agents saved from the editor landing untracked in `backend/agents/` (handoff section 5).

**Acceptance criteria:**
- A test call from the editor produces a call record with the draft that ran, the user's words as speech-to-text heard them, and every transition and tool call.
- Saving twice without changes creates one version.
- On a live test call, the per-turn messages the bot recorded match what the runner rebuilds from the same agent and history, or the PR lists the differences.
- pytest for the store: atomic writes, ids sanitised like agent ids, a missing workspace handled.

## 29. Copilot service: edit operations and the spec step

**Goal:** the Copilot backend can change agents safely and turns guidelines into the spec a human reviews: requirements, client questions and tests.

**Depends on:** #26, #28.

**Scope:**
- `backend/copilot/ops.py` ([ADR 0012](docs/adr/0012-copilot-edits-through-operations.md)): `add_node`, `update_node`, `rename_node` (cascades), `delete_node` (cascades), `add_edge`, `update_edge`, `delete_edge`, `set_initial_node`, `set_tools`, `update_agent`, with the editor store's rules. Shared cases in `backend/tests/fixtures/ops/` (operations in, expected agent out) run by both pytest and Vitest so the two implementations cannot drift.
- Requirement map ([ADR 0015](docs/adr/0015-debugging-by-cause.md)): operations that add or change prompts, edges or tools cite the requirement ids they serve, kept in an optional `requirements` list on nodes and on the agent (for the persona). The runtime ignores it; schema, dataclasses and zod mirror. A function lists the requirements no node carries and the requirements no test checks.
- Operations are applied to a copy and validated with `validate_agent`; errors go back to the model for at most 2 more tries; an agent with errors is never written.
- Service under `/copilot` on the runner ([ADR 0014](docs/adr/0014-copilot-service-and-ui.md)), progress streamed to the browser (server-sent events). OpenAI client, pinned models, prompts in their own files. Each request carries the editor's current draft, as test calls do, so the Copilot works on what the user sees, saved or not.
- Authoring guide (`backend/copilot/prompts/authoring-guide.md`): what makes a good voice agent graph, drafted by Claude from general practice and Phase 1 (short spoken replies, one question at a time, confirm critical details such as #13's spell-and-confirm, how to write edge descriptions, when to use tools, clean endings). The user adds Prosper or industry practice in review. The Copilot's prompts include it; humans can read it too.
- The conversation is saved in the workspace (`chat.json`), so a reload keeps it.
- Spec step: guidelines plus the healthcare baseline produce requirements (id, text, the sentence it came from), client questions (question, default used meanwhile) and tests (format from #26, linked to requirements, with a tier). Tests are generated from the requirements only, never from a graph. Stored as drafts in the workspace.
- Chat loop with a small toolset: read the workspace, propose or edit the spec ("drop R7", "add a test for a minor"), and later build, run tests, audit and fix. Transcripts and tickets are passed as delimited data, never as instructions.
- The Copilot's tools can read only its workspace; nothing reaches `backend/eval/`.

**Acceptance criteria:**
- From clinic-a's guidelines, the requirements cover every rule in the guidelines (checked against a list in the PR), every requirement has at least one test, and the baseline requirements are always there.
- The gaps put in the guidelines on purpose come back as client questions.
- The shared operation cases pass in pytest and Vitest; an invalid sequence of operations is repaired or reported, never written.
- Renames and deletes carry a node's requirement list (shared cases).
- A test shows that no Copilot tool can read `backend/eval/`.

## 30. Copilot builds the agent and loops until green

**Goal:** from approved tests, the Copilot builds the graph with operations and fixes it until its tests pass. This is the "initial implementation" workflow.

**Depends on:** #27, #29.

**Scope:**
- Build: approved spec, then an outline (nodes, tools per node, edges), then operations, streamed so the UI can show the graph growing. Every operation cites the requirements it serves; at the end every requirement is carried by a node or the persona, or the proposal says why.
- Diagnosis ([ADR 0015](docs/adr/0015-debugging-by-cause.md)): for each failing check, the broken link in the rule chain. Wrong place and data-or-tool are decided exactly, from the failing turn's recorded context and the requirement map; overridden and unclear guideline by the model. A failure diagnosed as an unclear guideline becomes a client question, not a fix.
- Loop: run the workspace tests; for each failure the model proposes 2 to 3 candidate changes aimed at the broken link; each is checked with `replay_turn` on the failing turn (k = 5); the best is applied and the failing tests are rerun, then all of them. At most 3 rounds, counting full reruns; stop as soon as everything passes. The result is a proposal: operations, the new agent, the diagnosis per failure, a short rationale, and test results before and after.
- For each candidate that went on to a full rerun, keep its turn rate and the rerun's result, for the agreement number in #34.
- Locked tests: the Copilot cannot change an approved test. If it thinks a test is wrong, it says so in the proposal and the user decides.
- Safety tier: a proposal with a failing safety test is marked blocked and cannot be accepted.
- Leak check: a proposal whose agent contains facts from any test (caller names, dates of birth, phone numbers) is blocked, so the Copilot cannot pass by special-casing a caller.
- `make eval COPILOT=1`: runs the spec step and the build on clinic-a's guidelines, approves the generated tests automatically (standing in for the human), then runs the held-out reference suite on the result. Records pass rate, rounds, time and cost.

**Acceptance criteria:**
- On clinic-a, the generated agent passes at least 18 of the 20 reference tests (target 20/20), including every safety test. If not, the PR reports what failed and why.
- A test shows that no reference test id or text appears in any prompt or tool result the Copilot receives.
- A test the Copilot cannot make pass ends as a blocked proposal with an explanation, never as an edited test.
- The leak check blocks a proposal that names a test caller (unit test).
- Every failure in a proposal names its broken link; the exact diagnoses (wrong place, data or tool) have unit tests on fixtures.

## 31. Copilot UI

**Goal:** the Copilot inside the editor: a chat with cards, the graph building live, diff review and the tests.

**Depends on:** #29 (#30 for the build cards).

**Scope:**
- A right-hand column with tabs: Copilot, Tests, Calls (filled in #32) and Test call (the #7 panel, unchanged). It takes the call panel's place instead of adding a fourth column.
- Copilot tab: the chat; replies render as cards: requirements (with their source sentence), client questions (with "copy for the client"), the test list (edit, delete, approve), build progress, proposals (diff summary, the diagnosis per failure, test results, the line "N past turns affected" from #33, Accept and Reject) and issues (#32). Buttons such as "Create from guidelines", "Run tests", "Audit calls" and "Fix" call the same endpoints directly, so the demo never depends on the model choosing a tool.
- Guidelines: a text area in the workspace to paste the client's document.
- Requirement map: clicking a requirement outlines the nodes that carry it; the node panel shows a node's requirements as read-only chips; requirements with no node or no test appear in the problems list as warnings.
- Canvas: while the Copilot builds, its operations appear live; a proposal shows as a diff overlay (added, changed, removed nodes and edges). Accept applies it through a new store operation as one undo step and saves a version; Reject leaves the agent as it was.
- While the Copilot is building or fixing, the canvas and side panel are read-only, with a "Copilot is working" banner and a Stop button. Accept is refused if the draft changed since the proposal started (for example after a Stop).
- The chat is restored from the workspace after a reload.
- Tests tab: each test with tier, requirements and last result; run all or one; open a result to read the transcript with the failing checks marked and replay its path on the canvas with the #8 highlighting.

**Acceptance criteria:**
- Paste clinic-a's guidelines, review the spec cards, approve the tests, watch the graph build, accept, run the tests: all in the UI, without the terminal.
- One Cmd+Z undoes an accepted proposal; Reject changes nothing; a proposal based on an older draft cannot be accepted.
- Clicking a requirement outlines its nodes; a requirement no node carries shows in the problems list.
- Checked in the browser pane against a stubbed Copilot backend, and once for real by the user.

## 32. Calls inbox and audit

**Goal:** find problems in calls without anyone listening to them. This is the "detection" half of production iteration.

**Depends on:** #26, #28, #31.

**Scope:**
- Mock production data, in a demo seed (`backend/demo/`):
  - a deliberately weak first version of the clinic-a agent, with its defects listed in a label file;
  - about 15 calls: most produced by the runner against it with varied personas, plus our real recorded voice calls and a few roughened by hand (hesitations, cut-off sentences, real speech-to-text garbles from #13 such as "Sara Boreal" and a name in Chinese characters), saved as `source: production-mock`. Calls made by the runner keep their hidden caller (persona, goal, facts, style) in the label file, which the checker cannot read;
  - 3 client tickets written as a clinic would write them ("Mrs. Lopez says she was booked under someone else's name").
- Audit: each call is checked against the workspace requirements and a general checklist (loops, repeated questions, an ignored transfer request, invented availability, no clean ending, a frustrated caller). Each issue has a severity, the requirement, the node (from transitions) and quotes. Tickets are matched to calls where possible.
- Cause ([ADR 0015](docs/adr/0015-debugging-by-cause.md)): each issue gets its broken link (the #30 diagnosis) and a decisive turn. The audit judge names the turn and is run twice; if the two runs disagree, rollouts with `continue_from` (k = 3, bisecting over turns) find where the chance of success drops.
- Caller card for each flagged call: persona, goal, facts and style inferred from the transcript, and the recorded words with the question each answered. Stored with the issue; #33 reproduces and forecasts from it.
- Grouping (stretch): issues with the same requirement and node across calls become one issue with a count.
- Calls tab: the list (date, outcome, number of issues); a call's transcript with issues marked; its path replayed on the canvas. Issues also appear in the problems list and as badges on nodes, as a third kind next to errors and warnings.
- Audit results cached per call and agent version.
- The checker is measured against the planted defects: how many it finds and how many false alarms it raises, reported in the PR. Also: how often the decisive turn falls in the planted defect's node, and how the caller cards compare with the hidden callers.

**Acceptance criteria:**
- On the seed data the checker finds at least 80% of the planted issues with at most one false alarm per 5 calls. The exact numbers are reported either way.
- Clicking an issue opens the call at the quoted turn and outlines the node.
- The decisive turn falls in the planted defect's node for at least 80% of the planted issues found. The exact number is reported either way.

## 33. Fix from an issue

**Goal:** the production iteration loop end to end: issue, reproduction, fix, regression.

**Depends on:** #30, #32.

**Scope:**
- Reproduce first, as a backcast ([ADR 0015](docs/adr/0015-debugging-by-cause.md)): from the issue's caller card (#32), run the current agent with `continue_from` from the start, k = 5 times. The recorded words, as speech-to-text heard them, are reused whenever the agent asks the same thing, and the caller improvises otherwise. The share of runs that fail is the base rate a fix must beat; if none fails, report that the issue does not reproduce and stop. The reproduction test is built the same way (anchored replay, checks from the broken requirement).
- Fix funnel: 2 to 3 candidate changes aimed at the broken link; `replay_turn` on the decisive turn for each (k = 5). If no candidate changes the outcome, rollouts look for an earlier decisive turn. The best candidate is replayed on every past turn that ran in a changed node; the winner goes through the #30 loop with the reproduction test plus the full suite.
- What-if forecast on the flagged call: observed up to the turn where the fixed agent first differs, then k = 5 continuations from the caller card ("same as the real call up to turn 4; after that, 4 of 5 succeed").
- The proposal shows the reproduction going from fail to pass, the suite results, the what-if, and one line: "14 past turns affected: 2 fixed, 11 same, 1 changed". The candidate is chosen on the flagged call; the line counts only the other calls.
- Measured: on runner-made calls, the forecast against the true what-if (the hidden caller run against the fixed agent); turn rates against full reruns; after an accept, a few new simulated calls through the changed nodes against the past-call line.
- Accept: a new version, the reproduction test added to the workspace suite (approved by the accept), and the issue marked as fixed in that version.
- Tickets without a call ("patients want the earliest slot offered first") become a new or changed requirement, then a spec card, tests and a fix.

**Acceptance criteria:**
- For the wrong-name issue in the seed data: the backcast fails on the weak version (rate reported); the decisive turn is the name capture, not the booking; the fix passes the turn replay; the reproduction passes after the fix, the full suite still passes, and a live call by the user confirms it.
- The proposal shows the what-if and the past-call line; forecast calibration and the agreement of turn replays with full reruns are reported, whatever they are.
- The reproduction test is in the suite afterwards and passes on later runs.

## 35. Turn inspector and causal views

**Goal:** see why the agent did what it did: what it saw on a turn, which sentences it relied on, where a call was lost, and which past turns a change would touch. Built last; the first to cut.

**Depends on:** #31, #32, #33.

**Scope:**
- Turn inspector (Calls and Tests tabs): click an agent turn to see the node, the system message, the functions offered, the history and the tool results the model was given (the flight recorder from #26 and #28), the requirements the node carries, and the diagnosis if this is an issue's decisive turn.
- Canvas overlay: with a proposal open, nodes tinted by how many past turns the change affects, with fixed, same and changed counts from #33; clicking a node lists those turns.
- Win-probability chart, on demand for a flagged call and cached for the demo ([ADR 0015](docs/adr/0015-debugging-by-cause.md)): after each turn, the chance the call still ends well, estimated with `continue_from` (k = 3) and the call's caller card. The biggest drop is marked and compared with the judge's decisive turn.
- Sentence ablation, on demand from the inspector ("Why did it do this?"): remove each sentence of the node's messages in turn, `replay_turn` (k = 3), and highlight the sentences whose removal changes the action. Not measured; the README says so.
- Cut order inside this issue: ablation first, then the chart, then the overlay. The inspector stays.

**Acceptance criteria:**
- The inspector shows exactly what was recorded for the turn (checked against the call record).
- On the wrong-name call, the chart's biggest drop is at the name capture turn, or the PR explains why not.
- Time and cost of one chart and one ablation are recorded.
- Checked in the browser pane against stubbed data, and once for real by the user.

## 34. Demo readiness

**Goal:** a reliable live demo and honest numbers.

**Depends on:** all of the above.

**Scope:**
- `make demo-reset`: restores the demo workspace (guidelines, the weak agent, mock calls and tickets) and clears caches.
- `docs/demo.md`: the demo script. Act 1: guidelines, spec, approve tests, build, tests pass, live call. Act 2: calls inbox, audit, issues on the graph with their decisive turn, reproduce, candidate fixes replayed on that turn, the what-if and the past-call line, fix, tests pass, live call. The inspector, chart and ablation from #35 if they were built. Everything runs live, but every long step (spec, build, test runs, audit, fix) can switch to the results cached during the rehearsal, so a slow model call never stalls the demo.
- Two full rehearsals; fix what breaks.
- Update `docs/notes/call-tests.md` for tools and the new example agent.
- Numbers in `docs/notes/results.md`: reference pass rate, mutants caught, judge agreement, checker recall and false alarms, blame accuracy, turn replays against full reruns, forecast calibration, the past-call line against new calls, time and cost per run, human edits needed after generation, minutes from guidelines to green and from issue to accepted fix.
- Drafts for #11's README: "How we know it works", "What the tests don't catch" and "What a what-if can't tell you".
- Clinic B: the user's held-out clinic (guidelines and about 6 tests), added to `backend/eval/clinic-b/` only now and run once with `make eval COPILOT=1`, to see whether the Copilot generalises. No prompt changes after seeing it; the result is reported as it is.

**Acceptance criteria:**
- From `make demo-reset`, both acts run end to end twice in a row with no manual fixes.
- The numbers are recorded, including clinic B's.

---

## Out of scope (state in the README)

Telephony, voice in simulated calls, analytics dashboards, changes going live without review, a canary or staged rollout, branching or rollback UI for versions, auth and multiple users, PHI redaction and a BAA with the model provider, languages other than English.

## What the tests don't catch (state in the README)

A what-if is a forecast, never a fact: after the turn where a fixed agent first differs from a real call, the caller is simulated from a caller card. Text tests do not see latency, interruptions and turn-taking, audio quality, how the voice reads letters and numbers out loud, or speech-to-text errors other than the ones replayed from real calls. In production the final judge is real calls: completed bookings, transfers, hang-ups, a canary before full rollout and a rollback.
