# ADR 0002: Keep the existing schema; add only optional UI positions

- **Status:** Accepted. Amended by [ADR 0008](0008-node-tools-from-a-mock-catalog.md) (Phase 2): nodes gain an optional `tools` list.
- **Date:** 2026-09-29

## Context

The challenge allows changing the node format. The existing schema (`backend/agent_builder/schema.py`) already models transitions as explicit edges with a target, a description and an argument schema, and stays close to Pipecat Flows vocabulary (`role_message`, `task_messages`, `pre_actions`, `post_actions`). It has no layout data.

`AgentConfig.from_dict`, `Node.from_dict` and `Edge.from_dict` read fields with `.get()`, so unknown keys are ignored by the backend.

## Decision

Keep the schema unchanged. Add an optional `ui: {x, y}` field per node. The backend ignores it, so no backend change is needed. Missing positions are filled by auto-layout. The frontend preserves keys it does not model (loose zod objects, actions as opaque records), so a load/save round trip never loses data.

## Alternatives considered

- **A new, richer format** (conditions, variables, typed actions). More expressive, but it means rewriting the builder, and it gives the Composer a larger surface to get wrong.
- **Layout in a separate file.** Keeps the agent file pure, but two files per agent drift apart (renames, deletes, Composer output that only writes one of them).

## Consequences

- The runtime is unchanged and fully compatible with `example_flow.json`.
- Composer output without positions still renders.
- The Composer has to ignore or preserve `ui` fields. That is one well-named optional field, cheap to explain in a prompt.
- Limitations of the format stay: no templating of collected `state` into later prompts, no conditional logic outside the LLM. Documented as out of scope in the README.
