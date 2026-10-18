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
- **Test** `unclear-reminder-answer-asked-again` in the seed spec (`backend/demo/workspace/linden-grove/spec.json`, R20): an existing patient, and a `replay` answer "Bye." to the reminder question. Checks: `book_appointment` is never called with "No reminder" or "none", a sick visit is booked, and a judge rule checks that the question was asked again and the booking used the next answer (text). I used `replay` rather than `hearing`: replay puts in "Bye." once, word for word, and lets the caller answer freely after that. A `hearing` pair such as "By text"→"Bye" depends on the caller model saying exactly "By text", and would garble the caller again if they repeated it. The seed spec only reaches new installs. The user's live workspace needs the test added in the Composer (re-seeding would replace version 2).

## Not verified

No model runs. The test is valid (`validate_test` against the spec's configuration) and the free suite passes (434 tests). Estimate for checking that the test fails on version 2 and passes with the rule: about $0.25 a run (gpt-4o agent over about 16 turns, plus the caller and the judge), so 3 runs on each agent is about $1.50.

## Follow-up

`verify_patient` asks for `register_patient`'s fields with the same "ask one at a time" wording and has the same gap (for example, an insurance plan heard wrong). Same rule, separate change.
