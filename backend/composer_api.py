#
# Agents API for the editor, served by the Pipecat runner under /composer (ADR 0005).
#
# Agents are JSON files in one folder. The URL id is the file stem, kept separate
# from the agent's display name so a rename never moves the file. Files are stored
# exactly as received (after validation), so editor-only keys such as node `ui`
# positions round-trip untouched (ADR 0002). With a workspaces folder, each save that
# changes what the agent does also adds a version to its workspace (ADR 0013, #28).
#

import json
import os
from pathlib import Path
from typing import Any, Awaitable, Callable

import aiohttp
from fastapi import APIRouter, Body, HTTPException
from fastapi.responses import JSONResponse
from loguru import logger

from agent_builder import validate_agent
from clinic import catalog, clinic_ids, seed_path, validate_clinic
from copilot.workspace import Workspace
from storage import AGENT_ID_RE, write_atomic

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


def make_router(
    agents_dir: Path, fetch_voices: VoiceFetcher = fetch_elevenlabs_voices, workspaces_dir: Path | None = None
) -> APIRouter:
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
        write_atomic(path, json.dumps(agent, indent=2, ensure_ascii=False) + "\n")
        if workspaces_dir is None:
            return {"id": agent_id, "name": agent["name"]}
        version, _ = Workspace(agent_id, workspaces_dir).add_version(agent, "editor")
        return {"id": agent_id, "name": agent["name"], "version": version["number"]}

    @router.post("/validate")
    async def validate(agent: Any = Body(...)):
        # 200 either way: an invalid agent is the answer here, not a failed request.
        return {"errors": [e.to_dict() for e in validate_agent(agent)]}

    @router.get("/tools")
    async def tools():
        # The tool catalog for the node panel (ADR 0008). Fixed, so no caching needed.
        return {"tools": catalog()}

    @router.get("/clinics")
    async def list_clinics():
        # For the agent panel's clinic select (ADR 0016). Read on every request,
        # so a clinic file added or renamed shows without a restart.
        clinics = []
        for clinic_id in clinic_ids():
            try:
                name = json.loads(seed_path(clinic_id).read_text())["clinic"]["name"]
            except (OSError, ValueError, KeyError, TypeError):
                name = None  # broken file: still listed, so the Clinic tab can show why
            clinics.append({"id": clinic_id, "name": name if isinstance(name, str) else None})
        return {"clinics": clinics}

    @router.get("/clinics/{clinic_id}")
    async def get_clinic(clinic_id: str):
        # The clinic file as it is (seed plus configuration) and every problem the
        # loader finds in it, for the read-only Clinic tab.
        try:
            path = seed_path(clinic_id)
        except KeyError:
            raise HTTPException(404, f"No clinic '{clinic_id}'.")
        try:
            data = json.loads(path.read_text())
        except ValueError as error:
            return {"id": clinic_id, "clinic": None, "problems": [{"path": "", "message": f"Not valid JSON: {error}"}]}
        return {"id": clinic_id, "clinic": data, "problems": [i.to_dict() for i in validate_clinic(data)]}

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

