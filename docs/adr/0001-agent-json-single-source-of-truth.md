# ADR 0001: Agent JSON is the single source of truth

- **Status:** Accepted
- **Date:** 2026-09-29

## Context

A graph editor has two representations of the same thing: the agent definition the runtime consumes, and the nodes and edges the canvas renders. Keeping two copies in sync is the most common source of bugs in editors like this. Phase 2 adds an AI Composer that will produce and modify agents, and import/export adds another way for the agent to change from outside the canvas.

## Decision

The frontend store holds exactly one `AgentConfig`. React Flow nodes and edges are derived from it on render. All changes go through named store operations (`addNode`, `deleteNode`, `renameNode`, `updateNode`, `connect`, `updateEdge`, `deleteEdge`, `setInitialNode`, `moveNode`, `updateAgent`).

Operations that would break an invariant (duplicate node name, duplicate function name within a node) are rejected and leave the store unchanged, so the store never holds an agent the canvas cannot render.

Drag positions are written to the store on every frame. Undo history is recorded only at drag boundaries (see ADR 0007 and Issue 4).

## Alternatives considered

- **React Flow's internal state as primary, serialise on save.** Simpler at first, but the canvas and the agent drift apart, and every external edit (import, Composer) needs its own sync path back into React Flow.

## Consequences

- Save and load are trivial: the store content is the file content.
- Imports and future Composer output update the canvas automatically.
- Operations are pure functions over `AgentConfig`, easy to unit-test, and could later be emitted by the Composer as edit steps.
- Cost: nodes and edges are re-derived on each change. Negligible at the size of a scheduling agent (tens of nodes).
