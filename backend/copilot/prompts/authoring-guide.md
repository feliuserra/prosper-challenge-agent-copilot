# Authoring guide: what makes a good voice agent graph

What the Copilot follows when it writes or changes an agent (#30), and what a person can read to review one. Drafted from general practice for phone agents and from what Phase 1's calls and tests showed. Prosper's own practice goes here when the team reviews it.

An agent is a graph: nodes are steps of the call, edges are functions the model calls to move to the next step, tools are catalog functions a node offers (they answer and keep the call in the node). The persona applies in every node; a node's task messages apply only there.

## Speak like a person on the phone

- One or two short sentences per reply. Everything is spoken aloud: no lists, headings, emojis or symbols.
- Dates and times as people say them: "Tuesday the 20th at 2 PM", never "2026-10-20 14:00". Phone numbers in groups.
- Offer two or three options at a time, not every open slot.
- Plain words. Older callers and callers on a bad line need short answers more than complete ones.

## One question at a time

- Ask for one thing per turn and wait. Asking for the name and its spelling in one breath made callers give only the name, and the assistant asked again.
- Move on as soon as the step has what it needs. Do not ask for what a tool already returned.

## Confirm what would be costly to get wrong

- Names: ask for the spelling, read it back letter by letter, and let the caller correct it. In the template this is `ask_name`, then `confirm_name` with a self-loop for a correction (`correct_spelling`) and an edge back to `ask_name` (`spell_again`). Speech-to-text garbles names; a booking under the wrong name was decided when the spelling was skipped, not when it was booked.
- Before booking, changing or cancelling, read back the day, the time and the provider as a question ("Shall I book Tuesday the 20th at 9 with Dr. Lee?") and act only on a yes. Saying "you are booked" before the tool has run made callers hang up thinking it was done.
- A fee or a price the caller must accept: say it, then act only after they agree. The tool's `fee_acknowledged` is true only after that yes.

## Nodes

- One job per node, named for it (`verify_patient`, `offer_times`). The task message says what to do in this step, which tools to use, and when to move on.
- What applies everywhere goes in the persona: tone, safety rules, and "never state a policy, price or fact that a tool did not give you in this call". The model invents plausible policies ("we might waive the fee") when nothing forbids it.
- Group nodes into stages (`Identify caller`, `Visit`, `Book`, `Change appointment`) so the graph reads at a glance.

## Edges

- Function names are short snake_case verbs or states: `name_confirmed`, `record_reason`, `change_done`.
- The description is what the model reads to decide when to call it. Say exactly when: "Call once the caller has confirmed the spelling of their name." A vague description makes the model leave a node too early or never.
- Fields the edge collects get a type and a description; require only what the next step needs.
- Give callers a way back: corrections, "actually I want to cancel", starting over.

## Tools

- Clinic rules that are tables or numbers (who does which visit, coverage, required fields, the fee) live in the clinic configuration, and the tools enforce them. Prompts say to use the tool and to act on what it answers, including a refusal: never restate the table in a prompt.
- Offer a tool in every node where the caller might need it. `transfer_to_human` belongs in every node a caller could ask for a person from, which is nearly all of them; `get_clinic_info` wherever they might ask about the clinic.
- Times come only from `find_slots`. Coverage comes only from `check_coverage`. Facts come only from `get_clinic_info`. Tool results are the truth about the clinic.
- Identify the patient (`lookup_patient` with name and date of birth) before telling them anything about their appointments or changing one.

## Safety, in the persona

- Emergencies (signs of a heart attack or a stroke, severe trouble breathing, heavy bleeding, thoughts of suicide or self-harm): tell the caller to hang up and call 911 now. Do not book.
- No medical advice: not what to take, how much, whether to stop a medicine or whether something is serious. Offer a visit or a call back.
- Only the patient: nothing about a patient's appointments to anyone else, even with the patient's name and date of birth.
- A caller who asks for a person is transferred at once, without being asked for their details first.

## End cleanly

- Before ending, ask whether there is anything else.
- End nodes say one short goodbye and have no edges (the call ends after their first reply). An end node with post-actions must include `end_conversation`, or it never hangs up.
- A transfer ends the call after one line; do not keep talking after it.

## Changing an agent

- Make the smallest change that does the job: keep node names, edges and stages that already work. A reviewer reads the diff; every unrelated rewording costs them time.
- Cite the requirement each change serves, so a requirement nothing carries shows as a gap before any test runs.
