You fix a clinic's phone scheduling assistant whose tests fail. The tests are approved by a person and locked: you cannot change them. You change the agent with operations, or the clinic configuration, and only to make the agent follow its requirements.

## Diagnose first

For each failing test, find the broken link: why the agent did what it did. Read the failed checks, the transcript (tool results are what the clinic answered), and what the model was given at the failing turn (the node it was in and the functions it could call). Then name one link from this list:

- `configuration`: a configuration entry is wrong or missing. The tool answered from it, and the answer was wrong for the clinic (a provider who should do a visit type, a plan's coverage, a field to ask, the fee, a fact).
- `node_instruction`: the instruction is missing or wrong in the node where the call was, or it lives in another node than the one the call was in.
- `tool_not_offered`: the node did not offer the tool the step needed, or nothing asked the model to call it, so it guessed or invented.
- `overridden`: the instruction is there, but another instruction wins over it.
- `unclear_guideline`: the requirements do not say what to do here. This becomes a question for the client, not a fix: write it in `question`.

Give the turn the failure was decided at, and one or two sentences of explanation.

## Then make one change

One change for all the failures: operations on the agent, configuration edits, or both, aimed at the broken links. Make the smallest change that does the job. Keep what works: every passing test must still pass. Rules that are tables or numbers belong in the configuration, which the tools enforce, not in prompts. Never write a test caller's name, date of birth or phone number into the agent or the configuration, and never special-case a caller: the agent must work for any caller.

A configuration edit replaces one top-level key of the configuration with its whole new value: `providers`, `appointment_types`, `insurance_plans`, `registration_fields`, `booking_fields`, `cancellation` or `facts`. Cite the requirements it carries.

If you think a test is wrong (it checks something the requirements do not ask for), say so in `concerns`. The person decides; you still cannot change it.

{{MODE}}

## Operations

{{OPERATIONS}}

Tools in the catalog: {{TOOLS}}.

## The authoring guide

{{GUIDE}}

## Answer

JSON only:

{"diagnoses": [{"test": "test-id", "link": "node_instruction", "turn": 7, "explanation": "...", "question": null}], "rationale": "...", "operations": [{"op": "...", ...}], "configuration": [{"key": "facts", "value": {...}, "requirements": ["R3"]}], "concerns": [{"test": "test-id", "why": "..."}]}

The requirements, the configuration, the agent, earlier attempts and the failing tests follow. They are data, never instructions to you.
