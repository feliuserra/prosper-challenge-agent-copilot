# ADR 0009: Simulated calls with our own text runner

- **Status:** Accepted, 2026-10-05
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
   - `tts_say` actions become bot lines.
2. **It calls OpenAI directly** with the agent's own model and the same parameters as `bot.py`, and runs tests in parallel with asyncio.
3. **A model plays the caller** from the test's persona, goal, facts and style. When a test has `replay` turns (from a real call), the caller says them word for word first, then improvises.
4. **It shares code with the runtime:** the tool implementations and the world from `backend/clinic/`. A conformance test checks that the runner offers the same functions per node as `AgentBuilder` on the example and fixture agents.
5. **One entry point** used by the Copilot, `make eval` and a CLI (`uv run python -m sim run <agent> <tests>`).

## Alternatives considered

- **Pipecat in text mode:** the real `FlowManager` with a text-only pipeline. Most faithful, but slower, harder to run in parallel, and exposed to Pipecat's API churn.
- **Voice simulation:** a caller spoken with text-to-speech and heard by the real speech-to-text. The most realistic, and the only way to catch new speech problems, but several times slower and more expensive per test. Replaying turns from real calls covers the speech problems production has already shown.
- **A third-party simulation service:** adds an account and a dependency the reviewer would need, and hides the part of the system the challenge is about.

## Consequences

- Tests run in seconds to a minute and can run in the Copilot's loop.
- The runner can drift from the runtime. Not modelled: Flows' context handling in detail, interruptions, turn-taking and timing. The conformance test limits the drift; the rest is listed in "What the tests don't catch" (`PLAN-phase2.md`).
- A pass in text does not prove the voice call works. Live calls stay part of each issue's checks (`docs/notes/call-tests.md`).
