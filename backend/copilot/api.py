#
# Workspaces API under /copilot (ADR 0013, ADR 0014), served by the runner like the
# agents API. Only what #28 needs to read and fill a workspace; the routes that
# change the spec come with #29 and #31, and test runs with #30.
#

from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .workspace import WORKSPACES_DIR, Workspace

MAX_GUIDELINES = 200_000  # characters: a long client document is about 20,000


class Guidelines(BaseModel):
    text: str = Field(max_length=MAX_GUIDELINES)


def make_router(root: Path = WORKSPACES_DIR) -> APIRouter:
    router = APIRouter(prefix="/copilot/workspaces/{agent_id}")

    def workspace(agent_id: str) -> Workspace:
        try:
            return Workspace(agent_id, root)
        except ValueError as error:
            raise HTTPException(400, str(error))

    @router.get("/guidelines")
    async def get_guidelines(agent_id: str):
        return {"text": workspace(agent_id).guidelines()}

    @router.put("/guidelines")
    async def put_guidelines(agent_id: str, body: Guidelines):
        workspace(agent_id).save_guidelines(body.text)
        return {"text": body.text}

    @router.get("/spec")
    async def get_spec(agent_id: str):
        return workspace(agent_id).spec()

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
