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
from typing import Any, Awaitable, Callable

import aiohttp
from fastapi import APIRouter, Body, HTTPException
from fastapi.responses import JSONResponse
from loguru import logger

from agent_builder import validate_agent

# Lowercase slug. Rules out path separators and '..', so ids are safe file names.
AGENT_ID_RE = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}")
REQUIRED_KEYS = ("OPENAI_API_KEY", "ELEVENLABS_API_KEY")

ELEVENLABS_VOICES_URL = "https://api.elevenlabs.io/v2/voices"
VOICE_PAGES = 5  # 100 voices per page

VoiceFetcher = Callable[[str], Awaitable[list[dict]]]


class VoiceListError(Exception):
    """Why the voices could not be listed. Safe to log and show: never holds the key."""


def http_error_message(status: int, body: str) -> str:
    # Built from the status and ElevenLabs' own message only. Never format an
    # aiohttp exception here: its repr carries the request headers, key included.
    try:
        detail = json.loads(body).get("detail", {})
        message = detail.get("message") if isinstance(detail, dict) else str(detail)
    except (ValueError, AttributeError):
        message = None
    return f"ElevenLabs answered HTTP {status}" + (f": {message}" if message else ".")


async def fetch_elevenlabs_voices(api_key: str) -> list[dict]:
    """The voices this ElevenLabs account can use, as {id, name, category}."""
    voices: list[dict] = []
    params = {"page_size": "100"}
    timeout = aiohttp.ClientTimeout(total=10)
    async with aiohttp.ClientSession(headers={"xi-api-key": api_key}, timeout=timeout) as session:
        for _ in range(VOICE_PAGES):
            async with session.get(ELEVENLABS_VOICES_URL, params=params) as response:
                if response.status != 200:
                    raise VoiceListError(http_error_message(response.status, (await response.text())[:1000]))
                data = await response.json()
            voices += [
                {"id": v["voice_id"], "name": v.get("name") or v["voice_id"], "category": v.get("category")}
                for v in data.get("voices", [])
            ]
            if not data.get("has_more") or not data.get("next_page_token"):
                break
            params["next_page_token"] = data["next_page_token"]
    return voices


def make_router(agents_dir: Path, fetch_voices: VoiceFetcher = fetch_elevenlabs_voices) -> APIRouter:
    router = APIRouter(prefix="/composer")
    voices_cache: list[dict] = []

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

    @router.get("/voices")
    async def voices():
        # The account's own voices for the editor's voice picker: a mistyped
        # voice_id gives a silent bot, and ElevenLabs keeps retiring default
        # voices, so a hard-coded list would go stale. Listing voices uses no
        # character quota. Fetched once per process; failures are not cached.
        if not voices_cache:
            api_key = os.environ.get("ELEVENLABS_API_KEY")
            if not api_key:
                return {"voices": [], "error": "ELEVENLABS_API_KEY is not set."}
            try:
                voices_cache.extend(await fetch_voices(api_key))
            except VoiceListError as error:
                logger.warning(f"Could not list ElevenLabs voices: {error}")
                return {"voices": [], "error": str(error)}
            except Exception as error:
                # Only the type: exception messages from HTTP clients can carry headers.
                logger.warning(f"Could not list ElevenLabs voices: {type(error).__name__}")
                return {"voices": [], "error": f"Could not reach ElevenLabs ({type(error).__name__})."}
        return {"voices": voices_cache}

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
