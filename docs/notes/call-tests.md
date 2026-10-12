# Manual call tests

A checklist of calls to make after each change to the voice pipeline or the example agent (`backend/agents/prosper-scheduler.json`). About ten minutes in all.

**Setup:** run `make clinic-reset` once, so the clinic starts from its seed (`backend/clinic/seed.json`: Monday 2026-10-12, 08:30; Dr. Priya Patel, Dr. Daniel Okafor and Grace Kim, NP; patients Ana Lopez, born 1984-03-12, James O'Connor and Mei Chen). Then `make dev`, open `http://localhost:5173`, open "Prosper Scheduler", press **Test call**, then **Call** for each test. Watch three places:

- the call panel transcript: what the bot heard and said, a "Transition" row for each step, and a "Tool" row for each tool call (open "Result" to see what the clinic answered);
- the canvas: the current node is outlined in green, the edge just taken is animated;
- the `make dev` terminal, which logs each step as `[function] -> target | collected: {...}` and each tool call as `[tool] in node | args: {...} | result: {...}`.

Bookings persist between calls (in `backend/clinic/state.json`) until `make clinic-reset`.

## 1. New patient with a hard name, one correction, and a booking

Say "book", then give a name that speech-to-text gets wrong, such as "Feliu Serra Burriel". When asked, spell it with one letter wrong on purpose. When the bot reads it back, say "no" and spell the right letters. Confirm, give a date of birth, say you are new, give a phone number, give a reason, ask for a morning, pick one of the times offered.

Expected:
- every user line in the transcript is in English letters (no other scripts);
- the bot reads the name back letter by letter and waits for a yes; after the "no", `correct_spelling -> confirm_name` (right letters in the same answer) or `spell_again -> ask_name` (only "no");
- `name_confirmed -> verify_patient | collected: {'full_name': 'Feliu Serra Burriel'}`, spelled exactly as you spelled it;
- a `lookup_patient` row with the date of birth as YYYY-MM-DD and `found: false`, then `register_patient` with a new `pat-...` id, then `patient_identified`;
- in `offer_times`, a `find_slots` row (with `time_of_day: morning`), and the bot offers two times that are in its result, saying them like "Monday at 9 AM with Dr. Patel", never as 2026-10-12;
- a `book_appointment` row with the `slot_id` of the time you picked, then `appointment_booked -> confirm`; the bot confirms the day, time and provider, says goodbye and hangs up.

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

## Not covered yet

Reschedule and cancel: the example agent takes the booking path for all three intents. The tools exist (`reschedule_appointment`, `cancel_appointment`); add calls for them when an agent has those paths (clinic A in #27).
