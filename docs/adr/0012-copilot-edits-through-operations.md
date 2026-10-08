# ADR 0012: The Copilot changes agents through validated operations

- **Status:** Accepted, 2026-10-05. Amended 2026-10-08 by [ADR 0015](0015-debugging-by-cause.md): operations cite requirements; candidate changes are checked by turn replay before full reruns.
- **Date:** 2026-10-05

## Context

- The Copilot creates agents and later changes them to fix failing tests and production issues. A human reviews every change before it applies.
- A review is only fast if the change is small and exact: a fix to the cancellation node should not reword the greeting.
- The editor already changes agents through named store operations with rules (renames cascade to edge targets and `initial_node`, deleting a node removes its incoming edges, function names are unique per node). See [ADR 0001](0001-agent-json-single-source-of-truth.md) and [ADR 0003](0003-node-name-is-identifier.md).
- `make eval` and the loop until green run without a browser, so the operations must also exist in Python.

## Decision

1. **Operations, as model tools:** `add_node`, `update_node`, `rename_node`, `delete_node`, `add_edge`, `update_edge`, `delete_edge`, `set_initial_node`, `set_tools`, `update_agent`, in `backend/copilot/ops.py`, with the same rules as the editor store.
2. **Creation uses operations too.** A new agent is built from an empty one. The operations stream to the UI, so the graph visibly builds itself.
3. **Applied to a copy, then validated** with `validate_agent`. Errors go back to the model for at most 2 more tries. An agent with errors is never written or proposed.
4. **Loop until green:** after a valid change, run the affected tests, then all of them; send failures with their evidence and their diagnosis (ADR 0015) back; at most 3 rounds, counting full reruns.
5. **One proposal:** the operations, the resulting agent, a short rationale and test results before and after. The UI shows it as a diff on the canvas. Accept applies it as one undo step and saves a version (ADR 0013); Reject discards it.
6. **The model is asked for the smallest change** that makes the failing tests pass. The diff shows anything beyond that.
7. **It works on what the user sees.** Each Copilot request carries the editor's current draft, as test calls do (ADR 0005). While the Copilot builds or fixes, the canvas and side panel are read-only with a Stop button, and a proposal records the draft it started from: Accept is refused if the draft has changed since.
8. **Shared test cases:** `backend/tests/fixtures/ops/` holds cases (agent, operations, expected agent or error) that pytest runs against the Python operations and Vitest runs against the store, so the two implementations cannot drift apart unnoticed.
9. **Operations cite requirements** (ADR 0015). Operations that add or change prompts, edges or tools name the requirement ids they serve; nodes, and the agent for its persona, keep them in an optional `requirements` list. Renames and deletes carry the list with the node, so the requirement map stays right after edits in the editor.
10. **Candidates before reruns** (ADR 0015). For each failure the model proposes 2 to 3 candidate changes. Each is checked by replaying the failing turn; only the best goes on to a full rerun.

## Alternatives considered

- **Full rewrite:** the model returns the whole agent. Simplest, but models reword parts they were not asked to change, so diffs get noisy and review slows down.
- **Rewrite to create, operations to edit:** reasonable, but it loses the live build on the canvas and needs two generation paths.
- **JSON Patch:** precise, but low level: the model has to get array indexes and paths right, and patches carry none of the rename and delete rules.

## Consequences

- Small, reviewable diffs, and the graph building live during the demo.
- The editing rules exist twice, in TypeScript and in Python. The shared cases keep them in step; the Python side implements only what the Copilot needs.
- The client-side warnings from #9 (unreachable nodes, dead ends) are not part of the validation loop. Tests cover behaviour; a Python port can come later if generated agents show those problems.
