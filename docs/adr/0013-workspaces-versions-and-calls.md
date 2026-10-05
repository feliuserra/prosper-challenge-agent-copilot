# ADR 0013: Workspaces, versions and recorded calls

- **Status:** Accepted, 2026-10-05
- **Date:** 2026-10-05

## Context

- Each client's agent now comes with guidelines, requirements, client questions, tests, calls and tickets, and the Copilot needs all of them to work.
- To show a fix worked, a call or test result must say which version of the agent it ran on.
- Phase 1 stores agents as `backend/agents/<id>.json`, served by the `/composer` API ([ADR 0005](0005-draft-to-bot-at-connect-time.md)). Its tests and the editor depend on that layout.
- Test calls from the editor can run an unsaved draft.

## Decision

1. **One workspace per agent,** next to the agent file and optional: `backend/workspaces/<agent-id>/`
   - `guidelines.md`: the client's document, pasted in;
   - `spec.json`: requirements, client questions and tests, each test `draft` or `approved`;
   - `versions/`: numbered snapshots;
   - `calls/`: call records;
   - `tickets/`: client tickets.
   The agent itself stays in `backend/agents/<id>.json`; the Phase 1 API does not change.
2. **Versions:** a snapshot on each save from the editor and each accepted Copilot change, with its source (`editor` or `copilot`) and a message. An unchanged agent adds no version.
3. **Calls are recorded by the bot** when the call ends: a copy of the agent that ran and its hash (and the version, if it matches a saved one), the transcript with the user's words as speech-to-text heard them, transitions, tool calls with results, start and end times and how it ended. Production would record on the server too.
4. **One call format** for live test calls, simulated calls and mock production calls, told apart by `source`.
5. **The reference suite is not in a workspace.** It lives in `backend/eval/`, which the Copilot cannot read (ADR 0011). Demo seed data (the weak agent, mock calls, tickets) lives in `backend/demo/` and is copied into a workspace by `make demo-reset`.
6. `backend/workspaces/` is gitignored.

## Alternatives considered

- **Move agents into folders** (`agents/<id>/agent.json`): tidier on disk, but it breaks the Phase 1 API and tests for no real gain.
- **Store the spec inside the agent JSON:** one file, but the runtime file grows, and every model that reads or writes the agent has to carry tests and calls along.
- **Record calls in the browser:** the panel already has the transcript, but the browser does not see tool results on the server, and production calls do not come from a browser.
- **A database:** not needed for a single-user local tool.

## Consequences

- Plain files that are easy to inspect, diff and reset before a demo.
- Call records contain what callers said, which in production is PHI, and the call checker sends transcripts to OpenAI. Fine for mock data; production would need redaction and a BAA. Stated in the README.
- Snapshots of an unsaved draft are kept inside the call record rather than as versions, so the version list only holds what someone saved or accepted.
