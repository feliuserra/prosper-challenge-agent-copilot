# Phase 1 plan: graph editor + test call

Issues in build order. Context is in [`docs/handoff.md`](docs/handoff.md), decisions in [`docs/adr/`](docs/adr/README.md). Each item is a GitHub issue on the fork (same numbers). One branch/PR per issue, referencing the issue number (`Closes #N`). GitHub is the source of truth for status; update this file only when scope changes.

Priority: **P0** must ship, **P1** strongly recommended, **P2** only if time allows.

## Prerequisites (user)

- [x] Install Node.js (current LTS).
- [x] Create `backend/.env` with `OPENAI_API_KEY` and `ELEVENLABS_API_KEY`.
- [ ] Decide when to commit the Intel Mac dependency pins in `backend/pyproject.toml` / `uv.lock` (and restore `package = false`). Issues must not commit them.
- [x] Install `gh` and move these issues to GitHub.

## Checklist

- [ ] [#1](https://github.com/feliuserra/prosper-challenge-agent-copilot/issues/1) Verify runtime assumptions and prove a minimal call (spike) · P0
- [ ] [#2](https://github.com/feliuserra/prosper-challenge-agent-copilot/issues/2) Agents API on the runner and agent handover to the bot · P0
- [ ] [#3](https://github.com/feliuserra/prosper-challenge-agent-copilot/issues/3) Frontend skeleton, schema and store · P0
- [ ] [#4](https://github.com/feliuserra/prosper-challenge-agent-copilot/issues/4) Graph canvas · P0
- [ ] [#5](https://github.com/feliuserra/prosper-challenge-agent-copilot/issues/5) Side panel editors · P0
- [ ] [#6](https://github.com/feliuserra/prosper-challenge-agent-copilot/issues/6) Validation errors · P0
- [ ] [#7](https://github.com/feliuserra/prosper-challenge-agent-copilot/issues/7) Test call panel · P0
- [ ] [#8](https://github.com/feliuserra/prosper-challenge-agent-copilot/issues/8) Live transition events · P1
- [ ] [#9](https://github.com/feliuserra/prosper-challenge-agent-copilot/issues/9) Authoring warnings · P1
- [ ] [#10](https://github.com/feliuserra/prosper-challenge-agent-copilot/issues/10) Editor polish · P1
- [ ] [#11](https://github.com/feliuserra/prosper-challenge-agent-copilot/issues/11) Demo agent, README and demo video · P0
- [ ] [#13](https://github.com/feliuserra/prosper-challenge-agent-copilot/issues/13) Reliable caller identity capture · P1 (built before #11, on the existing example agent)

---

## 1. Verify runtime assumptions and prove a minimal call (spike) · P0

**Goal:** Confirm the remaining assumptions, and prove the riskiest integration (a WebRTC call from our own frontend, carrying data to `bot()`) before building the editor on top of it.

**Already verified** (see handoff section 3): `task_messages` shape, runner app is extensible, `/api/offer` and `/start` forward request data as `runner_args.body`, RTVI is on by default, `AgentBuilder` construction has no side effects.

**Scope:**
- Which endpoint and payload field `@pipecat-ai/client-js` `startBotAndConnect` (with the SmallWebRTC transport) uses, and confirm a custom payload arrives in `runner_args.body` in `bot()`.
- Register one test route on `pipecat.runner.run.app` from `bot.py` and confirm it is served on 7860 alongside `/client`.
- Push an `RTVIServerMessageFrame` from an edge handler (via `flow_manager.worker`) and receive it in client-js.
- Compatible versions of `@pipecat-ai/client-js`, `@pipecat-ai/small-webrtc-transport`, `@pipecat-ai/client-react` for the server's RTVI version.
- A throwaway bare Vite page with a Call button, connecting through the Vite proxy. It can be deleted afterwards or become the seed of `frontend/` in Issue 3.

**Acceptance criteria:**
- You can hear the bot from the bare page, and a test value sent from the page is logged by `bot()`.
- A test server message from an edge handler is logged in the browser console.
- Findings and working client library versions written to `docs/notes/runtime.md` with file/line references into the installed packages.
- ADR 0005 set to Accepted (Option A) or amended (Option B); ADR 0006 confirmed or amended.

## 2. Agents API on the runner and agent handover to the bot · P0

**Depends on:** 1

**Scope:**
- `backend/agents/` folder, seeded with the example agent.
- Routes on the runner app under `/composer/` (ADR 0005), in their own module imported by `bot.py`: `GET /composer/agents`, `GET /composer/agents/{name}`, `PUT /composer/agents/{name}`, `POST /composer/validate`, `GET /composer/health`. Agent names are sanitised for use as file names (no path traversal).
- Builder validation reworked per ADR 0004:
  - collect all errors as `{message, node, edge}` records in a `ValidationError(ValueError)`;
  - tolerant parsing so missing required keys become errors, not `KeyError`;
  - new checks: function-name pattern `^[a-zA-Z0-9_-]{1,64}$`, unique function names within a node, `properties` values are objects with a known `type`, `required` is a list of strings.
- `/composer/validate` returns `{errors: [...]}`; `PUT` of an invalid agent returns 422 with the same list.
- `/composer/health` reports which required keys are missing from `backend/.env`.
- Handover (Option A unless Issue 1 said otherwise): `bot()` builds from `runner_args.body`; no agent sent means the example agent; an invalid agent is logged and the call ends, with no silent fallback.
- pytest as a uv dev dependency (coordinate with the uncommitted pins in `pyproject.toml`).
- Makefile `dev` target that starts the runner (+ frontend once it exists) as background jobs, in a single-shell recipe whose `trap` stops the runner when the frontend exits (`.ONESHELL:` is ignored by the make 3.81 that macOS ships).

**Acceptance criteria:**
- The next call uses the handed-over agent with no restart.
- An invalid agent returns 422 with every error, each tied to its node/edge, and can never run in the bot.
- Tests for each validation rule, including invalid and duplicate function names within a node and a malformed `properties`.
- `/composer/health` lists missing keys.
- Existing `make run` flow and the prebuilt `/client` still work.

## 3. Frontend skeleton, schema and store · P0

**Depends on:** 2

**Scope:**
- Vite + React + TS app in `frontend/`, Vite proxy for `/composer`, `/start`, `/sessions`, `/api` to 7860. Pin Node in `.nvmrc` and the client library versions found in Issue 1.
- zod schema mirroring the dataclasses, with loose objects (unknown keys preserved), actions as opaque records, plus optional `ui: {x, y}` per node (ADR 0002).
- Zustand store holding one `AgentConfig` and the current selection; all changes through named operations: `addNode`, `deleteNode`, `renameNode`, `updateNode`, `connect`, `updateEdge`, `deleteEdge`, `setInitialNode`, `moveNode`, `updateAgent` (ADR 0001).
  - `renameNode` rejects duplicates and updates edge targets, `initial_node` and the selection.
  - `updateEdge` rejects a function name already used in the node (store unchanged, error returned to the caller) and updates the selection when the name changes (ADR 0003).
  - `connect` creates a placeholder function name `go_to_<target>`, sanitised to the function-name pattern and suffixed (`_2`, `_3`, ...) if it already exists in that node, with `description: ""`.
  - `deleteNode` removes incoming and outgoing edges.
- zundo middleware on the store, partialized to the agent only (undo UI comes in Issue 10).
- Agent list, open, new (blank = one start node, or copy of example), save, unsaved-changes indicator, Cmd/Ctrl+S.
- Frontend unit tests with Vitest.

**Acceptance criteria:**
- Load then save preserves the agent exactly, apart from added `ui` fields, including keys the schema does not model.
- A new blank agent passes `/composer/validate`.
- Unit tests for the operations, including rename cascade (edge targets, `initial_node`, selection), duplicate rejection (node names, function names), delete-node cascade, and placeholder naming (sanitising, suffix).

## 4. Graph canvas · P0

**Depends on:** 3

**Scope:**
- Controlled React Flow view derived from the store; pan, zoom, minimap, fit view. Node id = name, edge id = `${source}::${function}`.
- dagre auto-layout only when no node has a position; unpositioned nodes in a laid-out agent are placed near their source node or the viewport centre. A "Tidy layout" button runs a full layout.
- Custom node card: name, Start badge, End badge, first line of task, status badge slot (used by Issues 6 and 9).
- Custom edge showing the `function` name as a label.
- Add node (toolbar, placed at viewport centre), connect by dragging (creates edge via `connect` and selects it), delete node/edge (Delete key), reconnect edge target by dragging its end.
- Dragging writes positions to the store continuously; zundo is paused on drag start and resumed on drag stop.
- Deleting the initial node is blocked with a message unless another start is chosen.

**Acceptance criteria:**
- Every canvas action goes through a store operation; no graph state lives only in React Flow.
- Positions persist across save/reload.
- Adding a node to a laid-out agent does not move existing nodes.
- One drag produces exactly one history entry.

## 5. Side panel editors · P0

**Depends on:** 4

**Scope:**
- Nothing selected: agent settings: name, persona, voice_id, model, initial node. `voice_id` and `model` are dropdowns of known values plus a "custom" free-text option (a typo in `voice_id` gives a silent bot mid-call).
- Node: name (cascade rename, inline duplicate error), task messages list, role override, `end` toggle, "Set as start", pre/post actions (`tts_say` as a text field, other types as raw JSON).
- Edge: function name (inline validation: pattern and unique within the node; the store keeps the last valid value), description (multi-line, hint that it tells the LLM when to transition), target dropdown, collected-fields table (name, type, description, required) writing `properties`/`required`, raw JSON fallback.

**Acceptance criteria:**
- Every field in the schema is editable from the UI.
- Invalid raw JSON is rejected with a message and never written to the store.
- Typing a duplicate function or node name shows an error and never produces a duplicate in the store.

## 6. Validation errors · P0

**Depends on:** 5

**Scope:**
- Structured errors from `/composer/validate` (debounced on change, and on save), including the checks added in Issue 2.
- Error badges on nodes/edges (matched by `node` and `edge` fields, never by parsing messages) and a clickable problems list that selects the offending element. The list is built to also hold warnings (Issue 9).

**Acceptance criteria:**
- Each error type shows on the right node or edge and selecting it from the list focuses that element.
- Several simultaneous errors are all shown.
- Errors block the test call (Issue 7).

## 7. Test call panel · P0

**Depends on:** 2, 6

**Scope:**
- Call / Hang up using the Pipecat client and SmallWebRTC transport, with a fresh client per call.
- On Call: `/composer/health`, then validate, then connect with the current draft in the request data (ADR 0005). Show errors instead of connecting on failure. Testing does not require saving.
- Bot-ready timeout (10 to 15 s) with a message pointing to the backend terminal.
- Connection status, mic selector and mute, live transcript (user and bot turns).
- Bot-initiated hang-up (end node) returns the panel to idle.

**Acceptance criteria:**
- Edit a node, press Call, and the change is audible in the call with no manual steps and no save.
- Missing keys show a readable error before connecting; a bot crash shows the timeout message instead of an endless "Connecting".
- A second call works without reloading the page.
- A call that reaches an end node leaves the UI in a clean idle state.

## 8. Live transition events · P1

**Depends on:** 1, 7

**Scope:**
- In the edge handler in `builder.py`, send an RTVI server message `{type: "transition", from, function, to, args}` using the API confirmed in Issue 1 (ADR 0006).
- The client highlights `initial_node` on bot-ready (it already knows it; no server message needed).
- UI: highlight the active node, animate the edge taken, list transitions with collected args in the call panel.

**Acceptance criteria:**
- During a call the highlighted node always matches the backend log.
- After hang-up the transition list stays visible until the next call.

## 9. Authoring warnings · P1

**Depends on:** 6

**Scope:**
- Client-side, non-blocking warnings: unreachable nodes from start; non-end nodes without outgoing edges; end nodes with outgoing edges; empty edge descriptions; empty task messages; `required` entries not defined in `properties`.
- Warning badges on nodes/edges, shown in the problems list from Issue 6.
- If time is short, do unreachable nodes, dead ends and empty descriptions first.

**Acceptance criteria:**
- Each warning has a test fixture that triggers it.
- Warnings never block a test call.

## 10. Editor polish · P1

**Depends on:** 5

**Scope:**
- Undo/redo UI and keyboard shortcuts (zundo is already set up in Issues 3 and 4).
- Import/export agent JSON file; read-only JSON view of the current agent.
- Readable self-loops and multiple edges between the same pair of nodes (done in #4: lanes for parallel edges, self-loops round the right side).
- Back edges: an edge to a node above its source (a retry or "go back") is drawn as a plain curve and runs through the nodes in between. Route it like a self-loop: out of the bottom, round the right side of both nodes, into the top of the target, with lanes when several back edges share a path.
- P2 extras if time allows: editable JSON view (zod-parsed), node duplication, post-call summary.

**Acceptance criteria:**
- Undo after rename, delete and connect restores the previous agent exactly.
- A "clarify" self-loop and two parallel edges render without overlapping labels.
- In the example agent, an edge from `confirm` back to `greeting` does not cross `collect_details` or `offer_times`.

## 11. Demo agent, README and demo video · P0

**Depends on:** 7 (8 preferred)

**Rescheduled (2026-10-05):** done last, after Phase 2. The README gets written once for both phases, the video covers the editor, a call and the Composer, and the full demo agent may be generated by the Composer rather than built by hand. A short README fix for `make dev` went in with #13.

**Scope:**
- A healthcare scheduling agent built in the UI: greeting, identity check, book / reschedule / cancel, human handoff, clean endings, with well-written edge descriptions.
- README: setup (one command, Node version, Intel Mac note if the pins are committed), architecture overview (one process on 7860 + Vite), link to ADRs, what is deliberately out of scope, a note that collected args (PHI in production) appear in logs and transition events, Phase 2 notes. Fix the stray `\` after the Quickstart code fence.
- Short demo video (recorded by the user): edit, call, live highlighting, fix, call again.

**Acceptance criteria:**
- A reviewer with their own keys can go from clone to test call by following the README.

## 13. Reliable caller identity capture · P1

Added after the first test call misheard the caller's name (see the GitHub issue for the full text).

**Scope:**
- Set the speech-to-text language to English in `bot.py` (it is unset, so the service guesses per sentence).
- Spell-and-confirm pattern in the example agent (`prosper-scheduler.json`, the default a reviewer calls first): ask name, ask to spell it, read it back, correct on "no". The full demo agent (#11) reuses it.
- Manual call script in `docs/notes/call-tests.md`.
- Optional: speech-to-text check with 5 to 10 recorded clips.

**Acceptance criteria:**
- Transcripts never switch language during a call.
- A misheard name can be corrected by the caller, and the saved name matches what was spelled.
- `docs/notes/call-tests.md` exists and the demo agent passes it.

## Out of scope (state in README)

Auth, database, multi-user editing, versioning, code/custom-handler nodes, template variables injecting `state` into later prompts, custom WebRTC, PHI redaction.
