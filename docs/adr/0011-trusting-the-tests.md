# ADR 0011: Trusting the tests

- **Status:** Accepted, 2026-10-05. Amended 2026-10-08 by [ADR 0015](0015-debugging-by-cause.md): checks on the debugging itself.
- **Date:** 2026-10-05

## Context

- The Copilot writes the agent, writes tests for it and loops until they pass. If the same models write the agent, write the tests and grade them, all three can share the same misreading of the guidelines and agree with each other while being wrong.
- A loop that runs until green learns whatever the tests reward. If it can see a suite, passing that suite says little.
- No technique guarantees a generated agent is right. The aim is to bound the risk and to report numbers we can defend.

## Decision

1. **Test-first human approval.** The Copilot shows requirements, client questions and tests before any graph exists. The human edits and approves the tests; reviewing 20 one-line tests against the guidelines is the cheapest place for human judgment.
2. **Locked tests.** Once approved, the Copilot cannot change a test. If it believes a test is wrong, it says so in its proposal and the human decides. (Coding agents fail the same way: deleting or weakening the failing test.)
3. **Tests come from requirements, not from the graph.** The spec step never sees an agent.
4. **No test facts in the agent.** A proposal whose agent contains facts from any test (caller names, dates of birth, phone numbers) is blocked. It is the cheapest guard against special-casing a test ("if the caller is Ana Lopez...").
5. **A held-out reference suite.** 20 hand-written tests for a fictional clinic live in `backend/eval/`, outside the workspace the Copilot can read. The Copilot loops only on its own tests; the reference suite measures the result afterwards. A test checks that no reference test reaches a Copilot prompt.
6. **Mutation testing.** About 8 deliberately broken versions of the hand-built reference agent. Every mutant must fail at least one reference test, and every reference test must catch at least one mutant (or the reason is written down). A test that passes on a broken agent checks nothing.
7. **Judge calibration.** About 30 transcripts for the soft rules, labelled by Claude with a reason each and corrected by the user. Each judged rule needs at least 90% agreement with the labels; otherwise it is rewritten or turned into an exact check.
8. **Planted issues.** The mock production calls come from a deliberately weak agent with known defects, so we know what each call contains. The call checker's recall and false alarms are measured against that list. Real recorded voice calls and hand-roughened ones are mixed in, so the checker is not measured only on clean simulated text. The calls made by the runner keep their hidden caller in the label file, which the checker cannot read.
9. **A blind second clinic.** Claude writes the reference suite and the Copilot's prompts, so the reference suite is held out from the Copilot but not from its author. The user writes clinic B (guidelines and about 6 tests) and keeps it out of the repo until a single final run. No prompt changes after seeing it; the result is reported as it is. It shows whether the Copilot generalises or just learned clinic A.
10. **Report effort, not only pass rates:** human edits needed after generation, minutes from guidelines to green, minutes from issue to accepted fix. Pass rates show the agent works; these show the team's work went down.
11. **State the limits** in the README: what text tests cannot see, and that real calls are the final judge.
12. **Check the debugging too** (ADR 0015):
    - blame: on the weak agent's calls, the decisive turn falls in the node of the planted defect;
    - turn replays predict full reruns: for every candidate fix that went on to a full rerun, the turn rate is compared with the result;
    - forecast calibration: the hidden caller of a mock call, run against the fixed agent, gives the true what-if, compared with the forecast made from the caller card alone;
    - the past-call line on a proposal is compared with new simulated calls through the changed nodes;
    - a fix is chosen on the flagged call and its past-call numbers are reported on the other calls, so the choice is not fitted to the numbers shown.
    Sentence ablation is not measured; the README says so.

## Alternatives considered

- **Trust the generated tests:** fastest, and exactly the closed loop described above.
- **Human review of the graph instead of the tests:** slower, and it is the manual work the brief wants removed.
- **Only live calls as evidence:** real, but slow, expensive and impossible to repeat after every change.

## Consequences

- About half a day spread over #27, #29, #30 and #32: labels, mutants and the planted-issue list.
- Numbers to quote in the README and the demo: reference pass rate, mutants caught, judge agreement, checker recall and false alarms, effort.
- Still no guarantee. In production, real outcomes (completed bookings, transfers, hang-ups), a canary before full rollout and a rollback would be the next layer; they are out of scope.
- If time runs short, the second clinic goes first (it needs the user's time to write). Mutation testing, the held-out reference suite and locked tests stay: without them "20/20" means little.
