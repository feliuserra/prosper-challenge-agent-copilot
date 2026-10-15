#
# Workspaces API under /copilot (ADR 0013, ADR 0014), served by the runner like the
# agents API. #28 reads and fills a workspace; #29 adds the spec step, streamed as
# server-sent events, and the spec changes #31 needs (approve tests, delete a test or a
# requirement). Test runs come with #30.
#
#   POST   .../spec                      run the spec step: an event stream (below)
#   PATCH  .../spec/tests                {"status": "approved"} approves every draft test
#   PATCH  .../spec/tests/{test_id}      the same for one test
#   DELETE .../spec/tests/{test_id}
#   DELETE .../spec/requirements/{id}    and the draft tests that checked only it
#
# The stream sends `event: <type>` and `data: <json>` per event: `part` (a part running,
# then done with its result), `repair` (problems sent back to the model), then `done`
# with the spec, or `error`. Problems before the stream starts (no guidelines, approved
# tests in the way, a step already running) are plain HTTP errors.
#

import asyncio
import json
from pathlib import Path
from typing import Callable, Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from loguru import logger
from openai import OpenAIError
from pydantic import BaseModel, ConfigDict, Field

from sim.llm import ChatModel, ModelError, OpenAIChat

from . import spec as spec_step
from .workspace import WORKSPACES_DIR, Workspace

MAX_GUIDELINES = 200_000  # characters: a long client document is about 20,000


class Guidelines(BaseModel):
    text: str = Field(max_length=MAX_GUIDELINES)


class SpecRun(BaseModel):
    replace_approved: bool = False  # the person confirmed that approved tests may go


class TestPatch(BaseModel):
    # Approving is the only change: approved tests are locked, and draft tests change
    # through the guidelines and a new spec step (#31's cuts).
    model_config = ConfigDict(extra="forbid")
    status: Literal["approved"]


def make_router(root: Path = WORKSPACES_DIR, model: Callable[[], ChatModel] = lambda: OpenAIChat("copilot")) -> APIRouter:
    router = APIRouter(prefix="/copilot/workspaces/{agent_id}")
    running: set[str] = set()  # workspaces with a spec step in progress

    def workspace(agent_id: str) -> Workspace:
        try:
            return Workspace(agent_id, root)
        except ValueError as error:
            raise HTTPException(400, str(error))

    def with_gaps(spec: dict) -> dict:
        return {**spec, "gaps": spec_step.gaps(spec)}

    def change(agent_id: str, edit) -> dict:
        """Apply `edit(spec)` to the stored spec and write it, under the lock on approved tests."""
        ws = workspace(agent_id)
        if agent_id in running:
            raise HTTPException(409, "A spec step is running for this workspace.")
        spec = ws.spec()
        try:
            result = edit(spec)
            spec_step.write(ws, spec)
        except spec_step.SpecError as error:
            raise HTTPException(error.status, str(error))
        return {"spec": with_gaps(spec), **(result or {})}

    @router.get("/guidelines")
    async def get_guidelines(agent_id: str):
        return {"text": workspace(agent_id).guidelines()}

    @router.put("/guidelines")
    async def put_guidelines(agent_id: str, body: Guidelines):
        workspace(agent_id).save_guidelines(body.text)
        return {"text": body.text}

    @router.get("/spec")
    async def get_spec(agent_id: str):
        return with_gaps(workspace(agent_id).spec())

    @router.post("/spec")
    async def run_spec(agent_id: str, body: SpecRun | None = None):
        ws = workspace(agent_id)
        replace = bool(body and body.replace_approved)
        if agent_id in running:
            raise HTTPException(409, "A spec step is already running for this workspace.")
        if not ws.guidelines().strip():
            raise HTTPException(400, "The workspace has no guidelines yet. Paste the client's guidelines first.")
        approved = [t for t in ws.spec().get("tests", []) if t.get("status") == "approved"]
        if approved and not replace:
            raise HTTPException(
                409, f"{len(approved)} approved test(s) would be replaced. Approved tests are locked: confirm to replace them."
            )
        return StreamingResponse(
            stream(ws, model, replace, running),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @router.patch("/spec/tests")
    async def approve_all(agent_id: str, body: TestPatch):
        return change(agent_id, lambda spec: {"approved": spec_step.approve(spec)})

    @router.patch("/spec/tests/{test_id}")
    async def approve_one(agent_id: str, test_id: str, body: TestPatch):
        return change(agent_id, lambda spec: {"approved": spec_step.approve(spec, test_id)})

    @router.delete("/spec/tests/{test_id}")
    async def delete_test(agent_id: str, test_id: str):
        return change(agent_id, lambda spec: spec_step.delete_test(spec, test_id))

    @router.delete("/spec/requirements/{requirement_id}")
    async def delete_requirement(agent_id: str, requirement_id: str):
        return change(agent_id, lambda spec: {"deleted_tests": spec_step.delete_requirement(spec, requirement_id)})

    @router.get("/versions")
    async def list_versions(agent_id: str):
        return {"versions": workspace(agent_id).versions()}

    @router.get("/versions/{number}")
    async def get_version(agent_id: str, number: int):
        version = workspace(agent_id).version(number) if number > 0 else None
        if version is None:
            raise HTTPException(404, f"No version {number} of '{agent_id}'.")
        return version

    return router


async def stream(ws: Workspace, model: Callable[[], ChatModel], replace_approved: bool, running: set[str]):
    """Run the spec step and yield its events as server-sent events. A client that goes
    away cancels the step; nothing is written then."""
    if ws.id in running:  # checked and marked with no await in between
        yield sse({"event": "error", "part": None, "message": "A spec step is already running for this workspace.", "problems": []})
        return
    running.add(ws.id)
    events: asyncio.Queue = asyncio.Queue()
    task = asyncio.create_task(_run(ws, model, replace_approved, events.put_nowait))
    try:
        while True:
            event = await events.get()
            yield sse(event)
            if event["event"] in ("done", "error"):
                break
    finally:
        task.cancel()
        running.discard(ws.id)


def sse(event: dict) -> str:
    return f"event: {event['event']}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"


async def _run(ws: Workspace, model: Callable[[], ChatModel], replace_approved: bool, emit) -> None:
    try:
        spec = await spec_step.run(ws, model(), emit, replace_approved=replace_approved)
        emit({"event": "done", "spec": {**spec, "gaps": spec_step.gaps(spec)}})
    except spec_step.SpecError as error:
        emit({"event": "error", "part": error.part, "message": str(error), "problems": error.problems})
    except ModelError as error:
        emit({"event": "error", "part": None, "message": f"The model could not be reached: {error}", "problems": []})
    except OpenAIError as error:  # no key: the client cannot be built
        emit({"event": "error", "part": None, "message": f"No model client: {type(error).__name__}.", "problems": []})
    except asyncio.CancelledError:
        raise
    except Exception as error:  # never leave the stream without an end
        logger.exception("spec step failed")
        emit({"event": "error", "part": None, "message": f"{type(error).__name__}: {error}", "problems": []})
