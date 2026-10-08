# ADR 0015: Debugging by cause: rule chains, turn replay and what-if forecasts

- **Status:** Accepted, 2026-10-08. Amends [ADR 0002](0002-keep-schema-add-ui-positions.md) (one more optional field), [0009](0009-text-runner-for-simulated-calls.md), [0010](0010-test-format-and-grading.md), [0011](0011-trusting-the-tests.md), [0012](0012-copilot-edits-through-operations.md) and [0013](0013-workspaces-versions-and-calls.md).
- **Date:** 2026-10-08

## Context

- The loop in ADR 0012 sends failing checks back to the model and asks for a fix. The model guesses the cause. A wrong guess costs a full rerun of the suite, and the reviewer gets a change without a reason they can check.
- What decides one agent turn:

  ```
             AGENT JSON  (the only thing the Copilot can change)
    persona/role   task msgs(n)   edges + descriptions(n)   tools(n)   graph shape
          └──────────────┴──────────────┬──────────────────────┘           │
                                        ▼                                  ▼
    clinic date ──────────►  WHAT THE MODEL SAW AT TURN t  ◄──── node n_t ◄── earlier choices
    history ──────────────►  (system message + functions + history)
    tool results (world) ─►               │
    caller words ─────────►               │           sampling noise
    (intent + STT garbles)                ▼                 │
                                agent action at turn t ◄────┘
                          (words, function or tool call, arguments)
                                          │
                   next node, world change, caller's next words ──► outcome (requirement met?)

    confounder: caller style ──► which path the call takes, and ──► the outcome
  ```

- Two things follow. Counting issues per node is association: angry callers reach the cancellation node more often and fail more often, so the node gets blamed for what the callers brought. Only changing the node and replaying shows whether it is the cause, and we own the simulator, so we can. And the turn where a call visibly fails is not always the turn that decided it: a wrong name booked at turn 9 was decided at turn 3, where the spelling was never confirmed.
- When guidelines become an agent, most failures are a rule lost between the client's sentence and the answer ("Dr. Kim takes Medicaid only" lives in the FAQ node, the caller asked in booking), not a bad turn deep in a long call.
- What a call would have been with another agent is a counterfactual and is never observed. A recorded call is evidence only until the new agent first says something different; after that, any answer is a forecast. The agent and the tools are code we can run, so the only unknown mechanism is the caller, and the uncertainty sits in one place we can measure.

## Decision

1. **Flight recorder.** Every call record and every test result stores, per agent turn, the node, the exact messages and functions the model was given, and the tool results. The bot records them from its LLM context; the runner records the same.
2. **Requirement map.** Copilot operations cite the requirement ids they serve. Nodes, and the agent for its persona, carry an optional `requirements: [id]` list that the runtime ignores; it travels with renames and deletes like any other node field. A requirement that no node carries, or that no test checks, shows as a gap before any test runs.
3. **Rule chain.** Each failure is diagnosed as the link that broke, and each link has its own kind of fix:

   | Link | Example | Fix |
   | --- | --- | --- |
   | Not extracted | the Dr. Kim exception is not in the requirements | spec: add the requirement and a test |
   | Wrong place | the insurance rules live only in the FAQ node | graph: move it, or put it in the persona |
   | Overridden | "always confirm and be helpful" beats "Medicaid only" | wording: which instruction wins |
   | Data or tool | availability invented, `find_slots` not offered or not called | tools: offer or require the tool |
   | Unclear guideline | "most insurances accepted" | a client question, not a fix |

   Wrong place and data or tool are checked exactly from the recorded context and the map; the others are judged by the model. The diagnosis goes to the model with the failure and into the proposal.
4. **Turn replay.** `replay_turn(record, turn, agent, k)` rebuilds the context at that turn from the record, swaps in another agent, and samples the agent's action k = 5 times at the live temperature. It is graded by a turn check (ADR 0010) and reported as a rate (4/5). No simulated caller is involved, so the only randomness is the agent's own.
5. **Decisive turn.** The audit judge names the turn that decided an issue, and is run twice. If the two runs disagree, or no change at that turn changes the outcome, rollouts find it: continue the call from a few turns with the current agent and bisect for where the chance of success drops.
6. **What-if forecasts,** in Pearl's three steps:
   - abduction: a caller card inferred from the call (persona, goal, facts, style, and the recorded words with the question each answered);
   - action: swap in the new agent;
   - prediction: continue the call k times, reusing the recorded words while the agent asks the same things and simulating the caller after the first divergence.

   A forecast is always shown in two parts: observed up to the divergence turn, forecast after it, as a rate ("same as the real call up to turn 4; after that, 4 of 5 continuations succeed").
7. **Backcast first.** Before any what-if on a call, the original agent is run from the caller card k times. If the failure does not come back, the issue does not reproduce and we stop. How often it comes back is the base rate a fix must beat.
8. **The fix funnel** (#30 and #33): 2 to 3 candidate changes, then turn replay on the decisive turn, then turn replay on every past turn that ran in a changed node, then anchored replay and the full suite for the winner. The number of candidates and k are fixed, and the candidate is chosen on the flagged call while the past-call numbers report the others, so the choice is not fitted to the numbers shown. "At most 3 rounds" (ADR 0012) counts full reruns.
9. **One line on the proposal:** "14 past turns affected: 2 fixed, 11 same, 1 changed". Same means the same action; fixed means a turn flagged as bad now passes; changed means different, for a human to read.
10. **Views,** built last (#35): a turn inspector (what the model saw), a canvas overlay of the past turns a change affects, a win-probability chart for flagged calls on demand (the chance the call still ends well after each turn; the biggest drop is the decisive turn), and sentence ablation on demand (remove each sentence of the node's prompt in turn and see which ones the action depended on).

## Measuring it

Added to ADR 0011:

- **Blame:** on the weak agent's calls, the decisive turn falls in the node of the planted defect.
- **Turn replay predicts the full verdict:** for every candidate that went on to a full rerun, did the turn rate predict the result?
- **Forecast calibration:** the mock calls made by the runner keep their hidden caller in the label file. Running that caller against the fixed agent gives the true what-if, compared with the forecast made from the caller card alone. This is possible only because the data is synthetic.
- **The past-call line against what happens next:** new simulated calls through the changed nodes behave as the line predicted.
- Sentence ablation is not measured; the README says so.

## Alternatives considered

- **Full reruns only** (ADR 0012 as first written): simpler, but every hypothesis costs a suite run and failures come back without a cause.
- **The judge alone names the cause:** cheap, but its answer is never tested by changing anything.
- **Statistics over calls** (issues per node): cheap, and confounded by caller style.
- **Off-policy evaluation with importance weights** from logged probabilities, as recommender systems do: needs the new agent's actions to be ones the old agent could have taken, which free text breaks.
- **The requirement map in the workspace** instead of the agent: no schema change, but renames and deletes in the editor would leave it stale.

## Consequences

- A fix comes with its evidence: the broken link, the decisive turn, the replay rate and the past turns it changes.
- The loop gets cheaper: a turn replay is one model call per sample, and only the winning candidate gets a full rerun.
- Call records grow by a few KB per turn.
- A second optional schema field after `tools` (ADR 0008); the runtime ignores it.
- The runner must rebuild the same message list as Pipecat Flows. A recorded live call is compared with the runner's rebuild (#28).
- A what-if is a forecast, never a fact. It is only as good as the caller card, which the backcast and the calibration check.
- About two more days of work. Sentence ablation, the chart and the overlay are first in the cut order; the flight recorder, turn replay and the requirement map are never cut.
