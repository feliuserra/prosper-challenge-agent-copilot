# Architecture Decision Records

Each record explains one decision: the context, what we chose, what we rejected and what it costs. When a decision changes, amend the record or mark it "Superseded" and add a new one; do not rewrite history silently.

| # | Title | Status |
| --- | --- | --- |
| [0001](0001-agent-json-single-source-of-truth.md) | Agent JSON is the single source of truth | Accepted |
| [0002](0002-keep-schema-add-ui-positions.md) | Keep the existing schema; add only optional UI positions | Accepted |
| [0003](0003-node-name-is-identifier.md) | Node name is the identifier, renames cascade | Accepted |
| [0004](0004-validate-with-agent-builder.md) | Validate with the real AgentBuilder, add warnings on the client | Accepted |
| [0005](0005-draft-to-bot-at-connect-time.md) | Hand the current draft to the bot at connect time, one backend process | Accepted |
| [0006](0006-stream-transitions-over-rtvi.md) | Stream transitions to the UI over RTVI | Accepted |
| [0007](0007-frontend-stack.md) | Frontend stack | Accepted |
| [0008](0008-node-tools-from-a-mock-catalog.md) | Node tools from a fixed mock catalog (Phase 2) | Accepted, amends 0002 |
| [0009](0009-text-runner-for-simulated-calls.md) | Simulated calls with our own text runner (Phase 2) | Accepted |
| [0010](0010-test-format-and-grading.md) | Test format and grading (Phase 2) | Accepted |
| [0011](0011-trusting-the-tests.md) | Trusting the tests (Phase 2) | Accepted |
| [0012](0012-copilot-edits-through-operations.md) | The Copilot changes agents through validated operations (Phase 2) | Accepted |
| [0013](0013-workspaces-versions-and-calls.md) | Workspaces, versions and recorded calls (Phase 2) | Accepted |
| [0014](0014-copilot-service-and-ui.md) | Copilot service and UI (Phase 2) | Accepted |

Format: title, status, date, context, decision, alternatives considered, consequences.
