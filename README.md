# Prosper Challenge — Agent Composer

Voice AI for healthcare scheduling. An agent is a **graph of nodes** (Pipecat Flows), defined declaratively as JSON and compiled into a runnable voice pipeline.

- **Phase 1** — a UI to edit the node graph and place a test call.
- **Phase 2** — the Agent Copilot: build an agent from a clinic's guidelines and check it, then find problems in its calls at scale.

## Hand-in, 15 October 2026

The version handed in is the tag [`handin-2026-10-15`](https://github.com/feliuserra/prosper-challenge-agent-copilot/tree/handin-2026-10-15). Start with the memo, [`docs/memo/memo.pdf`](docs/memo/memo.pdf): the problem, what was built, what is designed but not built, and the results. Commits after the tag finish what the memo marks as designed: the Copilot UI, the judge on a sample, fix from an issue and the demo (#31 to #34).

```
browser mic  ->  ElevenLabs STT  ->  OpenAI LLM  ->  ElevenLabs TTS  ->  browser
```

## Quickstart

Requires **Python 3.11+**, [**uv**](https://docs.astral.sh/uv/getting-started/installation/) (it fetches a matching Python if needed) and **Node 24** (`frontend/.nvmrc`). Copy `backend/.env.example` to `backend/.env` and fill in `OPENAI_API_KEY` and `ELEVENLABS_API_KEY`. Then, from the repo root:

```bash
make install   # uv sync for the backend, npm ci for the frontend
make dev       # voice runner on :7860 + editor on :5173
```

Open `http://localhost:5173`: pick an agent, edit the graph, and press **Test call** in the toolbar, then **Call**. Allow mic access. The call uses the draft as it is in the editor, saved or not. `Ctrl+C` stops both processes. `make test` runs the backend and frontend tests; `make help` lists all targets.

`make run` starts the voice runner alone, with Pipecat's prebuilt client at `http://localhost:7860/client`, which calls the default agent (`backend/agents/prosper-scheduler.json`).

## Phase 2: what to run

Detection at scale makes no model calls:

```bash
make synth        # 85,000 synthetic calls for 3 clinics, with defects planted at known rates (about 6 s)
make detect       # the ranked issues (about 5 s)
make detect-eval  # found or missed per planted defect, false alarms, and where detection stops (the sweep takes about 40 s on 12 cores)
```

Then run `make dev`, open an agent and press **Call heatmap** on the canvas: the ranked issues appear on the right, and the graph is tinted by how far each node is from its baseline.

The tests and the Copilot call OpenAI with the key in `backend/.env` and cost money. Results are cached, so a rerun is free; `NO_CACHE=1` runs again. Setting `OPENAI_API_KEY=` on the command line is not a dry run: `backend/.env` wins.

| Command | What it does | Cost, uncached |
| --- | --- | --- |
| `make eval` | The 20-test reference suite (`backend/eval/clinic-a/`) against the hand-built reference agent | about $1.90 |
| `make eval MUTANTS=1` | The 15 broken agents against the tests built to catch them (needs `make eval` first) | about $3 |
| `make eval COPILOT=1 NO_LOOP=1` | The Copilot writes clinic A's spec from its guidelines, builds the agent from the template, and the reference suite runs on it | about $2.50 |
| `make spend` | The estimated spend so far, by day and source, from the spend log | free |

`make help` lists every target with its options.

## Layout

| Path | Responsibility |
| --- | --- |
| `backend/bot.py` | The voice pipeline (WebRTC + ElevenLabs STT/TTS + OpenAI LLM). Runs the agent sent with the connect request, or the default agent. No graph logic lives here. |
| `backend/agent_builder/` | All agent-building code. `schema.py` = the declarative `AgentConfig` / `Node` / `Edge` contract; `validation.py` = every problem with an agent, as `{message, node, edge}` records; `builder.py` = `AgentBuilder`, which validates the JSON and compiles it into a Pipecat Flows graph. |
| `backend/composer_api.py` | The editor's agents API, served by the runner under `/composer` (list, get, save, validate, health). |
| `backend/agents/` | Agents **as data**, one JSON file each. `prosper-scheduler.json` is the example clinic scheduler and the default agent; agents saved from the editor are gitignored. |
| `backend/copilot/` | The Copilot (Phase 2). `workspace.py` = one workspace per agent in `backend/workspaces/<id>/` (guidelines, spec, versions, test runs, proposals, call records; gitignored); `api.py` = its API under `/copilot`. Each save from the editor adds a version when the agent changed. |
| `backend/clinic/` | The tool catalog, the mock clinic calendar and each clinic's configuration (`clinics/<id>.json`), which the tools enforce. |
| `backend/sim/` | The text runner: a simulated caller, the agent under the voice runtime's rules, the checks and the judge. |
| `backend/eval/` | Clinic A's guidelines, the reference suite and agent, the mutants and the judge labels; `make eval`. |
| `backend/detect/` | The synthetic call logs, the signals, the statistics and the triage behind `make detect` and the heatmap. |
| `docs/` | The memo, the [ADRs](docs/adr/README.md) (why each decision was made) and `handoff.md` (the working notes). |
| `frontend/` | The graph editor and test-call panel (Vite + React + TypeScript). In development Vite proxies `/composer`, `/copilot`, `/start`, `/sessions` and `/api` to the runner. |
