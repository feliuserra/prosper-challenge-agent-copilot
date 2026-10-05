# ADR 0014: Copilot service and UI

- **Status:** Accepted, 2026-10-05
- **Date:** 2026-10-05

## Context

- The Copilot needs model keys, the agent files, the workspace and the text runner, all on the backend.
- The brief provides OpenAI and ElevenLabs keys, and a reviewer must be able to run the project with those two keys.
- The demo is live, so it cannot depend on a model choosing the right tool at the right moment.
- The editor already has three columns at 1024px wide: canvas, side panel and call panel ([ADR 0007](0007-frontend-stack.md), #7).

## Decision

1. **Backend service** in `backend/copilot/`, mounted under `/copilot` on the runner, like the agents API (one process, ADR 0005). Long steps (spec, build, test runs, audits) stream progress to the browser as server-sent events.
2. **OpenAI only,** with dated model versions pinned in one config: a larger model for writing specs and agents and for checking calls, a small one for simulated callers, and the judge chosen by calibration (ADR 0010, ADR 0011). Prompts live in their own files.
3. **A chat with a small toolset:** read the workspace, propose or edit the spec, build, edit the agent (ADR 0012), run tests, list and audit calls, reproduce an issue. The model decides when to use them during a conversation.
4. **Buttons call the same endpoints directly:** "Create from guidelines", "Run tests", "Audit calls", "Fix". The core flows work without the model choosing a tool, which keeps the demo reliable.
5. **Replies are cards,** not only text: requirements, client questions, tests, build progress, proposals with their diff and test results, issues with quotes.
6. **One right-hand column with tabs:** Copilot, Tests, Calls, Test call. It takes the call panel's place; the side panel (node and edge editor) stays.
7. **Untrusted text stays data.** Transcripts, tickets and guidelines go into prompts delimited and labelled as data, never as instructions. The Copilot's tools can only read its own workspace.

## Alternatives considered

- **Copilot in the browser calling OpenAI:** the key would sit in the browser, and `make eval` would need a second implementation.
- **Claude or another provider for the Copilot:** may write better agents, but the reviewer would need another key. The brief allows it; we keep the setup to the keys provided.
- **A guided workflow without chat:** predictable, but less like the coding tools the brief points to, and worse at one-off requests ("add a test for a minor").
- **Separate pages for tests and calls:** cleaner, but results would no longer sit next to the graph they refer to.

## Consequences

- One process and one port as in Phase 1; the Vite proxy adds `/copilot`.
- At 1024px the canvas is narrow while the column is open, as with the call panel today.
- The Copilot's quality depends on prompts we tune on clinic A; the second clinic in ADR 0011 checks whether that generalises.
