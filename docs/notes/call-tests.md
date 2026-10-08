# Manual call tests

A checklist of calls to make after each change to the voice pipeline or the example agent (`backend/agents/prosper-scheduler.json`). About five minutes in all.

**Setup:** `make dev`, open `http://localhost:5173`, open "Prosper Scheduler", press **Test call**, then **Call** for each test. Watch three places:

- the call panel transcript (what the bot heard and said, plus a "Transition" row for each step);
- the canvas (the current node is outlined in green, the edge just taken is animated);
- the `make dev` terminal, which logs each step as `[function] -> target | collected: {...}`.

The saved name is the `full_name` in the `name_confirmed` line.

## 1. Book with a hard name, with one correction

Say "book", then give a name that speech-to-text gets wrong, such as "Feliu Serra Burriel". When asked, spell it with one letter wrong on purpose. When the bot reads it back, say "no" and spell the right letters. Confirm, give a reason, pick a time.

Expected:
- every user line in the transcript is in English letters (no other scripts);
- the bot reads the name back letter by letter and waits for a yes before going on;
- after the "no", the call goes back to spelling: `correct_spelling -> confirm_name` if you gave the right letters in the same answer, `spell_again -> ask_name` if you only said "no";
- `name_confirmed -> collect_reason | collected: {'full_name': 'Feliu Serra Burriel'}`, spelled exactly as you spelled it;
- the call reaches `confirm`, the bot repeats the name and time, says goodbye and hangs up; the panel returns to idle.

## 2. Book with a common name, no correction

Say "book", give and spell a short name ("Ana Lopez"), say yes at the read-back.

Expected: one read-back only, then `name_confirmed` with that name. No extra questions.

## 3. Off-topic in the middle

At the read-back, ask something unrelated ("what's the weather like?"), then answer the read-back.

Expected: the bot answers briefly or steers back, asks again whether the name is right, and stays on `confirm_name` (no transition in the panel or the terminal until you answer).

## 4. Hang up halfway

Start a call, get as far as `offer_times`, press **Hang up**.

Expected: the panel returns to idle and keeps the transcript and transitions; the green outline goes away; the terminal shows the session ending with no traceback. A new call starts cleanly from `greeting`.

## Not covered yet

Reschedule and cancel: the example agent takes the same path for all three intents. Add tests for them when an agent has those paths (the full demo agent).
