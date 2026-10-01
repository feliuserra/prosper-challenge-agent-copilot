# Architecture Decision Records

Each record explains one decision: the context, what we chose, what we rejected and what it costs. When a decision changes, amend the record or mark it "Superseded" and add a new one; do not rewrite history silently.

| # | Title | Status |
| --- | --- | --- |
| [0001](0001-agent-json-single-source-of-truth.md) | Agent JSON is the single source of truth | Accepted |
| [0002](0002-keep-schema-add-ui-positions.md) | Keep the existing schema; add only optional UI positions | Accepted |
| [0003](0003-node-name-is-identifier.md) | Node name is the identifier, renames cascade | Accepted |
| [0004](0004-validate-with-agent-builder.md) | Validate with the real AgentBuilder, add warnings on the client | Accepted |
| [0005](0005-draft-to-bot-at-connect-time.md) | Hand the current draft to the bot at connect time, one backend process | Proposed |
| [0006](0006-stream-transitions-over-rtvi.md) | Stream transitions to the UI over RTVI | Accepted |
| [0007](0007-frontend-stack.md) | Frontend stack | Accepted |

Format: title, status, date, context, decision, alternatives considered, consequences.
