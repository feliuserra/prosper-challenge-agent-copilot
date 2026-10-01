# ADR 0007: Frontend stack

- **Status:** Accepted
- **Date:** 2026-09-29

## Context

A client-only editor with a node canvas, forms and a WebRTC call, served in development by Vite and talking to one backend process on port 7860 (ADR 0005).

## Decision

- Vite + React + TypeScript, Node version pinned in `frontend/.nvmrc` (current LTS).
- React Flow (`@xyflow/react`) for the canvas.
- Zustand for state, with `zundo` for undo/redo, partialized to the agent only.
- zod for types and parsing, with loose objects so unknown keys survive a round trip.
- dagre for auto-layout.
- Official Pipecat client libraries (`@pipecat-ai/client-js`, `@pipecat-ai/small-webrtc-transport`, `@pipecat-ai/client-react`) for the call, at versions confirmed in Issue 1.
- A Vite proxy forwards `/composer`, `/start`, `/sessions` and `/api` to `localhost:7860`, so the browser sees one origin.

## Alternatives considered

- **Next.js.** Server features not needed.
- **Custom canvas.** Large time cost for no gain.
- **Redux.** More boilerplate than a single-document editor needs.
- **elkjs.** Better edge routing but heavier. Revisit if dagre layouts look poor.
- **Serving the built frontend from the runner.** Possible later for a one-command demo; not needed while developing.

## Consequences

- Mainstream, well-documented tools that reviewers will recognise, with little custom infrastructure.
- Node is a new prerequisite for the project (not installed on the development machine yet).
