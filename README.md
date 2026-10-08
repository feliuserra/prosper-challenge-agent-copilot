# Prosper Challenge — Agent Composer

Voice AI for healthcare scheduling. An agent is a **graph of nodes** (Pipecat Flows), defined declaratively as JSON and compiled into a runnable voice pipeline.

- **Phase 1** — a UI to edit the node graph and place a test call.
- **Phase 2** — an AI Composer that generates and iterates on agents from natural language.

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

## Layout

| Path | Responsibility |
| --- | --- |
| `backend/bot.py` | The voice pipeline (WebRTC + ElevenLabs STT/TTS + OpenAI LLM). Runs the agent sent with the connect request, or the default agent. No graph logic lives here. |
| `backend/agent_builder/` | All agent-building code. `schema.py` = the declarative `AgentConfig` / `Node` / `Edge` contract; `validation.py` = every problem with an agent, as `{message, node, edge}` records; `builder.py` = `AgentBuilder`, which validates the JSON and compiles it into a Pipecat Flows graph. |
| `backend/composer_api.py` | The editor's agents API, served by the runner under `/composer` (list, get, save, validate, health). |
| `backend/agents/` | Agents **as data**, one JSON file each. `prosper-scheduler.json` is the example clinic scheduler and the default agent. |
| `frontend/` | The graph editor and test-call panel (Vite + React + TypeScript). In development Vite proxies `/composer`, `/start`, `/sessions` and `/api` to the runner. |
