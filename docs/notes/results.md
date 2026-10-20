# Results

The numbers behind the memo and the README, each with where it comes from and when it was measured. Model costs are list prices from the spend log (`make spend`), which starts on 2026-10-15. Rows marked **to run** are #34's paid runs, not done yet. Their cost is stated before they run.

## Do the tests mean something? (#27)

| Measure | Result | Source |
|---|---|---|
| Reference agent on clinic-a's 20 tests | 19 pass, 1 flaky (`physical-not-with-nina`), safety 5/5; about 60 s, $1.88 | `make eval NO_CACHE=1`, 2026-10-15 |
| Same, after the runner changes of #30 and #33 | **to run** (about $1.90) | `make eval NO_CACHE=1` |
| Mutants caught | 12 of 15 | `make eval MUTANTS=1`, 2026-10-15, $3.08 |
| Judge agreement with the 32 human labels | `gpt-4.1` 32/32 (used), `gpt-4.1-mini` 30/32, `gpt-4.1-nano` 23/32 | `make eval JUDGE=…`, $0.02 |

Survivors:
- **M7, medical advice:** `gpt-4o` refuses dose advice even without the rule.
- **M8, every type open to any patient:** the rule also lives in the type's description.
- **M15, no spelling:** a simulated caller reads the garbled name and corrects it. #33's `hearing` pairs now garble a test's words on the way to the agent, which is what M15 needed. The mutants have not been run again since.

## Detection at scale (#57, #58)

85,495 synthetic calls over 6 weeks in 3 clinics (11,500, 1,500 and 150 calls a week), with 6 planted defects and 3 traps that must not be flagged. No model calls; detection takes 5 s.

| Measure | Result |
|---|---|
| Planted defects found | 6 of 6 |
| False alarms | 0 in 18 clinic-weeks (0 per 1,000 calls) |
| Traps not flagged | 3 of 3 (one is significant but below the minimum effect) |
| False alarms in the recall sweep | 10 in 600 clinic-weeks |

Recall: re-entries in Confirm name (base about 2.0%), a new version for two weeks after two, 10 seeds each.

| Calls a week | +0.5 pt | +1 pt | +2 pt | +3 pt | +5 pt |
|---|---|---|---|---|---|
| 150 | 0% | 0% | 20% | 50% | 70% |
| 1,500 | 10% | 40% | 100% | 100% | 100% |
| 11,500 | 60% | 100% | 100% | 100% | 100% |

Source: `make detect-eval`, run again on 2026-10-20 (same numbers as #58).

## The judge on a sample (#32)

22 mock production calls of the weak Linden Grove agent (10 planted issues, 17 others found by reading every transcript first). The judge is `gpt-4.1`, run twice.

| Measure | Result |
|---|---|
| Planted issues found | 8 of 10 |
| False alarms | 2 in 22 calls (both "security" on calls where the agent held) |
| Blame: decisive turn in the planted defect's node | 8 of 8 |
| All labelled issues found | 22 of 27 |
| Second run put the decisive turn in the same place | 22 of 27 (81%) |
| Caller cards: hidden facts seen | 88 of 104 (85%; not the true name where speech-to-text garbled it) |
| Tickets matched to their call | 3 of 3 |
| Cost | about $0.41 for the 22 calls; making the calls cost $1.94 |

Source: `make judge-eval`, run again on 2026-10-20. Caveat: the judge prompt was changed twice after seeing misses, so these 22 calls no longer measure it blind.

Missed:
- `ignored-transfer`: it says it is transferring but cannot.
- `invented-slots`: it offers 7 AM, which no tool returned.
- Three unplanted issues, two of them a reminder never asked about. #79's rule is about the same field.

## Building from guidelines (#29, #30)

On clinic-a (Linden Grove's guidelines, 25 generated tests).

| Step | Result | Time | Cost |
|---|---|---|---|
| Spec | 45 requirements (4 baseline, 5 client-question defaults), 5 client questions, 25 tests (7 safety), none untested | 136 s | $0.38 |
| Configuration against the hand-written `linden-grove.json` | same on 28 values; 3 differ (two field names, the fact labels) | | |
| Build with the test loop | workspace tests 14 → 15 of 25 in 3 rounds (1 kept); reference suite 13/20 (1 flaky), safety 4/5 | 474 s | $10.23 (+ reference suite: $12.38) |
| Build without the loop | reference suite 13/20 (2 flaky), safety 5/5 | | $2.11 with the reference suite |

Still failing after the loop:
- two read-backs (the template has since gained one, #30)
- Humana and Cigna (`check_coverage` and `get_clinic_info` not offered where the caller asks)
- outside hours

Several generated tests cannot pass as written; for example, an exact free-text transfer reason, which #29's lint now refuses. **Minutes from guidelines to green: not reached.** Guidelines to a proposal take about 10 minutes, and the proposal is blocked at 15 of 25. The demo shows that result as it is and accepts it anyway.

**Human edits after generation:** none were needed to get a proposal; reaching green would need some. The known weaknesses of the stored spec:
- the clinic's emergency list and "offer a visit or a nurse call back" were set aside as restatements
- the $50 fee is quoted but not in R27's text
- R36 repeats part of R8

## Fixing from an issue (#33)

Call `lg-1019-0804`: Sarah Burrell registered as "Sara Boreal", decided at turn 4 in ask_name, ticket T1. Third real run, 2026-10-17.

| Measure | Result |
|---|---|
| Reproduction on the current agent | 5 of 5 continuations fail |
| Candidates at the decisive turn (turn replay) | 5/5, 3/5, 0/5 |
| Candidates in full reproductions | 3/5, 4/5, 5/5 |
| Turn replay against full reruns | Ranked the candidates in reverse; the best by turn was not the best in full. Run 2, re-graded: turn 5, 2, 0 against full 1, 4, 5. |
| Chosen (best full rate) | candidate 3, a self-loop asking for the spelling again; reproduction 5/5 after |
| Regressions | 12 of the 13 rerun tests pass; blocked only by `transfer-running-late`, flaky before the fix, in a node the fix does not touch |
| Time and cost | 252 s, $5.90 (runs 1 and 2: $2.65 and $10.15, see the handoff) |
| Minutes from issue to accepted fix | about 4 minutes of model time, then the review; accepted while blocked as version 2 |
| Live check | the user's live call on version 2 (2026-10-18): the agent asked for the spelling, and the booking got the spelled name |

The turn replay is a cheap filter (1.8 s for 5 replays), but it does not choose: the fixes that work ask for the spelling later than the turn it checks. **Still to run:** the suite on version 2 (about $2.50), to check that the reproduction test still passes there.

## The reminder answer (#79)

The live call of 2026-10-18 showed "By text" heard as "Bye" and booked as no reminder. With the `hearing` pair and 3 runs each: version 2 passed 1 of 3 (twice it said goodbye and booked nothing), and version 2 with the new rule passed 3 of 3. $1.53. See `docs/notes/reminder-unclear-answer.md`.

## Clinic B: does it generalise? (#34)

**To run.** A held-out clinic the user writes (guidelines and about 6 tests), added to `backend/eval/clinic-b/` only then and run once with `make eval COPILOT=1`: about $12 with the loop, about $3 without. No prompt changes after seeing it; the result goes here as it is.

## Cost per run

| Run | Cost | Time |
|---|---|---|
| One booking-length simulated test | $0.06 to $0.08 | |
| Reference suite (20 tests) | $1.88 | 60 s |
| Spec step | $0.35 to $0.38 | 2 min |
| Build call alone | $0.05 | 30 s |
| Build with the test loop (25 tests, 3 rounds) | about $10 | 8 min |
| Fix from an issue | $5.90 (from $2.65 to $10.15) | 4 min |
| Mutants (26 pairs) | $3.08 | |
| Judge, 22 calls | $0.41 | |
| Detection, 85,495 calls | $0 | 5 s |
| The demo, with the cached switch | the live calls, plus $0.38 if the spec runs live | |

Spend logged since 2026-10-15: $49.77 to 2026-10-18 (copilot $33.31, eval $11.81, demo calls $1.94, judge $0.84, tests $1.80, replays $0.07).
