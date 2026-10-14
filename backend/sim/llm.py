#
# The one door to the models. The agent, the caller and the judge all send an
# OpenAI chat request (a dict) and get a Completion back, so unit tests swap in a
# scripted model and `make test` never touches the network.
#

import asyncio
import json
from dataclasses import dataclass, field
from typing import Protocol

from . import config


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: str  # raw JSON, as the model wrote it


@dataclass
class Completion:
    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    model: str = ""  # the dated version that answered
    input_tokens: int = 0
    output_tokens: int = 0


class ChatModel(Protocol):
    async def complete(self, request: dict) -> Completion: ...


class ModelError(Exception):
    """A request that still failed after the client's retries. The test is reported
    as `error`, never as the agent failing (ADR 0010)."""


@dataclass
class Models:
    """Where each role's requests go. All three are one OpenAIChat in real runs."""

    agent: ChatModel
    caller: ChatModel
    judge: ChatModel


class OpenAIChat:
    def __init__(self, client=None, max_parallel: int = config.MAX_PARALLEL_REQUESTS):
        if client is None:
            from openai import AsyncOpenAI

            # Reads OPENAI_API_KEY from the environment.
            client = AsyncOpenAI(max_retries=config.MAX_RETRIES, timeout=config.REQUEST_TIMEOUT_SECS)
        self._client = client
        self._limit = asyncio.Semaphore(max_parallel)

    async def complete(self, request: dict) -> Completion:
        import openai

        async with self._limit:
            try:
                response = await self._client.chat.completions.create(**request)
            except openai.APIError as error:
                # Status and message only: never repr an HTTP error, it can carry
                # request headers (handoff, section 4).
                status = getattr(error, "status_code", None)
                raise ModelError(f"{type(error).__name__}{f' {status}' if status else ''}: {error.message}") from None
        message = response.choices[0].message
        return Completion(
            text=message.content or "",
            tool_calls=[
                ToolCall(id=call.id, name=call.function.name, arguments=call.function.arguments)
                for call in message.tool_calls or []
            ],
            model=response.model,
            input_tokens=response.usage.prompt_tokens if response.usage else 0,
            output_tokens=response.usage.completion_tokens if response.usage else 0,
        )


def models() -> Models:
    chat = OpenAIChat()
    return Models(agent=chat, caller=chat, judge=chat)


def json_request(model: str, messages: list[dict], name: str, schema: dict, **params) -> dict:
    """A request whose answer is JSON matching `schema` (structured outputs)."""
    return {
        "model": model,
        "messages": messages,
        "response_format": {"type": "json_schema", "json_schema": {"name": name, "strict": True, "schema": schema}},
        **params,
    }


def parse_json(completion: Completion) -> dict:
    try:
        return json.loads(completion.text)
    except json.JSONDecodeError:
        raise ModelError(f"{completion.model or 'model'} answered with invalid JSON: {completion.text[:200]!r}") from None


class Usage:
    """Tokens and requests per model version, for the time and cost report."""

    def __init__(self, data: dict | None = None):
        self.data: dict[str, dict] = {k: dict(v) for k, v in (data or {}).items()}

    def add(self, completion: Completion) -> None:
        entry = self.data.setdefault(completion.model or "unknown", {"requests": 0, "input": 0, "output": 0})
        entry["requests"] += 1
        entry["input"] += completion.input_tokens
        entry["output"] += completion.output_tokens

    def merge(self, other: "Usage | dict") -> None:
        for model, entry in (other.data if isinstance(other, Usage) else other).items():
            mine = self.data.setdefault(model, {"requests": 0, "input": 0, "output": 0})
            for key in mine:
                mine[key] += entry.get(key, 0)

    def cost(self) -> float | None:
        """Estimated USD, or None when a model has no price in config.PRICES."""
        total = 0.0
        for model, entry in self.data.items():
            prices = config.price(model)
            if prices is None:
                return None
            total += (entry["input"] * prices[0] + entry["output"] * prices[1]) / 1_000_000
        return total
