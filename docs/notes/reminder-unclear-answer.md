# Unclear answer to a booking question booked as "none"

Seen in the live call that confirmed #33's fix (2026-10-18, Linden Grove version 2, `offer_times`). After the caller agreed to a slot, the agent asked how to send the reminder. The caller said "By text", speech-to-text wrote "Bye", and in the same turn the agent called `book_appointment` with `reminder: "none"`. The caller's "Text" arrived after the booking.

## Cause

Three things together, all in the prompt and the field, none in code:

- `offer_times` says to ask for each `book_appointment` field and then "once you have what book_appointment needs, call it in the same reply". Nothing says what to do with an answer that does not answer the question, so the model takes any reply as one.
- The `reminder` field (`clinic/clinics/linden-grove.json`) is required free text, and its description names `'none'` as a valid value, so it offers the model an easy default. "Bye" is close enough to "no thanks" for the model to pick it.
- The tool cannot catch it: `"none"` is a valid value, so an enum on the field would not help. The mistake is reading the answer, and only the prompt can fix that.

## Change (this branch)

- **Template** (`backend/agents/prosper-scheduler.json`, `offer_times`), after "ask one at a time for anything else book_appointment needs": take an answer only when it clearly answers the question. If it is unclear, is none of the choices offered, or is about something else (with "by text" heard as "Bye" as the example), ask the question again, and never fill in an answer the caller did not give. The template has the same gap: it reads back only the day, time and provider, so the guessed reminder would also get through its yes. Every clinic built from the template gets the rule.
- **Not the reference agent** (`eval/clinic-a/reference-agent.json`). Linden Grove version 1 is `weak_agent(reference)`, and `test_demo` makes sure the committed version 1 matches it. The 22 mock calls and their labels were recorded on that version, so changing the reference would change version 1 after its calls were recorded.
- **Linden Grove** gets the same sentence as a new version (3) of its own agent through the Composer, like #33's fix. Its workspace (`backend/workspaces/`) is gitignored, so this branch does not include it. The text to add, after the same sentence in its `offer_times`, is the template's new sentence.
- **Test** `unclear-reminder-answer-asked-again` in the seed spec (`backend/demo/workspace/linden-grove/spec.json`, R20). An existing patient whose style is to answer the reminder question with exactly "By text." the first time and "A text message, please." if asked again. `hearing` is `[["By text", "Bye"]]`, so the code turns the first answer into "Bye" and leaves the second alone. Checks: `book_appointment` is never called with "No reminder" or "none", a sick visit is booked, and a judge rule checks that the question was asked again and the booking used the next answer (text). The seed spec only reaches new installs. The user's live workspace needs the test added in the Composer (re-seeding would replace version 2). Adding it moves the test count in `test_tests_that_failed_before_the_fix_are_not_run_again` (26/24 to 27/25). The branch is based on #33's branch, which adds `hearing`.

## Runs (2026-10-18, $1.53 in all)

**First try, with `replay` ($0.77).** A recorded "Bye." ran 3 times on version 2 and 3 times with the rule, and all 6 passed. But the caller model used the recorded answer only once, in a run with the rule: "Bye." reads like hanging up, so the caller decided it no longer made sense and said "Text, please." itself. So version 2 never faced "Bye". In the one run that got it, the fixed agent asked again and booked with `text`.

**With `hearing` ($0.76).** All 6 runs got "Bye".

| Agent | Passed | What it did after "Bye" |
|---|---|---|
| Version 2 | 1 of 3 | Twice it said goodbye and the call ended with nothing booked. Once it said "I will not book the appointment", and booked only because the caller objected (the checks pass that run). |
| Version 2 plus the rule | 3 of 3 | Asked the reminder question again every time, then booked with "text" or "text message". |

None of the simulated version 2 runs booked with "none" as the live call did. They took "Bye" as goodbye instead. It is the same cause (an answer that does not answer the question is acted on), and the checks catch both forms: "none" fails `tool_not_called`, and no booking fails `tool_called`. The rule fixed both forms in these runs. Three runs per agent is a small sample.

One side effect of the pair: the agent's own "Bye" reaches the caller as "By text" (it works both ways). "Goodbye" is not touched (whole words only), and the agent says it only at the end of the call.

## Follow-up

`verify_patient` asks for `register_patient`'s fields with the same "ask one at a time" wording and has the same gap (for example, an insurance plan heard wrong). Same rule, separate change.
