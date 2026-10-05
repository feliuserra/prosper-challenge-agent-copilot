# ADR 0008: Node tools from a fixed mock catalog

- **Status:** Accepted, 2026-10-05. Amends [ADR 0002](0002-keep-schema-add-ui-positions.md): the schema gains one optional field.
- **Date:** 2026-10-05

## Context

- Phase 1 agents cannot look anything up or act. The example agent hard-codes two appointment times in a prompt and "books" by collecting a slot name. A real scheduler checks a calendar, finds the patient and books.
- Phase 2 tests need exact checks that mean the same thing on any agent. The Copilot generates graphs whose node and function names we cannot predict, so a hand-written reference suite cannot check `name_confirmed` or `collect_reason`. It can check "`book_appointment` was called with this slot" if every agent uses the same tools.
- Pipecat Flows supports functions that do not move to another node: a handler that returns `(result, None)` leaves the conversation in the current node and the model continues with the result (`pipecat_flows/manager.py:480-501`, `types.py:247`).

## Decision

1. **A fixed catalog in the backend** (`backend/clinic/`): `lookup_patient`, `register_patient`, `find_slots`, `book_appointment`, `reschedule_appointment`, `cancel_appointment`, `transfer_to_human`. Each has a description and a parameter schema. Tools only read and change the calendar; clinic policies (fees, new-patient rules) stay in the agent's prompts, where the deployment team writes them.
2. **A fake clinic world:** providers, patients, appointments and open slots from a seed JSON. Deterministic: a fixed "today", no clock, no randomness.
   - Live calls share one state that persists across calls (`backend/clinic/state.json`, gitignored, created from the seed when missing), so "book, then call back to reschedule" works in a demo. Deleting it, or `make demo-reset`, restores the seed.
   - Every test starts from its own fresh world, the clinic's seed or one it brings ("nothing free this week", "patient not on file").
   - The agent is told the clinic's date and weekday: the bot and the text runner add one line with it to the system message. Without it "next Tuesday" is meaningless and scheduling tests fail at random.
   - Strict formats in tool parameters and results (ISO dates and times, slot and appointment ids). The model converts what the caller says; tests compare exact values.
3. **Nodes list the tools they may use:** optional `tools: [name]` on `Node`. Tools return data and keep the conversation in the node; edges still move it. Branching on a result (patient found or not) is done by the model choosing between edges after it sees the result.
4. **Validation:** unknown tool, duplicate tool, or a tool with the same name as an edge function in the same node, each tied to its node.
5. **Visible like transitions:** each tool call is logged and sent to the UI as an RTVI server message `{type: "tool_call", node, tool, args, result}` (the same channel as [ADR 0006](0006-stream-transitions-over-rtvi.md)). Call records keep them (ADR 0013).
6. `transfer_to_human` ends the call after the bot says it is transferring. There is no real transfer.

## Alternatives considered

- **Tool edges:** an edge calls the API with its collected arguments and then moves on. Fewer concepts, but the target depends on the result (found or not), which needs dynamic targets in the schema and the editor.
- **User-defined tools:** name, parameters and a canned response defined in the editor. Most flexible and most UI to build, and canned responses do not behave like a calendar (a booked slot stays free).
- **No tools:** tests could only check what edges collected, under names that differ per agent. A reference suite written once for any agent would not be possible.

## Consequences

- Tests get a shared vocabulary: `tool_called`, `tool_order` and their arguments work on the hand-built reference agent and on any agent the Copilot generates.
- First schema change since Phase 1. It touches the dataclasses, validation, the builder, the zod mirror and the node panel. Agents without `tools` behave exactly as before.
- The catalog is specific to healthcare scheduling. That fits the product; in production each name would map to a real EHR or scheduling integration behind the same interface.
- The text runner (ADR 0009) imports the same tool code, so tests and live calls use one implementation.
