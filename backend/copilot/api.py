#
# Workspaces API under /copilot (ADR 0013, ADR 0014), served by the runner like the
# agents API. #28 reads and fills a workspace; #29 adds the spec step, streamed as
# server-sent events, and the spec changes #31 needs (approve tests, delete a test or a
# requirement). #30 adds the build and its proposals; #31 deciding on a proposal and
# running the tests, for the Copilot panel.
#
#   POST   .../spec                      run the spec step: an event stream (below)
#   PATCH  .../spec/tests                {"status": "approved"} approves every draft test
#   PATCH  .../spec/tests/{test_id}      the same for one test
#   DELETE .../spec/tests/{test_id}
#   DELETE .../spec/requirements/{id}    and the draft tests that checked only it
#   POST   .../build                     build the agent and loop: an event stream
#                                        ({"loop": false} builds without running tests)
#   GET    .../proposals/last            the newest proposal
#   POST   .../proposals/{n}/accept      write its agent, clinic and configuration
#                                        ({"anyway": true} for a blocked one)
#   POST   .../proposals/{n}/reject      record the decision; nothing else changes
#   POST   .../tests/run                 {"agent": ...}: run the approved tests on it, a stream
#   GET    .../runs/last                 the newest test run, summarized
#
# The stream sends `event: <type>` and `data: <json>` per event: `part` (a part running,
# then done with its result), `repair` (problems sent back to the model), then `done`
# with the spec, or `error`. The build adds `operation` (the agent after each one),
# `tests` (a test run) and `round`, and ends with `done` and the proposal. A test run
# sends `test` as each test ends, then `done` with the run. Problems
# before the stream starts (no guidelines, approved tests in the way, a step already
# running) are plain HTTP errors. One step at a time per workspace.
#
# With COPILOT_REPLAY set, the streams are replayed from recordings instead of running
# (recording.py): the stub backend for the panel's browser checks.
#

import asyncio
import json
import os
from pathlib import Path
from typing import Callable, Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from loguru import logger
from openai import OpenAIError
from pydantic import BaseModel, ConfigDict, Field

from sim.llm import ChatModel, ModelError, Models, OpenAIChat
from sim.llm import models as real_models

from . import build as build_step
from . import recording
from . import spec as spec_step
from .workspace import WORKSPACES_DIR, Workspace, agent_hash, now

MAX_GUIDELINES = 200_000  # characters: a long client document is about 20,000


class Guidelines(BaseModel):
    text: str = Field(max_length=MAX_GUIDELINES)


class SpecRun(BaseModel):
    replace_approved: bool = False  # the person confirmed that approved tests may go


class BuildRun(BaseModel):
    loop: bool = True  # false: the build alone, no test runs (cheap, blocked as untested)


class Decision(BaseModel):
    anyway: bool = False  # accept a proposal blocked by its tests, on purpose


class TestRun(BaseModel):
    agent: dict  # the agent as it is in the editor


class TestPatch(BaseModel):
    # Approving is the only change: approved tests are locked, and draft tests change
    # through the guidelines and a new spec step (#31's cuts).
    model_config = ConfigDict(extra="forbid")
    status: Literal["approved"]


def make_router(
    root: Path = WORKSPACES_DIR,
    model: Callable[[], ChatModel] = lambda: OpenAIChat("copilot"),
    test_models: Callable[[], Models] = lambda: real_models("copilot"),
    agents_dir: Path | None = None,
    run_tests: build_step.RunTests | None = None,
    record: Path | None = None,
    replay: Path | None = None,
) -> APIRouter:
    """`agents_dir` is where an accepted proposal's agent is written; `run_tests` replaces
    the runner in the build (unit tests). `record` and `replay` are recording folders
    (recording.py), from COPILOT_RECORD and COPILOT_REPLAY when not given."""
    record = record or _folder("COPILOT_RECORD")
    replay = replay or _folder("COPILOT_REPLAY")
    router = APIRouter(prefix="/copilot/workspaces/{agent_id}")
    running: set[str] = set()  # workspaces with a spec step or a build in progress
    if replay:
        logger.warning(f"Copilot streams are replayed from {replay}: no model calls")

    def served(ws: Workspace, step: str, work, finish):
        """The step's stream: replayed (with `finish` storing what the step would), or run
        and maybe recorded."""
        if replay:
            work = recording.replayer(replay / f"{step}.jsonl", finish)
        recorder = recording.Recorder(record / f"{step}.jsonl") if record and not replay else None
        return streaming(stream(ws, work, running, recorder))

    def not_the_template(agent_id: str) -> None:
        # Accepting writes agents/<id>.json: into the template, every later build would
        # start from that clinic's agent (#31, found in the user's first real run).
        if agent_id == build_step.TEMPLATE_ID:
            raise HTTPException(
                409,
                f"'{agent_id}' is the template every build starts from, so the Copilot does not work in it. "
                "Create an agent (New from example) and use the Copilot there.",
            )

    def saved_hash(agent_id: str) -> str | None:
        return build_step.saved_hash(agents_dir, agent_id) if agents_dir else None

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
        not_the_template(agent_id)
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
        work = lambda emit: _spec(ws, model, replace, emit)

        def finish(done):
            ws.save_spec({k: v for k, v in done["spec"].items() if k != "gaps"})
            return done

        return served(ws, "spec", work, finish)

    @router.post("/build")
    async def run_build(agent_id: str, body: BuildRun | None = None):
        ws = workspace(agent_id)
        not_the_template(agent_id)
        loop = body.loop if body else True
        if agent_id in running:
            raise HTTPException(409, "A Copilot step is already running for this workspace.")
        spec = ws.spec()
        if not spec.get("configuration"):
            raise HTTPException(400, "The spec has no configuration yet. Run the spec step first.")
        if not build_step.approved_tests(spec):
            raise HTTPException(400, "No approved tests yet. Approve the tests the agent must pass first.")
        # What the editor had saved when the build started: accepting checks it is unchanged.
        base = saved_hash(agent_id)
        work = lambda emit: build_step.run(
            ws, model(), None if run_tests or not loop else test_models(), emit, run_tests=run_tests, loop=loop, base=base
        )

        def finish(done):
            proposal = {k: v for k, v in done["proposal"].items() if k not in ("number", "decision")}
            proposal["created"] = now()
            proposal["started_from"] = {**proposal["started_from"], "agent": base}
            build_step.write_clinic(ws, proposal["configuration"])
            ws.save_proposal(proposal)
            if proposal.get("results"):
                summary = proposal["results"]["after"]
                ws.save_run({"created": now(), "agent_hash": agent_hash(proposal["agent"]), "proposal": proposal["number"], "summary": summary})
            return {**done, "proposal": proposal}

        return served(ws, "build", work, finish)

    @router.post("/tests/run")
    async def run_tests_now(agent_id: str, body: TestRun):
        ws = workspace(agent_id)
        if agent_id in running:
            raise HTTPException(409, "A Copilot step is already running for this workspace.")
        if not build_step.approved_tests(ws.spec()):
            raise HTTPException(400, "No approved tests yet. Approve the tests the agent must pass first.")
        work = lambda emit: build_step.run_workspace_tests(ws, body.agent, None if run_tests else test_models(), emit, run_tests=run_tests)

        def finish(done):
            run = {**done["run"], "created": now(), "agent_hash": agent_hash(body.agent)}
            run["number"] = ws.save_run({k: v for k, v in run.items() if k != "number"})
            return {**done, "run": run}

        return served(ws, "tests", work, finish)

    @router.get("/runs/last")
    async def last_run(agent_id: str):
        run = workspace(agent_id).last_run()
        if run is None:
            raise HTTPException(404, f"No test run for '{agent_id}' yet.")
        return build_step.run_view(run)

    @router.get("/proposals/last")
    async def last_proposal(agent_id: str):
        proposal = workspace(agent_id).last_proposal()
        if proposal is None:
            raise HTTPException(404, f"No proposal for '{agent_id}' yet.")
        return proposal

    @router.post("/proposals/{number}/accept")
    async def accept_proposal(agent_id: str, number: int, body: Decision | None = None):
        if agents_dir is None:
            raise HTTPException(501, "This server does not keep agents.")
        not_the_template(agent_id)
        if agent_id in running:
            raise HTTPException(409, "A Copilot step is running for this workspace.")
        try:
            version = build_step.accept(workspace(agent_id), number, agents_dir, anyway=bool(body and body.anyway))
        except (build_step.BuildError, spec_step.SpecError) as error:
            raise HTTPException(error.status, str(error))
        return {"version": version}

    @router.post("/proposals/{number}/reject")
    async def reject_proposal(agent_id: str, number: int):
        try:
            return {"decision": build_step.reject(workspace(agent_id), number)}
        except build_step.BuildError as error:
            raise HTTPException(error.status, str(error))

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


def _folder(variable: str) -> Path | None:
    value = os.environ.get(variable)
    return Path(value) if value else None


def streaming(events) -> StreamingResponse:
    return StreamingResponse(events, media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


async def stream(ws: Workspace, work, running: set[str], recorder: recording.Recorder | None = None):
    """Run a step, `work(emit)`, and yield its events as server-sent events. A client that
    goes away cancels the step; nothing is written then."""
    if ws.id in running:  # checked and marked with no await in between
        yield sse({"event": "error", "part": None, "message": "A Copilot step is already running for this workspace.", "problems": []})
        return
    running.add(ws.id)
    events: asyncio.Queue = asyncio.Queue()
    task = asyncio.create_task(_guarded(work, events.put_nowait))
    try:
        while True:
            event = await events.get()
            if recorder:
                recorder.add(event)
            yield sse(event)
            if event["event"] in ("done", "error"):
                break
        if recorder:
            recorder.save()
    finally:
        task.cancel()
        running.discard(ws.id)


def sse(event: dict) -> str:
    return f"event: {event['event']}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"


async def _spec(ws: Workspace, model: Callable[[], ChatModel], replace_approved: bool, emit) -> None:
    spec = await spec_step.run(ws, model(), emit, replace_approved=replace_approved)
    emit({"event": "done", "spec": {**spec, "gaps": spec_step.gaps(spec)}})


async def _guarded(work, emit) -> None:
    try:
        await work(emit)
    except spec_step.SpecError as error:
        emit({"event": "error", "part": error.part, "message": str(error), "problems": error.problems})
    except build_step.BuildError as error:
        emit({"event": "error", "part": "build", "message": str(error), "problems": error.problems})
    except ModelError as error:
        emit({"event": "error", "part": None, "message": f"The model could not be reached: {error}", "problems": []})
    except OpenAIError as error:  # no key: the client cannot be built
        emit({"event": "error", "part": None, "message": f"No model client: {type(error).__name__}.", "problems": []})
    except FileNotFoundError as error:  # a recording missing (COPILOT_REPLAY)
        emit({"event": "error", "part": None, "message": str(error), "problems": []})
    except asyncio.CancelledError:
        raise
    except Exception as error:  # never leave the stream without an end
        logger.exception("Copilot step failed")
        emit({"event": "error", "part": None, "message": f"{type(error).__name__}: {error}", "problems": []})
