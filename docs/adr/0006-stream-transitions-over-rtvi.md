# ADR 0006: Stream transitions to the UI over RTVI

- **Status:** Accepted. Send API confirmed in Issue 1 (2026-10-02), see [`docs/notes/runtime.md`](../notes/runtime.md).
- **Date:** 2026-09-29

## Context

A test call without visibility into the graph forces the author to guess why the agent behaved as it did. Transitions happen in the edge handler in `builder.py`, which already logs them.

In pipecat-ai 1.4.0, `PipelineWorker` enables RTVI by default (`enable_rtvi=True`, `pipecat/pipeline/worker.py:237`), `RTVIServerMessageFrame` exists (`pipecat/processors/frameworks/rtvi/frames.py:38`), and the edge handler has access to the worker through `flow_manager.worker` (`pipecat_flows/manager.py:251`).

## Decision

- The edge handler sends an RTVI server message `{type: "transition", from, function, to, args}` by queueing an `RTVIServerMessageFrame` with `flow_manager.worker.queue_frame(...)`. The default RTVI observer turns it into a `server-message` (`observer.py:549`), and client-js delivers `data` to `onServerMessage`. `from` is the source node name, captured when the edge function is built.
- The initial node is highlighted by the client on bot-ready. The client already knows `initial_node`, and a server message sent at connect may arrive before the client is listening.
- The UI highlights the active node, animates the edge taken and lists transitions with their collected args.

## Alternatives considered

- **Parse backend logs.** Brittle, and needs a second channel to the browser anyway.
- **A separate WebSocket channel.** Duplicates what RTVI already provides over the call connection.

## Consequences

- Test calls become a debugging tool.
- Small backend change in one place (the edge handler).
- Depends on the RTVI server-message API of the installed Pipecat version.
- Collected args (PHI in production) reach the browser. Acceptable for a local tool; stated in the README.
