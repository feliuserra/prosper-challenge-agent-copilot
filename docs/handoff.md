# Handoff: Prosper challenge (Agent Composer), Phase 1 UI

Context for a new session. Read it fully before writing code. The build plan is in [`PLAN.md`](../PLAN.md), the design decisions are in [`docs/adr/`](adr/README.md), and what the Pipecat runtime actually does (with file:line references into the installed packages) is in [`docs/notes/runtime.md`](notes/runtime.md). This file holds the context those do not.

Working style: the user (Feliu) is a strong Python developer and wants direct answers with explicit reasoning and trade-offs. Explain why each decision is made. Avoid overengineering. In documents written for the repo, keep a plain voice and avoid em-dashes.

---

## 0. Status (updated 2026-10-02)

| Issue | State | PR |
| --- | --- | --- |
| #1 Runtime spike | Merged | #14 |
| (Intel Mac dependency pins) | Merged | #15 |
| #2 Agents API + draft handover | Merged | #16 |
| #3 Frontend skeleton, schema, store | Merged | #17 |
| **#4 Graph canvas** | Built and committed on `issue-4-graph-canvas`; not pushed, no PR yet | |
| #5 to #11, #13 | Open | |

**Next step:** push #4 and open its PR once the user agrees, then #5 (side panel editors, `PLAN.md` section 5). The panel edits the selection the canvas already sets in the store.

**How we work through an issue:**
1. Branch `issue-N-short-name` from `main`, one branch and PR per issue, PR body ends with `Closes #N`.
2. Build, run `make test`, and verify in the real app (see "Testing without disturbing the user" below).
3. Commit locally and summarise for the user. **Ask before pushing, opening a PR or merging.** Once the user says "merge", merge with `gh pr merge <n> --merge --delete-branch`, then update local `main`, delete the local branch and create the next one.
4. Things that need a mic (a real call) are checked by the user: give them exact steps and what to look for in the terminal and the browser DevTools console (Cmd+Option+J). The user runs `make dev` in a terminal outside the app, so its output is not readable from the session; ask them to paste it.

## 1. The task

Build a UI for creating and editing voice agents, where an agent is a graph of nodes (conversation steps) and edges (transitions). The user must be able to edit the graph and place a test call from the UI, similar to ElevenLabs Agents or Retell AI. Changing the node format or backend is allowed if justified.

- **Phase 1 (now):** graph editor + test call.
- **Phase 2 (later):** an AI Composer that generates and edits agents from natural language. Phase 1 decisions should keep the agent JSON clean and easy for an LLM to read and write.
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
| `make test` | pytest (backend, 44 tests) + Vitest (frontend, 62 tests) |

**Testing without disturbing the user.** The user often has `make dev` running on 7860/5173. Do not kill their processes. Run a second backend and frontend on spare ports instead:

```bash
cd backend && .venv/bin/python bot.py --port 7861            # background
cd frontend && RUNNER_URL=http://localhost:7861 npx vite --port 5174 --strictPort   # background
```

Then drive `http://localhost:5174` in the built-in browser pane. Its mic is blocked, which is fine for everything except hearing the bot. In dev builds the store is on `window.agentStore` (e.g. `window.agentStore.getState().moveNode("greeting", {x: 0, y: 0})`). `window.prompt`/`confirm` can be stubbed from JS to drive the "New" buttons. Afterwards stop both servers and delete any agent files the test created in `backend/agents/`.

## 3. What the repo contains now

### Backend (`backend/`)
- `bot.py`: Pipecat pipeline (SmallWebRTC, ElevenLabs realtime STT + TTS, OpenAI LLM, Silero VAD) driven by a Pipecat Flows `FlowManager`. It mounts the agents API on the runner app and, in `bot()`, builds the agent from `runner_args.body["agent"]`:
  - no agent sent (e.g. the prebuilt `/client`): uses `agents/prosper-scheduler.json`;
  - invalid agent: logs every error and calls `reject_call()`, which runs an empty pipeline, sends an RTVI error "Invalid agent: ..." once the client is ready, and ends the call. It never falls back to another agent. Closing the WebRTC connection directly does not work (the client is still connecting and never notices); see `docs/notes/runtime.md` section 4.
- `composer_api.py`: router factory `make_router(agents_dir)` under `/composer`: `GET /agents` (`{agents: [{id, name}]}`), `GET|PUT /agents/{id}`, `POST /validate` (`{errors: [...]}`, always 200), `GET /health` (`{ok, missing_keys}`, from the process env, never values). The id is the file stem, a lowercase slug `[a-z0-9][a-z0-9_-]{0,63}`, separate from the agent's display name. `PUT` validates (422 with every error), writes atomically and stores the JSON exactly as received.
- `agent_builder/validation.py`: `validate_agent(dict) -> list[ValidationIssue]` with `{message, node, edge}` records (`edge` is the function name). Runs on the raw dict, so missing keys and wrong types are errors, not `KeyError`. Checks: name, nodes, `initial_node`, unique node names, edge targets, function names (`fullmatch [a-zA-Z0-9_-]{1,64}`), unique function names per node, `properties` values are objects with a known `type`, `required` is a list of strings, field types, task messages have a `role`, actions have a `type`. Unknown keys are allowed.
- `agent_builder/builder.py`: `AgentBuilder.from_dict` validates and raises `ValidationError(ValueError)` carrying all records; the constructor validates `asdict(config)`. Each edge handler updates `flow_manager.state`, logs, and queues an RTVI server message `{type: "transition", from, function, to, args}` (Issue #8 builds the UI on it). Nodes are built lazily on transition.
- `agent_builder/schema.py`: dataclasses `AgentConfig` (`name`, `initial_node`, `nodes`, `persona`, `voice_id`, `model`), `Node` (`name`, `task_messages`, `role_message`, `edges`, `pre_actions`, `post_actions`, `end`), `Edge` (`function`, `description`, `target`, `properties`, `required`). Unchanged from the starter.
- `agents/prosper-scheduler.json`: the example and default agent (was `example_flow.json`). Hand-formatted; the first save from the editor reflows its whitespace (values and key order unchanged).
- `tests/`: pytest for validation and the API (TestClient on a bare FastAPI app with a temp dir, no voice stack). Dev deps: `pytest`, `httpx2` (Starlette's TestClient deprecates `httpx`).

### Frontend (`frontend/`)
- Vite 8 + React 19 + TypeScript 7, zustand 5 + zundo 2, zod 4, Vitest 5. `@pipecat-ai/client-js` 1.13.1 and `@pipecat-ai/small-webrtc-transport` 1.10.8 pinned exactly. `@pipecat-ai/client-react` 1.8.2 is compatible but not installed (add it in #7 if useful). Node 24 in `.nvmrc`.
- `vite.config.ts`: proxies `/start`, `/sessions`, `/api`, `/composer` to the runner (`RUNNER_URL`, default `http://localhost:7860`).
- `src/agent/schema.ts`: zod mirror of the dataclasses. Loose objects, actions as opaque records, optional `ui: {x, y}` per node, **no defaults**. `api.getAgent` uses zod only to check the shape and returns the original object, so a load/save round trip keeps values and key order.
- `src/agent/names.ts`: `FUNCTION_NAME_RE`, `sanitizeFunctionName`, `uniqueName`, `placeholderFunctionName` (`go_to_<target>`, `_2`, `_3`... within 64 chars), `agentIdFor` (slug for new agents). `src/agent/templates.ts`: `blankAgent(name)` (one `start` node at 0,0), `EXAMPLE_AGENT_ID`.
- `src/store/agentStore.ts`: `useAgentStore` with `agent`, `agentId`, `savedJson`, `selection` (`{kind: "node", name}` or `{kind: "edge", source, function}`) and named operations: `open`, `markSaved`, `select`, `addNode(position?)`, `deleteNode` (refuses the start node; removes incoming edges), `renameNode` (cascades to targets, `initial_node`, selection; rejects duplicates and empty), `updateNode`, `connect(source, target)` (placeholder name, selects the edge), `updateEdge` (rejects duplicate function names; follows a rename with the selection), `deleteEdge`, `setInitialNode`, `moveNode` (writes `ui`), `updateAgent`. Rejectable operations return `{ok: false, error}` and leave the store unchanged. `selectIsDirty(state)` compares with `savedJson`.
- zundo: `useAgentStore.temporal`, partialized to `{agent}`, `equality` on the agent reference, so selection changes are not recorded. `open()` clears history. Drags are one history entry each (see section 4).
- `src/agent/layout.ts`: `autoLayout` (dagre, top to bottom, integer positions), `placeMissing` (below a positioned source node, else a fallback; never moves positioned nodes), `withPositions` (full layout only when no node has a position), `freeSpot`, `nearestFreeSpot`, `NODE_WIDTH`. The store uses it in `open` (fills missing positions without marking the agent unsaved, since they are deterministic), in `addNode()` without a position, and in `tidyLayout()`.
- `src/api.ts`: `listAgents`, `getAgent`, `saveAgent` (returns validation errors on 422), `validateAgent`.
- `src/components/`: `Toolbar` (agent picker, New blank, New from example, Save, Cmd/Ctrl+S, unsaved indicator, leave-page warning), `CallButton` (minimal test call with the current draft; #7 replaces it). The read-only `Outline` was removed in #4.
- `src/canvas/` (#4, `@xyflow/react` 12 and `@dagrejs/dagre`, the maintained fork of `dagre`): `Canvas.tsx` (controlled React Flow, remounted per agent id; Add node and Tidy layout panel; minimap, controls; notice panel), `derive.ts` (store to React Flow: `toFlowNodes`, `toFlowEdges`, `edgeId`/`parseEdgeId`, `NodeStatus` type for the badge slot #6 and #9 fill), `changes.ts` (React Flow change lists to store operations: positions, selection, measurements), `NodeCard.tsx`, `FunctionEdge.tsx` (label is a button that selects the edge) with its shapes in `edgePath.ts`: edges between the same two nodes get lanes that bow the curves apart and stack the labels, and a self-loop goes round the right side of its node. A lane-0 edge is exactly React Flow's default bezier (tested).
- Reconnecting: only the selected edge has a reconnect knob (a blue circle over its arrowhead), and `elevateEdgesOnSelect` draws it above other edges ending at the same handle. Click an edge, then drag the knob to another node.
- Single selection only: multi-select and box select are off, matching the store's `selection`.
- Tests: `names.test.ts`, `schema.test.ts`, `agentStore.test.ts`, `layout.test.ts`, `derive.test.ts`, `changes.test.ts`, `edgePath.test.ts` (62 in total).

## 4. Known gotchas

**Runtime and call**
- **The draft must be sent as `requestData.body`.** `startBotAndConnect({endpoint: "/start", requestData: {body: {agent}}})`. The runner keeps only `body` between `/start` and the offer. The agent's loose TS type needs a documented cast to client-js's `Serializable` (see `CallButton.tsx`).
- Mic requires localhost or HTTPS; browsers block audio playback until a user click.
- Pipecat renames APIs often. Read the installed package source rather than blog examples.
- **Missing keys or a bot crash hang the client** at "Connecting" (the runner answers the offer before the bot runs). Check the terminal first. #7 adds a `/composer/health` check before connecting and a bot-ready timeout.
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
- **Validation errors are structured.** Use `node`/`edge` from `/composer/validate` to place badges (#6). Do not parse error strings.
- **Keep zod objects loose and add no defaults**, or a round trip drops or adds fields.

## 5. Open items not tracked in an issue yet

- **Slow end of turn.** Smart Turn v3 marks short answers ("Book.") as incomplete, so the bot waits for the 3 s silence fallback (`End of Turn complete due to stop_secs. Silence in ms: 3000`). Tunable via `LLMUserAggregatorParams`. The user was asked whether to open an issue and has not answered.
- **Agents saved from the editor** land in `backend/agents/` as untracked files. Decide before the demo whether to commit or gitignore them (the example must stay tracked).
- **STT language** is unset, so names come out in other scripts (Cyrillic, Chinese). Tracked in #13.
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
- Makefile background jobs use a single-shell recipe; `.ONESHELL:` does not work with make 3.81 (#2).
- The demo video in #11 is recorded by the user.
- Stray `\` after a code fence in `README.md`: fix in #11.
