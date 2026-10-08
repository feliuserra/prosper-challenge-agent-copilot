# ADR 0009: Simulated calls with our own text runner

- **Status:** Accepted, 2026-10-05. Amended 2026-10-08 by [ADR 0015](0015-debugging-by-cause.md): per-turn context, turn replay and continuing a recorded call.
- **Date:** 2026-10-05

## Context

- Phase 2 runs tests constantly: 20 reference tests, the Copilot's own tests in a loop of up to 3 rounds, about 8 mutants, and reproductions of production issues. Each test is a conversation of about 10 turns.
- The budget is cheap runs on company keys, and the demo needs a test suite to finish in about a minute.
- The live bot is a Pipecat pipeline (WebRTC, ElevenLabs speech-to-text and text-to-speech, OpenAI, Silero VAD) driven by a Pipecat Flows `FlowManager`. Pipecat renames APIs often (handoff, section 4).

## Decision

1. **A small Python runner** (`backend/sim/`) that interprets the agent JSON with the same rules as `AgentBuilder`:
   - each node's system message is its `role_message` or the agent's `persona`, plus its task messages;
   - edges are functions that move to their target;
   - tools (ADR 0008) are functions that run and keep the conversation in the node;
   - an end node ends the call after its reply;
   - `tts_say` actions become bot lines;
   - the clinic's date is added to the system message, as in the bot (ADR 0008).
2. **It calls OpenAI directly** with the agent's own model and the same parameters as `bot.py`, and runs tests in parallel with asyncio.
3. **A model plays the caller** from the test's persona, goal, facts and style.
4. **Anchored replay.** A test built from a real call carries the caller's turns as speech-to-text heard them, each with the question it answered. When the agent asks for the same thing, the caller says the recorded words exactly, garbles included; when the agent goes elsewhere (as it will after a fix), the caller improvises. Replaying turns blindly in order would stop making sense as soon as the fixed agent behaves differently.
5. **It shares code with the runtime:** the tool implementations and the world from `backend/clinic/`. A conformance test checks that the runner offers the same functions per node as `AgentBuilder` on the example and fixture agents.
6. **One entry point** used by the Copilot, `make eval` and a CLI (`uv run python -m sim run <agent> <tests>`).
7. **Per-turn context and replay** (ADR 0015). Results record, for each agent turn, the node and the exact messages and functions given to the model, plus the tool results. `replay_turn` samples one turn of a recorded call or test with another agent, on the recorded history. `continue_from` continues a recorded call from a turn with a given caller, reusing the recorded words while the agent asks the same things. The conformance test in (5) also compares a recorded live call's messages with the runner's rebuild of the same turns (#28).

## Alternatives considered

- **Pipecat in text mode:** the real `FlowManager` with a text-only pipeline. Most faithful, but slower, harder to run in parallel, and exposed to Pipecat's API churn.
- **Voice simulation:** a caller spoken with text-to-speech and heard by the real speech-to-text. The most realistic, and the only way to catch new speech problems, but several times slower and more expensive per test. Replaying turns from real calls covers the speech problems production has already shown.
- **A third-party simulation service:** adds an account and a dependency the reviewer would need, and hides the part of the system the challenge is about.

## Consequences

- Tests run in seconds to a minute and can run in the Copilot's loop.
- The runner can drift from the runtime. Not modelled: Flows' context handling in detail, interruptions, turn-taking and timing. The conformance tests limit the drift; the rest is listed in "What the tests don't catch" (`PLAN-phase2.md`).
- Spelled letters are assumed to be heard correctly; only garbles recorded in real calls are replayed.
- A pass in text does not prove the voice call works. Live calls stay part of each issue's checks (`docs/notes/call-tests.md`).
