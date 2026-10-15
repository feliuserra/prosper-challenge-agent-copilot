# ADR 0014: Copilot service and UI

- **Status:** Accepted, 2026-10-05. Amended 2026-10-15 (#29, see the end): no chat yet; the spec step as built.
- **Date:** 2026-10-05

## Context

- The Copilot needs model keys, the agent files, the workspace and the text runner, all on the backend.
- The brief provides OpenAI and ElevenLabs keys, and a reviewer must be able to run the project with those two keys.
- The demo is live, so it cannot depend on a model choosing the right tool at the right moment.
- The editor already has three columns at 1024px wide: canvas, side panel and call panel ([ADR 0007](0007-frontend-stack.md), #7).

## Decision

1. **Backend service** in `backend/copilot/`, mounted under `/copilot` on the runner, like the agents API (one process, ADR 0005). Long steps (spec, build, test runs, audits) stream progress to the browser as server-sent events. Each request carries the editor's current draft (ADR 0012).
2. **OpenAI only,** with dated model versions pinned in one config: a larger model for writing specs and agents and for checking calls, a small one for simulated callers, and the judge chosen by calibration (ADR 0010, ADR 0011). Prompts live in their own files.
3. **A chat with a small toolset:** read the workspace, propose or edit the spec, build, edit the agent (ADR 0012), run tests, list and audit calls, reproduce an issue. The model decides when to use them during a conversation.
4. **Buttons call the same endpoints directly:** "Create from guidelines", "Run tests", "Audit calls", "Fix". The core flows work without the model choosing a tool, which keeps the demo reliable.
5. **Replies are cards,** not only text: requirements, client questions, tests, build progress, proposals with their diff and test results, issues with quotes.
6. **One right-hand column with tabs:** Copilot, Tests, Calls, Test call. It takes the call panel's place; the side panel (node and edge editor) stays.
7. **The conversation persists** in the workspace (ADR 0013).
8. **Live demo with a fallback.** Everything runs live, but every long step can switch to results cached during the rehearsal, so a slow model call never stalls the demo.
9. **Untrusted text stays data.** Transcripts, tickets and guidelines go into prompts delimited and labelled as data, never as instructions. The Copilot's tools can only read its own workspace.

## Alternatives considered

- **Copilot in the browser calling OpenAI:** the key would sit in the browser, and `make eval` would need a second implementation.
- **Claude or another provider for the Copilot:** may write better agents, but the reviewer would need another key. The brief allows it; we keep the setup to the keys provided.
- **A guided workflow without chat:** predictable, but less like the coding tools the brief points to, and worse at one-off requests ("add a test for a minor").
- **Separate pages for tests and calls:** cleaner, but results would no longer sit next to the graph they refer to.

## Consequences

- One process and one port as in Phase 1; the Vite proxy adds `/copilot`.
- At 1024px the canvas is narrow while the column is open, as with the call panel today.
- The Copilot's quality depends on prompts we tune on clinic A; the second clinic in ADR 0011 checks whether that generalises.

## Amendment (2026-10-15, #29)

Act 1 (#27 to #31) was cut to the minimum on 2026-10-15:

- **No chat yet** (points 3 and 7). Buttons call the endpoints (point 4 was already the demo path), and the Copilot panel is rebuilt from the workspace state, so there is no `chat.json`. If time is left after #31, one text box may send "change the spec" instructions and get a spec diff back, with no tools.
- **The model:** `gpt-4.1-2025-04-14` at temperature 0, pinned in `backend/copilot/config.py`, with strict structured outputs (a JSON schema per call). It goes through the runner's model client, so its requests land in the spend log as `copilot`. The prompts are in `backend/copilot/prompts/`, with the authoring guide that #30's build reads.
- **The spec step** (`POST /copilot/workspaces/{id}/spec`, `backend/copilot/spec.py`) makes one call per part, each checked by code and repaired on its own: requirements, set-aside sentences and client questions (sources must be quotes; every sentence of the guidelines is quoted or set aside with a reason; every question has a requirement for its default); the clinic configuration (the clinic loader decides, and each entry cites the requirements it carries); the tests (a plan whose coverage code checks, then the planned tests in batches of 5 written at the same time, each checked with `validate_tests`). The healthcare baseline (B1 to B4) is fixed text in code. The spec is written once, when every part is valid.
- **Streaming:** server-sent events over a POST (`event: part | repair | done | error`), read in the browser with `fetch`, since `EventSource` only does GET. A client that goes away cancels the step, and nothing is written.
- **Approved tests are locked** in the API: the only change a test accepts is its approval; a new spec step refuses to replace approved tests unless the request says so; every spec write is checked against the stored one.
- **What the Copilot reads** (point 9): its workspace, its prompts and the tool catalog. Guidelines go into prompts delimited as data. A test runs the spec step through the API on clinic-a's guidelines with an audit hook on file opens: nothing under `backend/eval/` and no clinic file is opened, and no reference test's id, title or judge rule reaches the model.

