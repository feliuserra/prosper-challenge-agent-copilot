# Handoff: Prosper challenge (Agent Composer), Phase 1 UI

Context for a new session. Read it fully before writing code. The build plan is in [`PLAN.md`](../PLAN.md) for Phase 1 and [`PLAN-phase2.md`](../PLAN-phase2.md) for Phase 2 (the Agent Copilot, issues #25 to #35, #38, #39 and #43), the design decisions are in [`docs/adr/`](adr/README.md), and what the Pipecat runtime actually does (with file:line references into the installed packages) is in [`docs/notes/runtime.md`](notes/runtime.md). This file holds the context those do not.

Working style: the user (Feliu) is a strong Python developer and wants direct answers with explicit reasoning and trade-offs. Explain why each decision is made. Avoid overengineering. In documents written for the repo, keep a plain voice and avoid em-dashes.

---

## 0. Status (updated 2026-10-14, #26 merged; clinic configuration planned after the interviewer's answers)

| Issue | State | PR |
| --- | --- | --- |
| #1 Runtime spike | Merged | #14 |
| (Intel Mac dependency pins) | Merged | #15 |
| #2 Agents API + draft handover | Merged | #16 |
| #3 Frontend skeleton, schema, store | Merged | #17 |
| #4 Graph canvas | Merged | #18 |
| #5 Side panel editors | Merged | #19 |
| #6 Validation errors | Merged | #20 |
| #7 Test call panel | Merged | #21 |
| #8 Live transition events | Merged | #22 |
| #9 Authoring warnings | Merged | #23 |
| #10 Editor polish | Merged | #24 |
| Phase 2 plan | Merged: [`PLAN-phase2.md`](../PLAN-phase2.md), ADRs 0008 to 0015, issues #25 to #35 on GitHub | #36 |
| #13 Reliable caller identity | Merged; the user's test calls passed | #37 |
| #25 Mock tools and turn timing | Merged; the user's test calls passed | #41 |
| Client intake plan | Merged: #38 (checklist) and #39 (intake call) added to `PLAN-phase2.md` | #40 |
| #26 Text runner and test format | Merged; the user's runs passed, and a broken agent failed as expected | #42 |
| Clinic configuration plan | **In review.** #43 created, ADR 0016, `PLAN-phase2.md`; #27, #29, #30, #31, #38 and #39 updated on GitHub | #44 |
| #43, #27 to #35, #38, #39 | Open, in the order of `PLAN-phase2.md`: #43 before #27, #38 right after #29, #39 after #33 | |
| #11 | Open, moved to the end, after Phase 2 (see section 6) | |

**Next step:** merge #44 (docs) when the user says so. Then #43 (clinic configuration) before #27: clinic-a's guidelines, world, reference agent and tests are written against #43's catalog. `issue-27-reference-suite` (local, not pushed) holds only a handoff commit, which #44 contains, so it can be deleted once #44 is merged; start #43 on `issue-43-clinic-config` from `main`. A separate session is brainstorming how to find problems in calls at scale (workflow 2) before #32 is rewritten: see "Interviewer's answers" below. #11 comes last.

When #27 starts (after #43), for that session:
- The issue body changed on 2026-10-14: the guidelines must describe appointment types and which provider does each, which plans cover which visits and the data needed to register a patient; `world.json` carries clinic-a's configuration in #43's format; the reference agent is built from the scheduling template; tests and mutants cover configuration rules.
- Read the issue body first (`gh issue view 27 --repo feliuserra/prosper-challenge-agent-copilot`): it now includes the spend log (cached tokens priced at the cached rate, `backend/.spend/ledger.jsonl` written by `sim/llm.py`, `make spend`).
- Suggested order, offered to the user at the end of the last session: draft `backend/eval/clinic-a/guidelines.md` and a one-line list of the 20 tests (tier, persona, what it checks) for the user to review before writing any test JSON or the reference agent. The user's review of the guidelines, the tests and about 30 judge labels (about 45 minutes) is a prerequisite in `PLAN-phase2.md`.
- Build on #26: the test format is `backend/sim/testfile.py` (with `validate_tests`), examples in `backend/sim/examples/scheduler-tests.json`; `run_suite`, `blocking` and the CLI's table are reusable for `make eval`. Mutants are agent dicts, so `run_suite(mutant, tests, models)` per mutant; the cache keeps reruns free.
- Cost to expect at list prices: about $0.06 to $0.08 per booking-length test, so one uncached run of 20 tests is about $1.20 to $1.60 plus reruns of failures, and one pass over 8 mutants about $10. Prefer cached runs and the cheap probes below while iterating; use `--no-cache` for numbers that go in the PR.
- Judge calibration: label transcripts from real runs (the CLI's `--out` writes them). To compare judge models, call `judge_rule` directly on the labelled turns, as the caller probe did in #26, instead of rerunning calls.
- Leftover from the user's broken-agent check: `backend/agents/broken-transfer.json` (untracked). The user was told to delete it; check before committing anything in `backend/agents/`.

Spend log, for reference (decided 2026-10-13): the company keys cannot read spend (OpenAI: missing `api.usage.read`; ElevenLabs: no `user_read`, and its character stats cover the whole account since 2026-09-12, not just us), so only Prosper's dashboards show billed amounts. Added to #27 (cached tokens, a ledger written by the model client, `make spend`) and #28 (usage per call record, one ledger line per call), in the issue bodies and `PLAN-phase2.md`. Spend before the ledger is not covered; #26 spent about $1.01.

Interviewer's answers, for reference (received 2026-10-14; the user asked three questions by email):
- Answers: (1) most deployment time goes to turning rules into an agent and checking it; getting the rules depends on how responsive the client is. (2) Agents start from a template per use case and are always customized; two scheduling agents for small clinics are quite similar; what changes is which providers do which appointment types, which types exist, which insurance covers which visits, the data needed to register a patient or book, and the flow and tone. A hospital could be a client; for the challenge, assume few clinic types. (3) One person runs fewer than 10 agents, but an agent can take 50,000 calls a month. How to find problems is left to us as part of the challenge.
- (1) keeps the test-first build loop as the headline of act 1. #39 moved to the first thing to cut; the idea of intake sessions with 3 or 4 people playing clinic managers was dropped.
- (2) produced #43 and ADR 0016: rules that are tables or numbers live in a validated clinic configuration that the tools enforce (3 new tools, `appointment_type` on `find_slots` and `book_appointment`, `fee_acknowledged`, fields per clinic, schemas built per clinic), agents name their clinic, and the example agent becomes the scheduling template. #29 extracts the configuration, #30 customizes the template; #27, #31 and #38 follow. Candidate extra actions (waitlist, leave a message, confirmations) are listed in #43 to iterate on.
- (3) makes workflow 2 triage at scale: nobody can listen, and the limit is attention more than model cost. Ideas so far, none decided: a per-node funnel on the graph from transitions, with no model calls; the same template node compared across clinics; issues grouped with a rate and a trend per version (an alarm when a rate rises after an accepted change); three tiers (deterministic signals on every call, a small model on flagged calls plus a random sample, grouping and ranking by severity, frequency and trend); mock data in the hundreds of calls with defects planted at known rates. Brainstormed in a separate session; #32 (maybe #33) is rewritten after it.

Client intake, for reference (decided 2026-10-12, from a brainstorm with the user):
- The idea: for workflow 1 the input sets the ceiling. The model writes prompts well but cannot invent a clinic's policy, and the slow part of an initial build is probably the round trips with the client, not writing the graph (a hypothesis; we do not know what Prosper asks clients today).
- #38: a checklist of 29 client decisions (stable ids, an optional scenario, a safe default each) in `backend/copilot/intake-checklist.json`. The spec step reports coverage per item: answered, defaulted (an `assumed` requirement plus a client question; vague answers count as defaulted) or not applicable. The checklist is a floor, not a ceiling. It asks only what only the client knows: conversation design is the authoring guide's, calendar data the clinic system's. The first draft of the items and defaults is in the issue body; the user reviews it. It improves through PRs: a failure diagnosed as "unclear in the guidelines" adds the item that would have caught it.
- #39: a voice agent generated from the checklist (no model call, so it never drifts from it) interviews the clinic manager on the existing bot; its transcript goes into the agent's workspace as `source: intake` and feeds the spec step; gaps left become a short follow-up call. Measured with a simulated manager (#26 runner) who knows the answers the guidelines leave out, which is partly by construction and must be said. Cuttable.
- Dropped: uploading a recorded kickoff call. The intake call replaces it.
- Pointers to #38 and #39 were added to the bodies of issues #29, #31, #34 and #38, matching `PLAN-phase2.md`. The first `gh issue edit` was blocked by the permission classifier ("External System Writes"); it went through once the user allowed it.

What #26 built, for reference:
- `backend/sim/` (ADR 0009, 0010, 0015). `conversation.py`: one call, agent side. Node configs and handlers come from `AgentBuilder` itself (new public `build_node(name)`, `build_transfer_node(from_node)`), so a node offers what the bot offers. Flows' context rules are mirrored with file:line references in the header: the role message becomes the system message (an empty one keeps the last), task messages are appended (APPEND), tools replaced per node; calls go into the history as Pipecat writes Flows functions (async tools): assistant `tool_calls`, a "started" tool message, the result as a developer message (built with Pipecat's own `async_tool_messages`); unknown functions get Pipecat's "not currently available" tool message; calls with non-JSON arguments are dropped; post-actions run after the node's first reply. Not modelled: interruptions, timing, and the order of words and calls when one reply has both (words first here; #28 compares with a live call).
- Turns: numbered from 1, agent turns are one model call each (`node`, `text`, `calls` with `kind` edge/tool/unknown/ignored, `args`, `result`, `to`; `context` = the exact system, messages and tools; `model` = the version that answered), caller turns have `text` and `replayed` when recorded words were used, action lines have `source: tts_say`. A record also keeps `start_node`, `date_line`, the starting `world` and `end_reason` (`end_node`, `transfer`, `caller_hung_up`, `max_turns`, `agent_loop`).
- `Conversation.rebuild(record, agent, before_turn)`: replays the record's words and calls (recorded results, not rerun) with `agent`'s prompts and tools, and redoes recorded world changes on the record's world. With the same agent it equals every recorded context (unit test, and checked on a real run).
- `caller.py`: `gpt-4.1-mini-2025-04-14` with strict JSON output `{say, hang_up, use_recorded}`. Recorded answers: the model only picks an index, the code puts the recorded words in verbatim. Anchored (tests): any unused answer; strict (`continue_from`): only the next one, until the first divergence. The caller sees spoken words only.
- `testfile.py`: the test format and `validate_tests` (for model-written tests in #29). `world` replaces the seed's top-level keys. `checks.py`: `tool_called` (succeeded calls only, loose args via `normalize_name`), `tool_not_called` (attempts count), `tool_order` (first calls in order), `call_ended` (optional `reason`), `transferred`, `max_turns`, `judge` (sees words and catalog tool calls with results; never prompts or edge calls; temperature 0; provisional `gpt-4.1-2025-04-14` until #27). Turn checks for `replay_turn`: tool_called, tool_not_called, transferred, judge.
- `runner.py`: `simulate`, `run_test` (rerun once on failure, `flaky`, `error` for `ModelError`, cache in `backend/.sim-cache/` keyed by agent without `ui`, test, resolved world, models, `RUNNER_VERSION`), `run_suite` (parallel; `OpenAIChat` caps 16 requests in flight, SDK retries 5). `replay.py`: `replay_turn`, `continue_from` (take a record or a test result). `config.py`: models, limits, prices.
- CLI: `cd backend && uv run python -m sim run agents/prosper-scheduler.json sim/examples/scheduler-tests.json [--no-cache] [--only ID] [--out FILE] [--transcripts]`. Exit 1 when a result blocks (fail, error, flaky safety), 2 for invalid input.
- Models and rate limits on the company key: `docs/notes/models.md` (10k+ requests/min everywhere, so limits are not a concern).
- Real runs on 2026-10-12: the 3 example tests passed 3/3 in 21.8 s for about $0.19 (agent `gpt-4o` is ~90% of the tokens). `replay_turn` on a real turn: 5/5 in 1.8 s. `continue_from` with the same agent reused all 8 recorded answers. Spent about $1.01 on the key in total for #26, the user's runs included (every run is listed in PR #42).
- Tests: 182 pytest (77 new, all with scripted models; an autouse fixture removes `OPENAI_API_KEY` so no test can call the API), 165 Vitest.
- Checked by the user on 2026-10-14: the 3 example tests passed, and a copy of the example without `transfer_to_human` failed `transfer-on-request` twice (it kept promising a transfer it could not make; `transferred` and `call_ended` caught it). The user's first run showed the misheard-name test passing without saying the garble: the caller prompt asked that a recorded answer "still fit", and the model read a name without its spelling as not fitting. Fixed (partial answers are replayed; picks and yes/no still must fit), measured by replaying only the caller's decision on that turn (2/10 before, 10/10 after; a recorded time pick 10/10 when the same times are offered, 0/10 when not; about 1.5 cents). Runs now report `replay: {recorded, used}` and the CLI warns when a run did not fully replay; `--transcripts` shows edge transitions and recorded lines (the judge's view is unchanged). `RUNNER_VERSION` is 26.2.
- Cheap way to test a caller or judge prompt change: call `Caller.next` (or the judge) directly on the exact turns from a result, 10 times, instead of rerunning whole calls. A cent instead of a dollar.
- Results keep the full context per agent turn, about 165 KB per test. Storing only what each turn adds is an easy change if it matters for #28 or the UI.

What #25 built, for reference:
- `backend/clinic/` (ADR 0008): `catalog.py` is the tool catalog as pure data (`TOOLS`: name, description, parameter schema, `changes_world`, `ends_call`; `catalog()` for the editor). `world.py` is `ClinicWorld`: providers with weekly schedules, patients and appointments from a seed; `now` comes from the seed; open slots are generated from the schedules (ids like `dr-patel-2026-10-12-0900`) and are open when after `now` and not used by a booked appointment. Each tool is a method of the same name; `call(name, args)` checks required args and returns `{"error": ...}` for refusals instead of raising. Names match ignoring case, accents, spaces and punctuation; dates must be YYYY-MM-DD. `live.py` is `LiveClinic`: `state.json` (gitignored), created from `seed.json` on the first change, reread on every call so deleting it resets at once. `make clinic-reset` deletes it.
- Seed (`clinic/seed.json`): Monday 2026-10-12 08:30; Dr. Priya Patel, Dr. Daniel Okafor, Grace Kim NP; patients Ana Lopez (pat-001), James O'Connor (pat-002, appointment 2.5 h away, inside a 24 h window), Mei Chen (pat-003); a cancelled appointment that frees Patel's 09:00.
- Schema: optional `tools: [name]` on nodes (dataclass and zod). Validation: tools must be a list of catalog names, no duplicates, no clash with an edge function in the node (that error carries `edge`, so it badges the edge).
- Builder: `AgentBuilder(config, clinic=None)`; `clinic` is anything with `call(name, args)` and `date_line()`. With a clinic, every node's role message ends with the clinic's date line. Tools come after the edges in the node's functions; the handler calls the clinic, logs `[tool] in node | args | result`, sends RTVI `{type: "tool_call", node, tool, args, result}` and returns `(result, None)`, which keeps the conversation in the node (`pipecat_flows/manager.py:480-520`, `run_llm=True`). `transfer_to_human` returns a one-off node (one line, then `end_conversation`) that is not in the graph, so the UI stays on the node it was called from. Without a clinic a tool answers an error.
- `bot.py`: one `LiveClinic` for every call. Turn timing: Smart Turn v3's `stop_secs` (the longest silence when it judges a turn unfinished) is `TURN_STOP_SECS = 1.2` instead of Pipecat's 3, set through `UserTurnStrategies(stop=[TurnAnalyzerUserTurnStopStrategy(LocalSmartTurnAnalyzerV3(params=SmartTurnParams(...)))])`. Lower is snappier but cuts off a caller who pauses longer while spelling.
- `GET /composer/tools`: the catalog. Editor: tool checkboxes in the node panel (catalog order, first sentence of each description as a hint, tools the catalog lacks kept until unchecked), tool names on node cards, "Tool" rows in the call transcript (args, a folded result, refusals in red).
- Example agent: `greeting -> ask_name -> confirm_name -> verify_patient -> collect_reason -> offer_times -> confirm`. `verify_patient` asks the date of birth and uses `lookup_patient` / `register_patient`; `offer_times` uses `find_slots` and `book_appointment`; the greeting offers `transfer_to_human`. The persona asks for dates spoken naturally, never as numbers.
- Tests: 105 pytest (every tool on the seed, live state, validation, the builder's tool functions with a fake flow manager, the catalog route), 165 Vitest. Checked in the browser pane: checkboxes, card lines, the clash error, tool rows.
- Checked by the user with real calls on 2026-10-12 (`docs/notes/call-tests.md`): all passed, including the one-word answer in about a second and a booking from a `find_slots` slot.

What #13 built, for reference:
- `bot.py`: speech-to-text language fixed to English (`ElevenLabsRealtimeSTTService.Settings(language=Language.EN)`, sent as `language_code=en`; checked against the installed service).
- Example agent: `greeting -> ask_name -> confirm_name -> collect_reason -> offer_times -> confirm`. `confirm_name` reads the name back letter by letter; `name_confirmed` saves `full_name` (the value the acceptance criteria check in the log), `correct_spelling` is a self-loop for "no, it's ...", `spell_again` goes back to `ask_name`. Reason is now its own node.
- Tests no longer use the example agent for editor behaviour: the original four-node example is frozen in `backend/tests/fixtures/linear-agent.json` and both test suites use it. Only "the example is valid", "has no warnings", schema and file round trips still read `prosper-scheduler.json`, so the example can change freely.
- README: quickstart for `make dev` (Node 24, `.env`), `frontend/` in the layout table, the stray `\` fixed. The full README is still #11.
- `docs/notes/call-tests.md`: four manual calls (hard name with a correction, common name, off-topic at the read-back, hang up halfway).
- Checked by the user with real calls on 2026-10-08, all four passed: transcripts in English letters only; "Felu" spelled on purpose, corrected with "No. It's Feliu" (`correct_spelling -> confirm_name`) and read back right; one read-back for a common name; the weather question was declined and the call stayed on `confirm_name`; hang-up left no traceback. Seen in the call: the first question asks for the name and the spelling together, and a caller who gives only the name is asked again to spell it. Fine for now; "one question at a time" goes into the authoring guide (#29).

Earlier notes: The P2 extras of #10 (editable JSON view, node duplication, post-call summary) were not built. For #24, the first `gh pr merge` was blocked by the permission classifier ("Merge Without Review") after the user said "ok yes"; it went through once they said "merge". The stale `docs/plan-and-adrs` branch (merged as #12) still exists locally and on origin: deleting it was blocked by the classifier, so the user deletes it. For #23, the first `gh pr merge` right after a push failed with "not mergeable" while GitHub recomputed; it went through on retry. Note on merging: a first `gh pr merge` for #22 was blocked by the permission classifier ("Merge Without Review"); it went through once the user said "merge" again after being told. For #22, `gh` did delete the remote branch but did not switch or delete the local one (finished by hand, as for #20 and #21).

What #10 built (frontend only), for reference:
- Back edges (`edgePath.ts`): an edge into a node whose top is above the source's bottom gets a route from `routeBackEdges(boxes, edges)`, computed in `toFlowEdges` (which now takes the measured card sizes) and drawn by `backEdgeGeometry`: out of the bottom of the source, up a column, into the top of the target, label beside the column. The column clears every node in the edge's vertical span that starts left of it, plus self-loops and their labels (label width estimated from the function name). Back edges that share a column and overlap vertically get lanes, shorter spans inside, labels stacked by lane. Forward edges and self-loops are unchanged. Known limits: React Flow's fit view counts nodes only, so a column or label right of the graph can start out of view; the column is not checked against nodes to its right.
- Undo/redo (`store/history.ts`): `undo()`, `redo()`, `useCanUndo()`, `useCanRedo()`. After a step the selection is cleared if it points at something the step removed. Toolbar buttons blur the focused field first (ends its edit session, so the typing is one complete step). Cmd/Ctrl+Z, Cmd/Ctrl+Shift+Z and Ctrl+Y, except in a text input or textarea, which keep their own undo.
- Import/export (`agent/file.ts`): Export downloads the draft as `<id>.json` (indent 2, `ui` included, unsaved changes included). Import checks the shape with zod like `getAgent`, keeps the original object (key order), and opens it as a new unsaved agent under a fresh id from its name, like "New". Backend errors in an imported agent show in the problems list as usual.
- JSON tab in the side panel: the whole agent, read-only, live, with Copy.
- Tests: 160 in Vitest (undo after rename, delete and connect restores the same agent object; selection after undo/redo; back-edge routes, including the example agent with `confirm -> greeting` sampled against every card; file round trip and errors).
- Checked in the browser pane: back edges and lanes next to a self-loop and parallel edges, Undo/Redo buttons and shortcuts, Cmd+Z in a text field left to the field, Undo while typing, live JSON tab, export (download captured from JS), import of a valid and an invalid file.

What #9 built (frontend only), for reference:
- `src/validation/warnings.ts`: `agentWarnings(agent)` returns `Problem`s with `severity: "warning"`, by node in file order: not reachable from the start node (BFS over edges whose target exists; skipped when `initial_node` does not exist, which is already a backend error), dead end (not `end` and no edges), end node with edges (the builder queues `end_conversation` right after the node's first reply, so they are never taken), no task messages, each empty task message, empty edge description (on the edge), `required` names missing from `properties` (on the edge). Reads the draft defensively (non-array fields are treated as empty), since it runs on every edit.
- `useProblems()` merges them after the backend errors. Warnings are computed from the current draft, so they update at once while errors follow the 400 ms check. They never go into `useValidationStore`, which is what the call checks, so they cannot block a call.
- The problems summary is yellow when there are only warnings. Badges and the list needed no other change.
- The example agent has no warnings (tested). A new blank agent has two (dead end, empty task message), which is correct.
- Tests: 144 in Vitest (one fixture per warning, clean and example agents, cycles and self-loops, missing start node, malformed shapes; a call placed with an agent that only has warnings).
- Checked in the browser pane: badges on nodes and edge labels with tooltips, the list, selecting a node from a warning, Test call enabled with warnings.
- To reach a backend error from the UI (the editor blocks most at edit time): clear the agent name (agent-level, no badge), or give an edge's fields JSON box a property without a type, e.g. `{"properties": {"x": {}}}` (red badge on the edge). Clearing a node name does not work: `NameInput` never writes an invalid name.
- Not done: the node panel's "end node with After actions never hangs up" note is still only in the panel; it could become a warning too.

What #8 built (frontend only; the backend message existed since #1), for reference:
- `transcript.ts`: a third entry kind, `Transition` (`{role: "transition", from, function, to, args}`), and `parseTransition(data)` for the server message. Transitions go into the same list as the user and bot turns, so the panel shows what was said around each one, and they stay after hang-up until the next call like the rest of the transcript. A transition ends the current user turn (the next final starts a new one); bot progress messages still find their sentence across it.
- `callStore.ts`: `live: {agentId, node, edge} | null`. Set at bot-ready to the `initial_node` of the agent that was sent, and the editor's `agentId` at the moment it was sent; each transition moves `node` to `to` and sets `edge`. Cleared when the call ends (`finish`) and at the start of a call. `onServerMessage` ignores other message types and messages from a call that is no longer current.
- Canvas: `toFlowNodes(..., activeNode)` and `toFlowEdges(..., activeEdge)` add `active` to the node and edge data and `animated` to the edge. `Canvas.tsx` passes them only when `live.agentId` is the open agent. Matched by node name: a node renamed mid-call loses its highlight. CSS: the active node has a green outline (so it combines with the blue selection), the edge taken is green and animated, its label green.
- `CallPanel.tsx`: transition rows in the transcript (`choose_intent → collect_details`, then the collected args as a key/value list).
- Tests: 132 in Vitest (call store: initial node, following transitions, editor changes mid-call, cleared at hang-up with transitions kept, late transitions from an earlier call; `parseTransition`; derive flags).
- Checked in the browser pane by setting the call store from JS (no mic there): highlight, animated edge, selection plus highlight, transition row, cleared after the call, no highlight when another agent's call is live.

**Real-call check** (done by the user; kept for reference. `make dev`, open the example agent, Test call, Call): the start node is outlined in green as soon as the call connects; after each answer that moves the conversation on, the `[function] -> target | collected: {...}` line in the `make dev` terminal must match the newly outlined node, the animated edge and the new "Transition" row in the panel. After hang-up (or the end node) the outline and animation go away and the transcript, transitions included, stays until the next call.

What #7 built (`frontend/src/call/`), for reference:
- `callStore.ts`: one call at a time, a fresh `PipecatClient` per call (dynamic import, so the WebRTC stack is a separate chunk). `startCall()` runs four steps shown in the panel: `backend` (`GET /composer/health`), `agent` (`checkAgent` on the draft, which also fills the problems list), `mic` (`initDevices()`, then `mediaState.mic` must be `granted`), `bot` (`startBotAndConnect` raced against a 15 s bot-ready timeout). `hangUp()` hangs up, or cancels a call still being placed. `setMuted`, `selectMic`, `listMicsIfAllowed`. Dependencies are injectable with `setCallDeps` for tests.
- `transcript.ts`: turns from `user-transcription` (partials replaced, finals joined) and `bot-output` (one segment per sentence, showing `spoken_progress.accumulated_text`).
- `CallPanel.tsx`: a 320px column right of the side panel, opened with "Test call" in the toolbar. Call / Cancel / Hang up, Mute, status with a timer, step list, notice, mic picker, transcript. `CallAudio` plays the bot and is mounted in `App`, so closing the panel does not cut the call.
- Checked by the user with real calls (edit without saving, mute, transcript, second call, end node) and in the browser pane (missing keys, agent errors, blocked mic, the 15 s timeout against a bot that crashes).

**Pending for the user:** rotate the ElevenLabs key; it appeared in a log during #5 (see section 4, Secrets).

**How we work through an issue:**
1. Branch `issue-N-short-name` from `main`, one branch and PR per issue, PR body ends with `Closes #N`.
2. Build, run `make test`, and verify in the real app (see "Testing without disturbing the user" below).
3. Commit locally and summarise for the user. **Ask before pushing, opening a PR or merging.** Once the user says "merge", merge with `gh pr merge <n> --merge --delete-branch`, then update local `main`, delete the local branch and create the next one. For #20 and #21, `gh` merged and deleted the remote branch but printed nothing and did not switch or delete the local branch; check with `git branch` and finish by hand (`git fetch --prune`, `git switch main`, `git pull --ff-only`, `git branch -d`).
4. Things that need a mic (a real call) are checked by the user: give them exact steps and what to look for in the terminal and the browser DevTools console (Cmd+Option+J). The user runs `make dev` in a terminal outside the app, so its output is not readable from the session; ask them to paste it.

## 1. The task

Build a UI for creating and editing voice agents, where an agent is a graph of nodes (conversation steps) and edges (transitions). The user must be able to edit the graph and place a test call from the UI, similar to ElevenLabs Agents or Retell AI. Changing the node format or backend is allowed if justified.

- **Phase 1 (now):** graph editor + test call.
- **Phase 2 (later):** an AI Composer that generates and edits agents from natural language. Phase 1 decisions should keep the agent JSON clean and easy for an LLM to read and write. Now planned as the Agent Copilot in [`PLAN-phase2.md`](../PLAN-phase2.md).
- Domain: voice AI for healthcare scheduling.

Repo: `feliuserra/prosper-challenge-agent-copilot`, local path `~/Desktop/work/prosper-challenge-agent-copilot`.

## 2. Local environment

- **Intel Mac (x86_64).** The dependency pins for it are committed (PR #15) behind `darwin`/`x86_64` markers, so other platforms resolve as before. Nothing local is uncommitted any more.
- **Tools:** Node 24 in `/usr/local/bin`, `gh` and `uv` in `~/.local/bin`. No Homebrew or nvm. Prefix commands with `PATH=$HOME/.local/bin:/usr/local/bin:$PATH` when a shell does not find them.
- **GNU Make 3.81** (macOS default). It has no `.ONESHELL:`; see the Makefile gotcha below.
- **The repo is a fork** of `Prosper-Technologies/prosper-challenge-agent-copilot`. Always pass `--repo feliuserra/prosper-challenge-agent-copilot` to `gh` so issues and PRs never land upstream. There is no CI on the fork.
- **`backend/.env`** holds `OPENAI_API_KEY` and `ELEVENLABS_API_KEY`. Never read or print it. Keys are company-provided and usage is visible to them, so do not place calls casually.
- **Stage files explicitly**, never `git add -A` or `git add .`.

**Commands** (from the repo root):

| Command | What it does |
| --- | --- |
| `make install` | `uv sync` for the backend, `npm ci` for the frontend |
| `make dev` | Runner on 7860 + Vite on 5173, open `http://localhost:5173`. Ctrl+C stops both |
| `make run` | Runner only, prebuilt Pipecat client at `http://localhost:7860/client` |
| `make test` | pytest (backend, 182 tests) + Vitest (frontend, 165 tests) |
| `cd backend && uv run python -m sim run <agent> <tests>` | Text runner: simulated calls graded by tests (#26); costs model calls |
| `make clinic-reset` | Restore the live clinic (bookings made in calls) to its seed |

**Testing without disturbing the user.** The user often has `make dev` running on 7860/5173. Do not kill their processes. Run a second backend and frontend on spare ports instead:

```bash
cd backend && .venv/bin/python bot.py --port 7861            # background
cd frontend && RUNNER_URL=http://localhost:7861 npx vite --port 5174 --strictPort   # background
```

Then drive `http://localhost:5174` in the built-in browser pane. Its mic is blocked, which is fine for everything except hearing the bot. A call stops at the Microphone step there; faking `getUserMedia` does not get past Daily's device matching. To test the bot step anyway, import the app's own store in the page (`await import("/src/call/callStore.ts")`, the same module instance the panel uses) and `setCallDeps({createClient})` with a real `PipecatClient` wrapped so `mediaState` reports the mic as `granted`. With a working bot this places a real call (key usage), so only do it against a bot that fails before building services. In dev builds the store is on `window.agentStore` (e.g. `window.agentStore.getState().moveNode("greeting", {x: 0, y: 0})`). `window.prompt`/`confirm` can be stubbed from JS to drive the "New" buttons. Afterwards stop both servers and delete any agent files the test created in `backend/agents/`.

## 3. What the repo contains now

### Backend (`backend/`)
- `bot.py`: Pipecat pipeline (SmallWebRTC, ElevenLabs realtime STT + TTS, OpenAI LLM, Silero VAD) driven by a Pipecat Flows `FlowManager`. It mounts the agents API on the runner app and, in `bot()`, builds the agent from `runner_args.body["agent"]`:
  - no agent sent (e.g. the prebuilt `/client`): uses `agents/prosper-scheduler.json`;
  - invalid agent: logs every error and calls `reject_call()`, which runs an empty pipeline, sends an RTVI error "Invalid agent: ..." once the client is ready, and ends the call. It never falls back to another agent. Closing the WebRTC connection directly does not work (the client is still connecting and never notices); see `docs/notes/runtime.md` section 4.
- `composer_api.py`: router factory `make_router(agents_dir)` under `/composer`: `GET /agents` (`{agents: [{id, name}]}`), `GET|PUT /agents/{id}`, `POST /validate` (`{errors: [...]}`, always 200), `GET /health` (`{ok, missing_keys}`, from the process env, never values), `GET /voices` (`{voices: [{id, name, category}], error?}`, the ElevenLabs account's voices for the voice picker, fetched once per process with an injectable fetcher for tests; always 200, `error` says why there is no list). The id is the file stem, a lowercase slug `[a-z0-9][a-z0-9_-]{0,63}`, separate from the agent's display name. `PUT` validates (422 with every error), writes atomically and stores the JSON exactly as received.
- `agent_builder/validation.py`: `validate_agent(dict) -> list[ValidationIssue]` with `{message, node, edge}` records (`edge` is the function name). Runs on the raw dict, so missing keys and wrong types are errors, not `KeyError`. Checks: name, nodes, `initial_node`, unique node names, edge targets, function names (`fullmatch [a-zA-Z0-9_-]{1,64}`), unique function names per node, `properties` values are objects with a known `type`, `required` is a list of strings, field types, task messages have a `role`, actions have a `type`. Unknown keys are allowed.
- `agent_builder/builder.py`: `AgentBuilder.from_dict` validates and raises `ValidationError(ValueError)` carrying all records; the constructor validates `asdict(config)`. Each edge handler updates `flow_manager.state`, logs, and queues an RTVI server message `{type: "transition", from, function, to, args}` (Issue #8 builds the UI on it). Nodes are built lazily on transition.
- `agent_builder/schema.py`: dataclasses `AgentConfig` (`name`, `initial_node`, `nodes`, `persona`, `voice_id`, `model`), `Node` (`name`, `task_messages`, `role_message`, `edges`, `pre_actions`, `post_actions`, `end`), `Edge` (`function`, `description`, `target`, `properties`, `required`). Unchanged from the starter.
- `clinic/`: the tool catalog, the fake clinic world and the live state shared by calls (#25, see section 0).
- `sim/`: the text runner, test format, checks, turn replay (#26, see section 0).
- `agents/prosper-scheduler.json`: the example and default agent (was `example_flow.json`). Written with indent 2, as the editor saves it (since #25).
- `tests/`: pytest for validation and the API (TestClient on a bare FastAPI app with a temp dir, no voice stack). Dev deps: `pytest`, `httpx2` (Starlette's TestClient deprecates `httpx`).

### Frontend (`frontend/`)
- Vite 8 + React 19 + TypeScript 7, zustand 5 + zundo 2, zod 4, Vitest 5. `@pipecat-ai/client-js` 1.13.1 and `@pipecat-ai/small-webrtc-transport` 1.10.8 pinned exactly. `@pipecat-ai/client-react` 1.8.2 is compatible but not installed; #7 did not need it (the call state lives in a zustand store like the rest). Node 24 in `.nvmrc`.
- `vite.config.ts`: proxies `/start`, `/sessions`, `/api`, `/composer` to the runner (`RUNNER_URL`, default `http://localhost:7860`).
- `src/agent/schema.ts`: zod mirror of the dataclasses. Loose objects, actions as opaque records, optional `ui: {x, y}` per node, **no defaults**. `api.getAgent` uses zod only to check the shape and returns the original object, so a load/save round trip keeps values and key order.
- `src/agent/names.ts`: `FUNCTION_NAME_RE`, `sanitizeFunctionName`, `uniqueName`, `placeholderFunctionName` (`go_to_<target>`, `_2`, `_3`... within 64 chars), `agentIdFor` (slug for new agents). `src/agent/templates.ts`: `blankAgent(name)` (one `start` node at 0,0), `EXAMPLE_AGENT_ID`.
- `src/store/agentStore.ts`: `useAgentStore` with `agent`, `agentId`, `savedJson`, `selection` (`{kind: "node", name}` or `{kind: "edge", source, function}`) and named operations: `open`, `markSaved`, `select`, `addNode(position?)`, `deleteNode` (refuses the start node; removes incoming edges), `renameNode` (cascades to targets, `initial_node`, selection; rejects duplicates and empty), `updateNode`, `connect(source, target)` (placeholder name, selects the edge), `updateEdge` (rejects duplicate function names; follows a rename with the selection), `deleteEdge`, `setInitialNode`, `moveNode` (writes `ui`), `updateAgent`. Rejectable operations return `{ok: false, error}` and leave the store unchanged. `selectIsDirty(state)` compares with `savedJson`.
- zundo: `useAgentStore.temporal`, partialized to `{agent}`, `equality` on the agent reference, so selection changes are not recorded. `open()` clears history. Drags are one history entry each (see section 4).
- `src/agent/layout.ts`: `autoLayout` (dagre, top to bottom, integer positions), `placeMissing` (below a positioned source node, else a fallback; never moves positioned nodes), `withPositions` (full layout only when no node has a position), `freeSpot`, `nearestFreeSpot`, `NODE_WIDTH`. The store uses it in `open` (fills missing positions without marking the agent unsaved, since they are deterministic), in `addNode()` without a position, and in `tidyLayout()`.
- `src/api.ts`: `listAgents`, `getAgent`, `saveAgent` (returns validation errors on 422), `validateAgent`, `listVoices`.
- Store patches (#5): in `updateNode`, `updateEdge` and `updateAgent`, a value of `undefined` removes the key, so clearing an override does not leave `""` in the file.
- `src/store/editSession.ts` (#5): one undo step per focused text field (see section 4).
- `src/agent/fields.ts`: collected-field operations returning an `EdgePatch` (add, remove, rename in place and in `required`, change spec keys, toggle required) and the JSON parsers for the fallback box and raw actions. `options.ts`: backend defaults (`DEFAULT_VOICE_ID`, `DEFAULT_MODEL`), the model list, field types, task roles. `names.ts` has `nodeNameError` and `functionNameError` for inline errors.
- `src/panel/` (#5): `Panel` shows the editor for the selection (`AgentPanel` when nothing is selected, `NodePanel`, `EdgePanel`) and has the `nokey` class so React Flow ignores key presses from it. `controls.tsx`: `LiveText` (writes on every keystroke), `NameInput` (identifiers: inline error while typing, written on blur or Enter only if valid, Escape cancels), `JsonField` (written only when it parses; the error stays until fixed), `ChoiceWithCustom`. Save blurs the focused field first, so a name being typed is committed and saved.
- `src/components/`: `Toolbar` (agent picker, New blank, New from example, Import, Export, Undo, Redo, Save, Cmd/Ctrl+S and +Z, unsaved indicator, leave-page warning; a rejected save says how many errors and points to the problems list; the "Test call" toggle for the call panel). The read-only `Outline` was removed in #4.
- `src/call/` (#7, #8): see section 0.
- `src/validation/` (#6, #9): `warnings.ts` (client-side warnings, see section 0); `validationStore.ts` holds the latest backend errors and a `failure` message (backend unreachable), outside the agent store and its history. `checkAgent(agent, run?)` validates and publishes; save passes `saveAgent` as `run`, since it returns the same records on 422. `watchAgent()`, started in `App`, checks the open agent 400 ms after it stops changing and at once when another agent is opened (dropping the previous agent's errors). `problems.ts`: the `Problem` type (`ValidationIssue` plus `severity`), `useProblems()`, and helpers for the list (what to select, the location label, which nodes to bring into view).
- Problems on the canvas (#6): `statusBadges` in `derive.ts` groups problems by their `node`/`edge` fields into one badge per severity ("2 errors", messages in the tooltip) for node cards and edge labels. `ProblemsList.tsx` is a collapsible strip below the graph; clicking a problem selects its node or edge (or nothing, for agent-level problems, which shows the agent settings) and fits the view to it. `Canvas` is now a column: `.canvas-flow` (React Flow, and the box Add node measures) above the strip.
- `src/canvas/` (#4, `@xyflow/react` 12 and `@dagrejs/dagre`, the maintained fork of `dagre`): `Canvas.tsx` (controlled React Flow, remounted per agent id; Add node and Tidy layout panel; minimap, controls; notice panel), `derive.ts` (store to React Flow: `toFlowNodes`, `toFlowEdges`, `edgeId`/`parseEdgeId`, `NodeStatus` type for the badge slot #6 and #9 fill), `changes.ts` (React Flow change lists to store operations: positions, selection, measurements), `NodeCard.tsx`, `FunctionEdge.tsx` (label is a button that selects the edge) with its shapes in `edgePath.ts`: edges between the same two nodes get lanes that bow the curves apart and stack the labels, and a self-loop goes round the right side of its node. A lane-0 edge is exactly React Flow's default bezier (tested).
- Reconnecting: only the selected edge has a reconnect knob (a blue circle over its arrowhead), and `elevateEdgesOnSelect` draws it above other edges ending at the same handle. Click an edge, then drag the knob to another node.
- Single selection only: multi-select and box select are off, matching the store's `selection`.
- Tests: `names.test.ts`, `schema.test.ts`, `agentStore.test.ts`, `layout.test.ts`, `derive.test.ts`, `changes.test.ts`, `edgePath.test.ts`, `fields.test.ts`, `editSession.test.ts`, `problems.test.ts`, `validationStore.test.ts`, `transcript.test.ts`, `callStore.test.ts`, `warnings.test.ts`, `history.test.ts`, `file.test.ts` (160 in total). No component tests; the panel and the problems list are checked in the browser.

## 4. Known gotchas

**Secrets**
- **Never format an HTTP client exception with `repr` (`{error!r}`) or log its request info.** An aiohttp `ClientResponseError` repr includes the request headers, so the ElevenLabs key ended up in a test runner log during #5 (the log was deleted; the user was told). `composer_api.py` builds its errors from the HTTP status and ElevenLabs' message only, and logs just the type for anything else.

**Runtime and call**
- **The draft must be sent as `requestData.body`.** `startBotAndConnect({endpoint: "/start", requestData: {body: {agent}}})`. The runner keeps only `body` between `/start` and the offer. The agent's loose TS type needs a documented cast to client-js's `Serializable` (see `CallButton.tsx`).
- Mic requires localhost or HTTPS; browsers block audio playback until a user click.
- Pipecat renames APIs often. Read the installed package source rather than blog examples.
- **Missing keys or a bot crash hang the client** at "Connecting" (the runner answers the offer before the bot runs). The call panel (#7) checks `/composer/health` first and gives up after 15 s without bot-ready, pointing to the terminal.
- **A blocked microphone does not make `initDevices()` throw.** The transport's Daily media manager swallows the denial, so the call would go ahead with a bot that hears nothing. client-js records it in `client.mediaState.mic` (`{state: "error", reason: "blocked"}`); the call store requires `granted` before starting the bot. Found when a call from the browser pane (mic blocked) connected anyway.
- **Bot transcript comes from `bot-output`.** With protocol 2.0 the server sends one `bot-output` per sentence (`spoken_status: "new"`, nothing spoken yet) and then progress messages with `spoken_progress.accumulated_text` as words are spoken (`pipecat/processors/frameworks/rtvi/observer.py:645-760`). Word-level `bot-output` is not sent to 2.0 clients. `bot-transcription` is deprecated.
- **The call store ignores events from a call that is no longer current** (hung up, failed, replaced): a late `onDisconnected` from the first call must not end the second.
- **Server messages** of type `transition` become transcript entries and move `live` (#8). Others are ignored.
- **Create a fresh Pipecat client per call.** The bot can end the call itself (end node); treat that as a normal hang-up.
- **Collected args are logged and sent to the browser** (transition events). In production these are PHI. Fine for the demo; say so in the README (#11).
- **Makefile background jobs** need a single-shell recipe (lines joined with `;` and `\`). make 3.81 ignores `.ONESHELL:`, and `trap 'kill 0' EXIT` then kills make itself. The `dev` target's trap kills only the background runner.
- Browser console noise from extensions (e.g. `zotero.js`, `inject.js`) and a `favicon.ico` 404 are harmless.

**Editor**
- **React Flow ids.** Node id = node name, edge id = `${source}::${function}`. Unique because the store never holds duplicate function names in a node, even while typing (`updateEdge` rejects them). Selection lives in the store and follows renames.
- **Dragging vs. undo.** Positions go to the store on every drag frame (`moveNode`). zundo records the "before" state only on a tracked write, so pausing *before* the first write would leave a drag with no history entry. `changes.ts` keeps the drag's first write and pauses right after it, then resumes on the `dragging: false` changes at the end of the batch. Those changes are also sent when a drag is aborted, which skips `onNodeDragStop`, so tracking cannot stay paused.
- **Controlled React Flow needs `measured` back.** It takes node sizes only from the node objects you pass in, so the canvas keeps reported sizes in component state and merges them into the derived nodes. They are DOM measurements, not agent data.
- **Deletes go through `onDelete`, not `remove` changes.** It sees the whole deletion, so edges that `deleteNode` already cascades are skipped (one delete is one history entry). `onBeforeDelete` blocks the start node with a notice.
- **Add node** goes to the centre of the view, or the nearest free spot that is still visible, falling back to the centre on top of other nodes.
- **Reconnect knobs and shared handles.** Each edge's reconnect anchor sits just above its target handle, and edges rendered later cover earlier ones there with their wide hit strokes. That is why only the selected edge gets an anchor and is elevated. React Flow also paints a mouse-focused edge as selected; `index.css` keeps that for keyboard focus only.
- **Driving the canvas in the browser pane:** select an edge first, then find its knob with `document.querySelectorAll('.react-flow__edgeupdater-target')`. The pane's screenshot frame is 800x600 over a 1024x768 viewport; screenshots right after a drag can be one render behind.
- **Typing and undo.** Text fields write on every keystroke, so the canvas, a save and a test call always see the current text. `editSession.ts` makes each focused field one history entry, like drags: the session's first write is recorded and history is paused after it until blur or unmount. A session only resumes history it paused itself, so it never ends a drag's pause.
- **Names are identifiers and are written on blur or Enter,** not per keystroke: renaming a node changes its React Flow id, and writing every keystroke would remount the node and cascade each partial name.
- **End and post-actions.** The builder adds `end_conversation` only when a node is `end` and has no post-actions. With post-actions and no `end_conversation`, an end node never hangs up; the node panel warns about it.
- **Voices.** The company ElevenLabs key lacks the `voices_read` permission, so `/composer/voices` answers with an error and the panel falls back to a plain voice-ID input with the reason as a hint. With a key that can read voices, the panel shows a dropdown and flags a `voice_id` that is not in the account.
- **Validation errors are structured.** Badges and the problems list use `node`/`edge` from `/composer/validate`. Do not parse error strings. The backend tests pin the `(node, edge)` of every rule.
- **Checks finish out of order** (a debounced check, then a save). Each check takes a number when it starts and may only publish if it is newer than the last one published, so an older draft's errors never replace a newer one's. Opening another agent invalidates checks still running.
- **An edge whose target is missing is not drawn,** so its problems go on its source node's badge, prefixed with the function name. The list still selects the edge, and the edge panel shows the target as "(missing)".
- **The call button is disabled from the latest check,** which can be up to 400 ms plus a request behind the draft. That is only a hint; the click validates the current draft again and does not connect if it has errors.
- **The problems strip has the `nokey` class.** React Flow listens for Delete/Backspace on the whole document, so without it Backspace on a focused problem would delete the node it just selected.
- **Keep zod objects loose and add no defaults**, or a round trip drops or adds fields.

## 5. Open items not tracked in an issue yet

- **Slow end of turn.** Smart Turn v3 marks short answers ("Book.") as incomplete, so the bot waits for the 3 s silence fallback (`End of Turn complete due to stop_secs. Silence in ms: 3000`). Tunable via `LLMUserAggregatorParams`. Now part of #25 (turn timing).
- **Agents saved from the editor** land in `backend/agents/` as untracked files. Decide before the demo whether to commit or gitignore them (the example must stay tracked). To be decided in #28.
- **ElevenLabs default voices.** Per ElevenLabs' docs, legacy voices such as Rachel (`21m00Tcm4TlvDq8ikWAM`, the backend's `DEFAULT_VOICE_ID` and the example's voice) now route to replacement voices (Rachel to "Janet"), and default voices expire on December 31, 2026. Pick a voice the account owns for the example and the default before then. Not tracked in an issue yet.
- **One early disconnect** was seen in a WebKit browser during #1 (cause unknown). Chrome works. Look again in #7 if it recurs.

## 6. Changes from the original plan

Recorded so the reasoning is not lost:
- `create_issues.py` never existed: issues were created from `PLAN.md` as GitHub issues #1 to #11 (plus #13) on the fork.
- ADR 0005 is Accepted with Option A and a single process (#1).
- ADR 0004: the builder collects all errors as structured records; `properties` is checked by hand, no `jsonschema`. Unique node names were added as a check in #2.
- Duplicate function names are rejected at edit time, not only flagged, to keep React Flow edge ids unique.
- The bot re-validates the received draft and ends the call with an RTVI error on an invalid one (#2).
- `example_flow.json` moved to `backend/agents/prosper-scheduler.json` (#2).
- The store refuses to delete the start node (#3), the rule #4 asks the canvas to enforce.
- Drag history (#4): the drag's first position write is recorded and history is paused after it, instead of pausing on drag start (see section 4).
- `@dagrejs/dagre` instead of `dagre`, which has been unmaintained since 2022 (#4). Same library and API, with bundled types.
- Reconnecting an edge keeps its function name, even a placeholder such as `go_to_<old target>`. Rename it in the side panel (#5).
- The voice picker lists the account's voices from ElevenLabs (`/composer/voices`) instead of a hard-coded list, because ElevenLabs keeps retiring default voices (#5). Models stay a short static list plus "Custom".
- Collected fields are a two-line list per field (name, type, required, remove; description below) rather than a five-column table, to fit the 360px panel (#5). Keys the list does not show, such as `enum`, are kept and edited in the JSON box.
- Makefile background jobs use a single-shell recipe; `.ONESHELL:` does not work with make 3.81 (#2).
- The demo video in #11 is recorded by the user.
- The call panel is a third column, opened from the toolbar, rather than part of the side panel or the problems strip, so neither the selection editor nor the problems list is hidden during a call (#7). At 1024px wide the canvas gets narrow while it is open; close it to edit.
- The mic step checks `mediaState.mic` after `initDevices()`, and the step list shows each phase's result, since "checking" is too fast to see against a local backend (#7).
- Stray `\` after a code fence in `README.md`: fix in #11.
- Back edges (to a node above the source) were plain curves that crossed the nodes in between; #4 only routed self-loops and parallel lanes. Added to #10's scope during #9 and built in #10.
- Import opens the file as a new agent instead of replacing the open one (#10), so it cannot overwrite a saved agent by accident.
- #13 was built before #11, on the existing example agent instead of the demo agent. #11 moved to the end, after Phase 2: one README and one video for both phases, and the full demo agent may come from the Composer. A short `make dev` README fix went in with #13.
- Two issues were added after the Phase 2 plan, from a brainstorm on what to ask a client: #38 (intake checklist, coverage in the spec step) and #39 (an intake call generated from it). No ADR; the reasoning is in the issues and in section 0. About a day added to the estimate; #39 was placed in the cut order after the sentence ablation and the win-probability chart, then moved to first on 2026-10-14.
- After the interviewer's answers (2026-10-14): #43 and ADR 0016 (clinic configuration as data, agents from a template; amends ADRs 0008, 0012 and 0015) added before #27, about a day and a half. #27, #29, #30, #31 and #38 were updated for it on GitHub and in `PLAN-phase2.md`.
