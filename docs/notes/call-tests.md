# Manual call tests

A checklist of calls to make after each change to the voice pipeline or the template (`backend/agents/prosper-scheduler.json`, the example agent every Copilot build starts from). About fifteen minutes in all, plus two calls on the demo's agent at the end.

**Setup:** run `make clinic-reset` once, so the clinic starts from its seed (`backend/clinic/clinics/riverside.json` since #43: Monday 2026-10-12, 08:30; Dr. Priya Patel, Dr. Daniel Okafor and Grace Kim, NP; patients Ana Lopez, born 1984-03-12, James O'Connor and Mei Chen). Then `make dev`, open `http://localhost:5173`, open "Prosper Scheduler", press **Test call**, then **Call** for each test. Watch three places:

- the call panel transcript: what the bot heard and said, a "Transition" row for each step, and a "Tool" row for each tool call (open "Result" to see what the clinic answered);
- the canvas: the current node is outlined in green, the edge just taken is animated;
- the `make dev` terminal, which logs each step as `[function] -> target | collected: {...}` and each tool call as `[tool] in node | args: {...} | result: {...}`.

Bookings persist between calls (in `backend/clinic/state/riverside.json`, one file per clinic since #43) until `make clinic-reset`.

## 1. New patient with a hard name, one correction, and a booking

Say "book", then give a name that speech-to-text gets wrong, such as "Feliu Serra Burriel". When asked, spell it with one letter wrong on purpose. When the bot reads it back, say "no" and spell the right letters. Confirm, give a date of birth, say you are new, give a phone number, give a reason, ask for a morning, pick one of the times offered.

Expected:
- every user line in the transcript is in English letters (no other scripts);
- the bot reads the name back letter by letter and waits for a yes; after the "no", `correct_spelling -> confirm_name` (right letters in the same answer) or `spell_again -> ask_name` (only "no");
- `name_confirmed -> verify_patient | collected: {'full_name': 'Feliu Serra Burriel'}`, spelled exactly as you spelled it;
- a `lookup_patient` row with the date of birth as YYYY-MM-DD and `found: false`, then `register_patient` with a new `pat-...` id, then `patient_identified`;
- in `offer_times`, a `find_slots` row (with `time_of_day: morning`), and the bot offers two times that are in its result, saying them like "Monday at 9 AM with Dr. Patel", never as 2026-10-12;
- after you pick a time, the bot asks whether you need an interpreter (Riverside's booking field, `interpreter`), then reads the booking back as a question with the day, time and provider, and asks nothing else after it (#30);
- only after your yes, a `book_appointment` row with the `slot_id` of the time you picked and `interpreter` as you answered, then `appointment_booked -> confirm`; the bot confirms the day, time and provider, says goodbye and hangs up.

## 2. Returning patient, and the slot from call 1 is gone

Say "book", give and spell "Ana Lopez", say yes at the read-back, give the date of birth March 12, 1984. Ask for the same day and time you booked in call 1.

Expected: one read-back only; `lookup_patient` returns `found: true` with `pat-001` and her appointment on Wednesday the 14th at 10 AM; no `register_patient`. The time booked in call 1 is not in the `find_slots` result, and the bot does not offer it.

## 3. Ask for a person

At the greeting, say "Can I talk to a person?"

Expected: a `transfer_to_human` row with a short reason; the bot says in one sentence that it is transferring you, then hangs up. The panel returns to idle.

## 4. Short answers and pauses

At the greeting, answer with one word: "Book." Later, spell your name with a clear pause between the first and last name.

Expected: the bot answers "Book." in about a second, not three. The pause while spelling does not cut you off; if it does (the turn ends before you finish), note how long you paused: the limit is `TURN_STOP_SECS` in `backend/bot.py`.

## 5. Off-topic in the middle

At the read-back, ask something unrelated ("what's the weather like?"), then answer the read-back.

Expected: the bot answers briefly or steers back, asks again whether the name is right, and stays on `confirm_name` (no transition in the panel or the terminal until you answer).

## 6. Hang up halfway

Start a call, get as far as `offer_times`, press **Hang up**.

Expected: the panel returns to idle and keeps the transcript, transitions and tool calls; the green outline goes away; the terminal shows the session ending with no traceback. A new call starts cleanly from `greeting`.

## 7. Reschedule

Say you want to move an appointment, give and spell "Ana Lopez", born March 12, 1984. Ask for Thursday morning instead.

Expected: `choose_intent` to `ask_name`, then `change_appointment -> manage_appointment` after `lookup_patient` (no `register_patient`). The bot names her appointment (Wednesday the 14th at 10 AM with its provider) and checks it is the one you mean. Then a `find_slots` row, two times offered from its result, a `reschedule_appointment` row with the time you picked, and `change_done -> change_confirmed`: one or two sentences with the new day and time, then goodbye.

## 8. Cancel, outside the fee window

Run `make clinic-reset` first if call 7 moved Ana's appointment. Say you want to cancel, and identify as Ana Lopez as in call 7.

Expected: the bot names the appointment and asks you to confirm before cancelling. Riverside's fee is $50 inside 24 hours, and the clinic's clock is Monday 08:30, so Wednesday is outside the window: no fee is charged or agreed. Then a `cancel_appointment` row and `change_done -> change_confirmed`.

## 9. An answer that does not answer (#79)

Book as in call 2. When asked about an interpreter, say something that is not an answer, such as "Bye" or "What?".

Expected: the bot asks the interpreter question again and does not call `book_appointment` until you answer it. It never books with "none" for you.

## 10. Questions the clinic answers

At the greeting, ask "Do you take Aetna?", then "What are your hours?"

Expected: a `check_coverage` or `get_clinic_info` row for each, and answers from their results (the clinic's facts), not from the model's memory. Then say "That's all" and the bot says goodbye.

## The demo's agent: Linden Grove (#32, #33)

`make demo-seed` (or `make demo-reset`) installs the weak Linden Grove agent, version 1. Its clinic is `backend/clinic/clinics/linden-grove.json`: Monday 2026-10-19, 08:00; Dr. Alvarez, Dr. Reed and Nina Brooks; patients such as Daniel Ortiz, born 1979-08-14. Open "Linden Grove scheduler", then **Test call**.

- **Version 1, a hard name.** Book as a new patient with a name speech-to-text gets wrong, such as "Sarah Burrell". Expected (the planted defect `wrong-name`): the bot never asks for the spelling, and `register_patient` gets the name as heard.
- **After the fix (version 2, Act 2 of `docs/demo.md`).** The same call. Expected: the bot asks for the spelling (the `ask_for_spelling_again` self-loop in ask_name), and `register_patient` gets the spelled name. The user's call of 2026-10-18 did this end to end.
- **The reminder (Linden Grove's booking field).** When asked how to be reminded, say "By text" fast. If it arrives as "Bye", version 2 books with `reminder: none` (seen on 2026-10-18). With #79's rule added as a new version, it asks again.
