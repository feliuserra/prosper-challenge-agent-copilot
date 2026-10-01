# ADR 0003: Node name is the identifier, renames cascade

- **Status:** Accepted
- **Date:** 2026-09-29

## Context

Edges reference their target, and the agent references its start node, by node `name`. Renaming a node would otherwise break those references. Edges have no identifier at all.

## Decision

- Keep `name` as the node identifier. `renameNode` updates every edge `target`, `initial_node` and the current selection in one step, and rejects a name that already exists.
- An edge is identified by its source node and its function name. The canvas edge id is `${source}::${function}`.
- Function names are unique within a node. This is also a runtime requirement (ADR 0004). `connect` generates a unique placeholder, and `updateEdge` rejects a function name that already exists in the node. The store never holds a duplicate, even transiently while the user types, because a duplicate would produce two React Flow edges with the same id.

## Alternatives considered

- **Stable ids separate from display names.** Robust against renames, but it changes the schema and forces the Composer to manage ids as well as names, which is exactly the kind of bookkeeping LLMs get wrong.

## Consequences

- References stay human- and LLM-readable.
- Renaming is one well-tested operation instead of logic spread across the UI.
- Names must be unique, which the UI enforces with inline errors.
- Canvas ids change on rename, so selection lives in the store and is updated by the rename operations; otherwise renaming would deselect the element being edited.
