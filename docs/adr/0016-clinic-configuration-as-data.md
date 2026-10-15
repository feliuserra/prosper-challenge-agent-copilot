# ADR 0016: Clinic configuration as data, agents from a template

- **Status:** Accepted, 2026-10-14. Amended 2026-10-15 (#30, see the end): a workspace's approved configuration is a clinic too. Narrowed the same day to keep #43 small: visit lengths, minimum notice, referrals and field formats became candidates, and the editor shows the configuration in a read-only Clinic tab. Amends [ADR 0008](0008-node-tools-from-a-mock-catalog.md) (clinic policies no longer live only in prompts), [ADR 0012](0012-copilot-edits-through-operations.md) (the Copilot starts from a template) and [ADR 0015](0015-debugging-by-cause.md) (one more broken link).
- **Date:** 2026-10-14

## Context

- The interviewer's answers (2026-10-14): agents start from a template per use case and are always customized. Two scheduling agents for small clinics are quite similar. What changes between clinics: which providers do which appointment types, which appointment types exist, which insurance covers which visits, the data needed to register a patient or book an appointment, and the conversation's flow and tone. Most of the deployment team's time goes to turning rules into an agent and checking it, not to getting the rules from the client.
- ADR 0008 kept clinic policies (fees, new-patient rules) in the agent's prompts and the tool catalog the same for every clinic. A rule such as "Dr. Okafor does not do new-patient visits" or "this plan does not cover physicals" written in a prompt is a table the model must apply from memory on every turn. It fails without a trace, and tests can only check it with a judge.
- The Copilot as planned (#29, #30) builds every agent's graph from nothing.

## Decision

1. **Rules that are tables or numbers live in a clinic configuration:** appointment types (who may book them, the providers who do them), insurance plans (covered types), registration and booking fields, the cancellation window and fee, and fixed facts (address, hours, parking). Only what the interviewer named; visit lengths, minimum notice, referrals and field formats wait until a test needs them.
2. **Tools enforce it.** They offer only what the configuration allows and refuse the rest with a reason the model can act on. A cancellation or reschedule inside the fee window needs `fee_acknowledged`. Three tools are added: `list_appointment_types`, `check_coverage`, `get_clinic_info`. The parameter schema the model sees is built from the clinic's configuration (its fields, its appointment types).
3. **The configuration is validated like an agent:** a loader returns every problem with its path. The configuration the Copilot extracts from guidelines must pass it, with the same repair loop as operations.
4. **Several clinics:** an agent names its clinic in an optional `clinic` field; live state is kept per clinic.
5. **The scheduling agent is a template** with no clinic facts in its prompts. The Copilot customizes a copy: a configuration plus operations on the template, not a new graph.
6. **The editor shows the configuration** in a read-only Clinic tab next to the graph: who does what, coverage, fields, the fee and the loader's problems. An agent is visibly a template graph plus a clinic configuration.
7. **Conversation stays in prompts:** flow, tone, what to say and when to confirm, and policies no tool can check (minors, emergencies, medical advice).

## Alternatives considered

- **Everything in prompts (ADR 0008 as it was).** No schema work, but every clinic needs prompt surgery on the template, and clinic rules are checked only by a judge.
- **The configuration as text in the system message.** Cheap, and the template stays generic, but the model still applies the tables itself and nothing refuses a wrong booking.
- **A rules engine** (conditions over caller, patient and slot). More general than the interviewer's list needs; a handful of tables covers it.

## Consequences

- Clinic rules get exact tests: a refused `book_appointment`, `check_coverage` called with the caller's plan, `fee_acknowledged` set only after the caller agreed.
- A Copilot proposal is a small, reviewable diff: for a small clinic, mostly configuration and tone. The human reviews the configuration as tables.
- Diagnosis (ADR 0015) gains a broken link, a wrong or missing configuration entry, decided exactly from the tool results in the failing turn. Mutation testing (ADR 0011) gains configuration mutants.
- The catalog grows from 7 to 10 tools, and `find_slots` and `book_appointment` take `appointment_type`. A clinic without configuration behaves as before.
- The text runner builds the same per-clinic schemas as the builder: both take them from the clinic (`ClinicWorld.tool_spec`), so they cannot drift.
- Clinics live in `backend/clinic/clinics/<id>.json` and their live state in `backend/clinic/state/<id>.json`. The agent is told its clinic's name with the date.
- The template gained a reschedule and cancel branch (built in #43's first PR): the fee rule has nothing to act on in an agent that only books.
- Some intake checklist items (#38) are answered by configuration entries instead of requirements.
- Out of scope, stated in the README: hospitals (departments, routing between them) and any rule the tables cannot express.

## Amendment (2026-10-15, #30)

- **A workspace's approved configuration is a clinic.** The build writes it to `backend/workspaces/<id>/clinic.json`, and the clinic loader (`clinic/clinics.py`) lists those next to `backend/clinic/clinics/`, under the workspace's id. The Copilot's agent names its workspace as its `clinic`, so the runner, the bot and the Clinic tab find the configuration with no new lookup. A file in `clinics/` wins over a workspace with the same id.
- The build starts by writing the spec's configuration there; an accepted proposal writes its configuration (with the Copilot's edits, if any) there and into the spec. While the loop tries configuration edits, the runner takes the clinic file directly (`run_suite(..., clinic=...)`); the cache key already holds the resolved world, so a result is keyed by the configuration it ran with.
- Tests see no workspace clinics: `tests/conftest.py` points the loader at an empty folder.

