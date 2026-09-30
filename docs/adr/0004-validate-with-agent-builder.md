# ADR 0004: Validate with the real AgentBuilder, add warnings on the client

- **Status:** Accepted
- **Date:** 2026-09-29

## Context

- `AgentBuilder._validate` checks only three things (at least one node, `initial_node` exists, every edge target exists). It stops at the first problem and raises a single `ValueError` with a plain string. Missing required keys raise `KeyError` from `from_dict`.
- Nodes are built lazily on transition. Anything the LLM API or Pipecat Flows rejects (function names outside `^[a-zA-Z0-9_-]{1,64}$`, duplicate function names in one node, malformed `properties`) surfaces only when a call reaches that node, i.e. mid-conversation.
- The editor needs every error at once, each tied to a node or edge, to draw badges and a problems list.
- Reimplementing validation in TypeScript risks the UI and the runtime disagreeing.

## Decision

1. **The builder collects structured errors.** Validation gathers all problems as records `{message, node, edge}` (`node` and `edge` are optional; `edge` is the function name) instead of raising on the first. A `ValidationError(ValueError)` carries the list, so existing callers that catch `ValueError` still work. Parsing is made tolerant enough (missing required keys become errors, not `KeyError`) that one bad field does not hide the rest.
2. **New hard checks**, added because they otherwise fail mid-call:
   - function name matches `^[a-zA-Z0-9_-]{1,64}$`;
   - function names are unique within a node;
   - `properties` is an object whose values are objects with a known JSON-schema `type` (`string`, `number`, `integer`, `boolean`, `array`, `object`), and `required` is a list of strings.
3. **`POST /composer/validate`** runs the builder and returns `{errors: [...]}`. It returns 200 with an empty list when the agent is valid; a save or handover of an invalid agent returns 422 with the same list.
4. **Client-side warnings** cover authoring quality the runtime cannot judge: unreachable nodes, non-end nodes without outgoing edges, end nodes with outgoing edges, empty edge descriptions, empty task messages, `required` entries not defined in `properties`. Warnings never block a call.

The `properties` check is a small hand-written function, not the `jsonschema` package. We only need to catch the mistakes that break a call, and `jsonschema` is not installed today.

## Alternatives considered

- **Full validation in TypeScript only.** Instant, but drifts from the runtime.
- **JSON Schema generated from Python.** More infrastructure than three dataclasses justify.
- **`jsonschema` meta-schema validation of `properties`.** Thorough, but a new dependency for a check a dozen lines can do. Revisit if the Composer starts emitting nested schemas.
- **Treating the API-level checks as client warnings.** Cheaper, but lets through agents that break mid-call.

## Consequences

- The UI can never pass an agent the runtime rejects, and the runtime is protected when agents are edited by hand or by the Composer.
- Errors need a network round trip; the client debounces it.
- The starter's builder changes more than originally planned (error collection, tolerant parsing). The change is contained in `agent_builder/` and covered by tests.
