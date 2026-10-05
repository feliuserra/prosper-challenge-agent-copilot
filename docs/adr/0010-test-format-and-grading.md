# ADR 0010: Test format and grading

- **Status:** Accepted, 2026-10-05. Models and the judge prompt are confirmed in #26 and #27.
- **Date:** 2026-10-05

## Context

- Tests are central to Phase 2: the human reviews them instead of prompts, the Copilot loops on them, and the reference suite measures the Copilot.
- Tests must be readable by a deployment engineer, writable by a model, and portable: the same reference test must work on any agent built from the same guidelines.
- A model playing the caller is not deterministic, and the budget allows about one run per test.

## Decision

1. **Tests are JSON**, like agents, so a model writes them with the same schema discipline and they diff well. Fields:
   - `id`, `title` (one line a human can check against the guidelines);
   - `tier`: `safety` or `core`;
   - `requirements`: the requirement ids it covers;
   - `caller`: `persona`, `goal`, `facts` (name, date of birth, phone...), `style` (terse, elderly, angry...);
   - `world`: the starting state of the clinic (ADR 0008), or the clinic's default;
   - `replay`: optional caller turns from a real call, each with the question it answered, reused word for word when the agent asks the same thing (ADR 0009);
   - `max_turns`;
   - `checks`.
2. **Exact checks first:** `tool_called` (with expected arguments; names compared ignoring case, spaces and punctuation), `tool_not_called`, `tool_order`, `call_ended`, `transferred`, `max_turns`.
3. **A judge only for soft rules:** a `judge` check holds one plain-language rule ("does not give medical advice"). The judge sees the transcript, the tool calls with their results, and that rule, never the agent's prompts, and answers pass or fail with the turn it relied on. Tool results let it tell real availability from invented availability.
4. **No checks on node or function names** in reference tests. They depend on how an agent was built, not on what it does.
5. **Tiers:** a failing `safety` test blocks a change. `core` tests are scored.
6. **Flakiness:** each test runs once; a failure is rerun once. Failing twice is a failure; failing then passing is reported as flaky. Flaky safety tests count as failures.
7. **Results carry evidence:** per check, the turn number and a quote, plus the transcript, tool calls and transitions, so a failure can be read without rerunning it.
8. **Cache:** results are stored by a hash of agent, test, model names and runner version, and only tests whose inputs changed are rerun. `--no-cache` for numbers we report.
9. **Errors are not failures:** API calls are retried with backoff and parallel calls are limited. A test that could not run (rate limit, outage) is reported as `error`, never counted as the agent failing.
10. **Pinned models** in one config, chosen after listing what the company key actually offers: dated model versions for the agent, the caller and the judge; the agent uses the same parameters in tests as in live calls. A small model plays the caller; the judge model is the cheapest one that reaches the calibration bar in ADR 0011.

## Alternatives considered

- **A judge for everything:** each test is a list of plain-language expectations. Simpler to write, but slower, more expensive and flakier, and a failure is harder to explain than "`book_appointment` was never called".
- **Two of three runs:** steadier results at about three times the cost. Rerunning only failures costs about the same as a single run.
- **YAML or a DSL:** nicer to read by hand, but one more format for the model to get right. The UI shows tests as cards anyway.

## Consequences

- Most failures are exact and explainable, which helps the Copilot fix them and the human trust them.
- Reference tests are portable across agents because of the shared tool catalog.
- Soft rules depend on the judge, so the judge is calibrated (ADR 0011).
- Results stay cheap enough to run in the Copilot's loop.
