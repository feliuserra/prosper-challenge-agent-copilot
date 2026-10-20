# README drafts for #11

Two sections for the final README, drafted in #34 from [`results.md`](results.md). Numbers marked *(to run)* are filled once #34's paid runs are done.

---

## How we know it works

Every claim is a number from a run that anyone can repeat; [`docs/notes/results.md`](docs/notes/results.md) has the source of each.

- **The tests catch broken agents.** 15 agents were broken on purpose, one rule each, and the tests caught 12. Each survivor is understood. The model refuses medical advice even without the rule. A rule written twice survives cutting one copy. A text caller cannot mishear a name. The last is now covered: tests can garble a caller's words the way speech-to-text does.
- **The judge agrees with people.** On 32 verdicts a person reviewed, the judge (`gpt-4.1`) agreed on all 32. Smaller models did not (30 and 23), so they are not used for safety rules.
- **Detection finds what was planted, and knows where it stops.** In 85,495 synthetic calls over six weeks, all 6 planted defects were found, with no false alarms in 18 clinic-weeks, and no model calls. Recall falls with volume: a 2-point rise is found every time at 1,500 calls a week, and 2 times in 10 at 150. The memo has the table.
- **The judge finds silent failures and blames the right turn.** On 22 mock production calls of a deliberately weak agent, it found 8 of 10 planted issues. Every time, it put the decisive turn in the node that had the defect. It raised 2 false alarms. Its prompt was tuned on these calls, so this is not a blind measure.
- **A fix is checked before anyone accepts it.** The fix of a misheard name failed 5 of 5 reproductions before, and passed 4 or 5 of 5 after, in two live runs. The tests that passed before were run again. In the later run all of them passed. In the earlier run, the only one that failed had been flaky before the fix.
- **It generalises, or not, on a clinic it never saw.** A person wrote a second clinic's guidelines and tests, kept out of the repo until one final run: *(to run)*.

## What the tests don't catch

- **Voice.** Tests are text. They see words, not latency, interruptions, accents or a caller talking over the bot. Speech-to-text errors are simulated with word pairs per test, so only the mishearings someone thought of are tested. The manual call checklist ([`docs/notes/call-tests.md`](docs/notes/call-tests.md)) covers the rest by hand.
- **A simulated caller is not a caller.** It follows its card. Real callers change their minds, give two answers at once, or hang up for reasons no card says.
- **Generated tests can be wrong.** Several of the Copilot's tests could not pass as written, for example an exact free-text transfer reason. A person approves them, and the lint now refuses some kinds, but a bad test can still block a good agent or pass a bad one.
- **Green is not reached yet.** The agent the Copilot built for clinic A passes 15 of its 25 tests, and 13 of the 20 reference tests. The demo shows that, blocked, as it is.
- **The judge reads rules literally.** Most of its false alarms were "must state" requirements read word for word. And it was tuned on the calls it is measured on.
- **Synthetic logs prove the statistics, not the world.** Planted defects have the shapes we chose. A failure that leaves no trace in transitions, tool calls or the clinic's records is invisible to tier 1, and the judge sees only a sample.
- **The turn replay is a filter, not a judge.** In the one real fix, it ranked the candidates in reverse of the full reproductions, so the full rate chooses.
