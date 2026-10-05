# ADR 0011: Trusting the tests

- **Status:** Accepted, 2026-10-05
- **Date:** 2026-10-05

## Context

- The Copilot writes the agent, writes tests for it and loops until they pass. If the same models write the agent, write the tests and grade them, all three can share the same misreading of the guidelines and agree with each other while being wrong.
- A loop that runs until green learns whatever the tests reward. If it can see a suite, passing that suite says little.
- No technique guarantees a generated agent is right. The aim is to bound the risk and to report numbers we can defend.

## Decision

1. **Test-first human approval.** The Copilot shows requirements, client questions and tests before any graph exists. The human edits and approves the tests; reviewing 20 one-line tests against the guidelines is the cheapest place for human judgment.
2. **Locked tests.** Once approved, the Copilot cannot change a test. If it believes a test is wrong, it says so in its proposal and the human decides. (Coding agents fail the same way: deleting or weakening the failing test.)
3. **Tests come from requirements, not from the graph.** The spec step never sees an agent.
4. **A held-out reference suite.** 20 hand-written tests for a fictional clinic live in `backend/eval/`, outside the workspace the Copilot can read. The Copilot loops only on its own tests; the reference suite measures the result afterwards. A test checks that no reference test reaches a Copilot prompt.
5. **Mutation testing.** About 8 deliberately broken versions of the hand-built reference agent. Every mutant must fail at least one reference test, and every reference test must catch at least one mutant (or the reason is written down). A test that passes on a broken agent checks nothing.
6. **Judge calibration.** About 30 hand-labelled transcripts for the soft rules. Each judged rule needs at least 90% agreement with the labels; otherwise it is rewritten or turned into an exact check.
7. **Planted issues.** The mock production calls come from a deliberately weak agent with known defects, so we know what each call contains. The call checker's recall and false alarms are measured against that list.
8. **A second clinic** (stretch): a few tests for a clinic never used while tuning the Copilot's prompts, run once at the end. We will tune on clinic A all week; this shows whether the Copilot generalises or just learned clinic A.
9. **Report effort, not only pass rates:** human edits needed after generation, minutes from guidelines to green, minutes from issue to accepted fix. Pass rates show the agent works; these show the team's work went down.
10. **State the limits** in the README: what text tests cannot see, and that real calls are the final judge.

## Alternatives considered

- **Trust the generated tests:** fastest, and exactly the closed loop described above.
- **Human review of the graph instead of the tests:** slower, and it is the manual work the brief wants removed.
- **Only live calls as evidence:** real, but slow, expensive and impossible to repeat after every change.

## Consequences

- About half a day spread over #27, #29, #30 and #32: labels, mutants and the planted-issue list.
- Numbers to quote in the README and the demo: reference pass rate, mutants caught, judge agreement, checker recall and false alarms, effort.
- Still no guarantee. In production, real outcomes (completed bookings, transfers, hang-ups), a canary before full rollout and a rollback would be the next layer; they are out of scope.
- If time runs short, the second clinic goes first. Mutation testing, the held-out reference suite and locked tests stay: without them "20/20" means little.
