# Handoff: Prosper challenge (Agent Composer), Phase 1 UI

Context for a new session. Read it fully before writing code. The build plan is in [`PLAN.md`](../PLAN.md) and the design decisions are in [`docs/adr/`](adr/README.md). This file holds the context those two do not.

Facts marked **VERIFIED** were checked against the repo and the installed packages (pipecat-ai 1.4.0, pipecat-ai-flows 1.3.0) on 2026-09-29. Facts marked **VERIFY** are still assumptions and are covered by Issue 1.

**How to use this document**
1. Read the ADRs (`docs/adr/`), then work through `PLAN.md` issue by issue, in order.
2. One branch/PR per issue, referencing the GitHub issue number (issues #1 to #11 on the fork match the numbering in `PLAN.md`).
3. If Issue 1 disproves an assumption, update the affected ADR (amend it, or mark it "Superseded" and add a new one) before building on it.

Working style: the user (Feliu) is a strong Python developer and wants direct answers with explicit reasoning and trade-offs. Explain why each decision is made. Avoid overengineering. In documents written for the repo, keep a plain voice and avoid em-dashes.

---

## 1. The task

Build a UI for creating and editing voice agents, where an agent is a graph of nodes (conversation steps) and edges (transitions). The user must be able to edit the graph and place a test call from the UI, similar to ElevenLabs Agents or Retell AI. Changing the node format or backend is allowed if justified.

- **Phase 1 (now):** graph editor + test call.
- **Phase 2 (later):** an AI Composer that generates and edits agents from natural language. Phase 1 decisions should keep the agent JSON clean and easy for an LLM to read and write.
- Domain: voice AI for healthcare scheduling.

Repo: `feliuserra/prosper-challenge-agent-copilot` (local path: `~/Desktop/work/prosper-challenge-agent-copilot`). Run with `make install` then `make run`, open `http://localhost:7860/client`.

## 2. Local environment (VERIFIED)

- The development machine is an **Intel Mac (x86_64)**. Several wheels (onnxruntime, numba, llvmlite, cryptography, opencv-python) no longer ship for it, so `backend/pyproject.toml` has uncommitted `override-dependencies` / `constraint-dependencies` pins and a matching `uv.lock` change. The same edit commented out `package = false`; that line should be restored (harmless today because there is no `[build-system]`, but it documents intent). The user will decide when to commit this. Do not commit it as part of an issue.
- Node.js 24 (official .pkg, `/usr/local/bin`) and `gh` (in `~/.local/bin`) are installed; Homebrew and nvm are not. The repo is a **fork** of `Prosper-Technologies/prosper-challenge-agent-copilot`: always pass `--repo feliuserra/prosper-challenge-agent-copilot` to `gh` (also set with `gh repo set-default`) so issues and PRs never land upstream.
- `backend/.env` exists with the keys. Never read or print it.
- No test runner is installed in the backend venv (no pytest). Adding one as a uv dev dependency touches `pyproject.toml`, so coordinate with the uncommitted pins above.
- `jsonschema` is not installed. See ADR 0004 for why we do not need it.

## 3. What the repo contains (VERIFIED from source)

- `backend/bot.py`: Pipecat pipeline (SmallWebRTC transport, ElevenLabs realtime STT + TTS, OpenAI LLM, Silero VAD) driven by a Pipecat Flows `FlowManager`. Loads the agent from a hard-coded `AGENT_FLOW = backend/example_flow.json`. **The agent is loaded inside `bot()`, i.e. on every client connection**, so changing what `bot()` loads changes the agent with no restart.
- `backend/agent_builder/schema.py`: dataclasses
  - `AgentConfig`: `name`, `initial_node`, `nodes`, `persona` (global role message), `voice_id` (default ElevenLabs "Rachel"), `model` (default `gpt-4o`).
  - `Node`: `name`, `task_messages` (list), `role_message` (optional persona override), `edges`, `pre_actions`, `post_actions`, `end` (bool; terminal node ends the call).
  - `Edge`: `function` (tool name the LLM calls), `description` (when to call it, **required key**), `target` (node **name**), `properties` (JSON-schema properties to collect), `required`.
  - `from_dict` uses `.get()` for optional fields, so **unknown keys are ignored**. Missing required keys (`name`, `initial_node`, `nodes`, `function`, `description`, `target`) raise `KeyError`, not `ValueError`.
- `backend/agent_builder/builder.py`: `AgentBuilder`
  - Validation only checks: at least one node, `initial_node` exists, every edge target exists. It **stops at the first problem** and raises a single `ValueError` with a plain string. At load time that currently means a crashed call.
  - The constructor only parses and validates. It has no side effects and needs no pipeline or `FlowManager`, so it can run inside an HTTP handler.
  - Each edge becomes a `FlowsFunctionSchema`. Its handler does `flow_manager.state.update(args)`, logs `[function] -> target | collected: args`, and returns the next node. **Nodes are built lazily on transition.**
  - A node with `end: true` and no explicit `post_actions` gets `end_conversation` as a post action.
  - Context strategy is not set, so Pipecat Flows uses its default, `APPEND` (`pipecat_flows/manager.py:140`). Collected `state` is never injected into later prompts.
- `backend/example_flow.json`: sample clinic-scheduler agent. `task_messages` is a list of `{"role": "developer", "content": "..."}`. It has no `pre_actions` or `post_actions`, so the action shape still comes from Pipecat Flows (`{"type": "tts_say", "text": ...}`, `{"type": "end_conversation"}`, ...). Treat actions as opaque records in the UI.
- Keys: `bot.py` loads `.env` from **`backend/.env`**, needing `ELEVENLABS_API_KEY` and `OPENAI_API_KEY`. Keys are company-provided and usage is visible to them. `.env` must stay gitignored (it is).
- The prebuilt Pipecat browser client is `pipecat-ai-prebuilt` 1.0.3 and reported RTVI Client v1.12.0.

### Pipecat runner (VERIFIED, pipecat-ai 1.4.0)
- The runner's FastAPI app is importable and **documented as extensible**: `from pipecat.runner.run import app` and add routes before `main()` (`pipecat/runner/run.py:168-181`). `_get_bot_module()` uses the `__main__` module, so `bot.py` is not imported twice and routes are not registered twice (`run.py:386-395`).
- Existing routes to avoid colliding with: `/`, `/client`, `/status`, `/start`, `/api/offer` (POST, PATCH), `/sessions/{session_id}/...`, `/files/...`.
- **Request data reaches `bot()`:** `POST /api/offer` passes `request.request_data` as `runner_args.body` (`run.py:811-815`). `POST /start` stores `request_data["body"]` per session and passes it as `runner_args.body` (`run.py:629, 642, 697`), and the client then sends its offer to `/sessions/{session_id}/api/offer`. Which of these the client-js `startBotAndConnect` uses, and how it names the payload field, is **VERIFY** (Issue 1).
- **RTVI is on by default:** `PipelineWorker(..., enable_rtvi=True)` adds an `RTVIProcessor` and observer automatically (`pipecat/pipeline/worker.py:237`). `RTVIServerMessageFrame` exists (`pipecat/processors/frameworks/rtvi/frames.py:38`), and `flow_manager.worker` exposes the worker (`pipecat_flows/manager.py:251`). Pushing that frame from an edge handler and receiving it in client-js is **VERIFY** (Issue 1).

## 4. Known gotchas

**Runtime and call**
- **One backend process, one port.** Because the runner app accepts custom routes (above), the agents API lives on the runner (port 7860) under a `/composer/` prefix (ADR 0005). Vite proxies `/composer`, `/start`, `/sessions` and `/api` to 7860. This removes the cross-port CORS problem.
- Mic requires localhost or HTTPS; browsers block audio playback until a user click.
- Pipecat renames APIs often (`bot.py` uses `PipelineWorker`/`WorkerRunner`). Read the installed package source rather than blog examples. Match client-js versions to the server's RTVI version.
- **Missing keys or a bot crash hang the client.** The runner answers the WebRTC offer before the bot runs, so the client connects but never receives bot-ready and sits at "Connecting". Check the terminal first. Issue 7 adds a `/composer/health` check before connecting and a bot-ready timeout.
- **Nodes are built lazily.** Anything the LLM API or Pipecat Flows rejects (invalid or duplicate function names, malformed `properties`) fails only when the call enters that node, i.e. mid-conversation, not at load. These must be validation errors, not warnings (ADR 0004).
- **The bot must re-validate the draft it receives.** The client validates before connecting, but `bot()` must not trust the request body. If the draft is invalid, log the errors and end the call. Do not silently fall back to the example agent in that case (the author would hear the wrong agent). Fall back to the example only when no agent was sent at all.
- **Reusing a Pipecat client after disconnect** is a common source of stale-state bugs. Create a fresh client per call. The bot can also end the call itself (end node); the UI must handle that as a normal hang-up.
- **Collected args appear in the backend log** (and in transition events, Issue 8). In a real deployment these are PHI (names, dates of birth). Fine for the demo; say so in the README.
- **Makefile and background jobs.** make runs each recipe line in its own shell, so `trap 'kill 0' EXIT` only works if the recipe runs in one shell: use `.ONESHELL:` or put the whole command on one line joined with `;`.

**Editor**
- **zod strips unknown keys by default.** Use loose objects (`.passthrough()` in zod 3, `.loose()` in zod 4) and treat actions as opaque records, or a load/save round trip silently drops fields.
- **React Flow ids.** Node id = node name, so renaming changes the id. Edges have no id in the schema; derive it as `${source}::${function}`. This is only unique if function names are unique within a node **at all times**, including while the user is typing. So `updateEdge` and `renameNode` **reject** duplicates (the field shows the error and the store keeps the old value); they never write a duplicate and flag it later. Selection lives in the store, and rename operations update it, otherwise renaming deselects the element being edited.
- **Dragging vs. undo.** React Flow is controlled, so it needs positions on every drag frame. Write positions to the store continuously (cheap at this size) and handle undo at drag boundaries: pause zundo on drag start, resume and record one step on drag stop. zundo is partialized to the agent only, so selection and other UI state never enter history. This is decided in Issues 3 and 4, not retrofitted in Issue 10.
- **Auto-layout with partial positions.** Run dagre only when no node has a position. Otherwise place unpositioned nodes near their source node or the viewport centre, so a node added later (by hand or by the Composer) does not reshuffle the user's layout.
- **Validation errors are structured.** `/composer/validate` returns every error at once, each with `node` and optionally `edge` (function name), so the UI can place badges (ADR 0004). Do not parse error strings.

## 5. Changes from the original handoff

Recorded so the reasoning is not lost:
- `create_issues.py` never existed: issues were created from `PLAN.md` as GitHub issues #1 to #11 on the fork.
- ADR 0005 now prefers Option A **and** a single process, because the runner app is extensible and already forwards request data to `bot()`. Status is "Proposed" until Issue 1 proves a call end to end.
- ADR 0004 now requires the builder to collect all errors as structured records, not raise on the first one. `properties` is checked by a small hand-written check rather than a new `jsonschema` dependency.
- Duplicate function names are rejected at edit time, not only flagged, to keep React Flow edge ids unique.
- The bot re-validates the received draft and does not fall back silently on an invalid one.
- Makefile background jobs need `.ONESHELL:`.
- Environment prerequisites (Node, `.env`, Intel Mac pins) added as section 2.
- The demo video in Issue 11 is recorded by the user.
- Stray `\` after a code fence in `README.md`: fixed in Issue 11.
