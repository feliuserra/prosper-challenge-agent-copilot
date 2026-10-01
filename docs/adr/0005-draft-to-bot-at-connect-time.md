# ADR 0005: Hand the current draft to the bot at connect time, one backend process

- **Status:** Proposed. Becomes Accepted (or amended) when Issue 1 proves a call end to end.
- **Date:** 2026-09-29

## Context

- The bot builds the agent inside `bot()`, on every connection. Changing what `bot()` builds changes the agent with no restart.
- The UI needs the next test call to use the agent being edited, ideally the unsaved draft, so testing does not force a save.
- The editor also needs a small agents API (list, get, save, validate, health).
- In pipecat-ai 1.4.0 the runner's FastAPI app is importable and documented as extensible (`pipecat/runner/run.py:168-181`), and it forwards request data to the bot as `runner_args.body`, both from `POST /api/offer` (`run.py:811-815`) and from `POST /start` (`run.py:629, 642, 697`).

## Decision

1. **One backend process.** The agents API is registered on the runner's app, under a `/composer/` prefix to avoid the runner's own routes (`/start`, `/status`, `/api/offer`, `/sessions/...`, `/client`):
   `GET /composer/agents`, `GET /composer/agents/{name}`, `PUT /composer/agents/{name}`, `POST /composer/validate`, `GET /composer/health`.
   Agents are JSON files in `backend/agents/`.
2. **Option A: the draft travels with the connect request.** The client sends the agent in the connect request data; `bot()` reads it from `runner_args.body`, re-validates it and builds from it.
   - No agent in the body: use the example agent.
   - Invalid agent in the body: log the errors and end the call. Never fall back silently to another agent.
3. **Option B (fallback if Issue 1 shows the body cannot carry the draft):** `POST /composer/activate` validates the draft and writes `backend/agents/.active.json` atomically (temp file + `os.replace`); `bot()` reads it on connect.

## Alternatives considered

- **Separate FastAPI process for the agents API.** The original plan, based on the assumption that extending the runner is awkward. It is not, and a second process adds a second port, a CORS or proxy rule, and more Makefile work.
- **Activate a saved agent by name.** Forces a save before every test and a save/activate/connect ordering the client must get right.
- **A database.** Unnecessary for a single-user local tool.

## Consequences

- Option A has no shared file and no ordering between save and connect, and allows several drafts to be tested at once in different tabs.
- The agents API depends on the Pipecat dev runner. Pipecat Cloud would not host these routes, which is fine: the editor is a local tool, and production would serve agents from real storage anyway.
- If Pipecat changes how the runner exposes `app` or `body`, the handover breaks. Issue 1 records the exact file and line references so the next upgrade can be checked quickly.
- Option B, if needed, allows one active agent at a time and needs the atomic write.
- Agent files are easy to diff and review in both cases.
