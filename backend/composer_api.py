#
# Agents API for the editor, served by the Pipecat runner under /composer (ADR 0005).
#
# Agents are JSON files in one folder. The URL id is the file stem, kept separate
# from the agent's display name so a rename never moves the file. Files are stored
# exactly as received (after validation), so editor-only keys such as node `ui`
# positions round-trip untouched (ADR 0002).
#

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body, HTTPException
from fastapi.responses import JSONResponse

from agent_builder import validate_agent

# Lowercase slug. Rules out path separators and '..', so ids are safe file names.
AGENT_ID_RE = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}")
REQUIRED_KEYS = ("OPENAI_API_KEY", "ELEVENLABS_API_KEY")


def make_router(agents_dir: Path) -> APIRouter:
    router = APIRouter(prefix="/composer")

    def agent_path(agent_id: str) -> Path:
        if not AGENT_ID_RE.fullmatch(agent_id):
            raise HTTPException(400, "Agent id must be a lowercase slug: a-z, 0-9, '-', '_'.")
        return agents_dir / f"{agent_id}.json"

    def validation_response(errors) -> JSONResponse:
        return JSONResponse({"errors": [e.to_dict() for e in errors]}, status_code=422)

    @router.get("/agents")
    async def list_agents():
        agents = []
        for path in sorted(agents_dir.glob("*.json")):
            if not AGENT_ID_RE.fullmatch(path.stem):
                continue
            try:
                name = json.loads(path.read_text()).get("name")
            except (OSError, ValueError, AttributeError):
                name = None  # unreadable file: still listed, so it can be fixed or replaced
            agents.append({"id": path.stem, "name": name})
        return {"agents": agents}

    @router.get("/agents/{agent_id}")
    async def get_agent(agent_id: str):
        path = agent_path(agent_id)
        if not path.is_file():
            raise HTTPException(404, f"No agent '{agent_id}'.")
        return json.loads(path.read_text())

    @router.put("/agents/{agent_id}")
    async def save_agent(agent_id: str, agent: Any = Body(...)):
        path = agent_path(agent_id)
        errors = validate_agent(agent)
        if errors:
            return validation_response(errors)
        _write_atomic(path, json.dumps(agent, indent=2, ensure_ascii=False) + "\n")
        return {"id": agent_id, "name": agent["name"]}

    @router.post("/validate")
    async def validate(agent: Any = Body(...)):
        # 200 either way: an invalid agent is the answer here, not a failed request.
        return {"errors": [e.to_dict() for e in validate_agent(agent)]}

    @router.get("/health")
    async def health():
        # Reads the process environment (loaded from backend/.env at startup),
        # because that is what the bot will use. Never returns values.
        missing = [key for key in REQUIRED_KEYS if not os.environ.get(key)]
        return {"ok": not missing, "missing_keys": missing}

    return router


def _write_atomic(path: Path, text: str) -> None:
    """Write via a temp file in the same folder, so readers never see a half-written agent."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.stem}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        os.unlink(tmp)
        raise
