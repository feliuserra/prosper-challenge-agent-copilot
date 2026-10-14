#
# One call in text, agent side (ADR 0009).
#
# Node configs and function handlers come from AgentBuilder, the code the live bot
# runs, so each node offers the same functions with the same schemas and an edge
# or a tool does the same thing. What Pipecat Flows then does with them is
# mirrored here:
#   - entering a node: tts_say pre-actions are spoken, the role message becomes
#     the system message (an empty one keeps the last), the task messages are
#     appended to the history and the node's functions replace the tools; then
#     the model replies (pipecat_flows/manager.py, _set_node and _update_llm_context);
#   - an edge's handler returns the next node, entered at once; a tool's returns
#     none, so the model runs again with the result (manager.py:480-520);
#   - calls go into the history the way Pipecat's assistant aggregator writes them
#     for Flows functions, which are async tools: the call, a "started" tool
#     message, and the result as a developer message
#     (pipecat/processors/aggregators/llm_response_universal.py:1624-1798);
#   - post-actions run after the node's first reply: tts_say is spoken and
#     end_conversation ends the call (pipecat_flows/actions.py).
#
# Not modelled: interruptions, timing, and the order of a reply's words and its
# calls when one reply has both (live it depends on timing; here words come
# first). #28 compares a recorded live call with this rebuild.
#
# Each agent turn keeps the exact system message, history and tools the model was
# given (the flight recorder, ADR 0015), so a turn can be rebuilt and replayed.
#

import copy
import json
from types import SimpleNamespace

from pipecat.processors.aggregators import async_tool_messages
from pipecat.services.llm_service import LLMService

from agent_builder import AgentBuilder
from clinic import TOOLS, ClinicWorld

from . import config
from .llm import Models, Usage


class ReplayError(ValueError):
    """A recorded call cannot be rebuilt with this agent (a node it went through is missing)."""


class _FlowManager:
    """What the builder's handlers touch: the shared state and the worker's frame queue."""

    def __init__(self):
        self.state: dict = {}
        self.worker = SimpleNamespace(queue_frame=self._queue_frame)

    async def _queue_frame(self, frame) -> None:
        pass  # the UI's transition and tool_call messages; the turns record the same


class Conversation:
    def __init__(self, agent: dict, world: ClinicWorld, models: Models):
        self.world = world
        self.initial_world = world.to_dict()
        self.builder = AgentBuilder.from_dict(agent, world)
        self.models = models
        self.usage = Usage()
        self.flow = _FlowManager()
        self._tools_by_node = {n.name: set(n.tools) for n in self.builder.config.nodes}

        self.start_node = self.builder.config.initial_node
        self.node = ""
        self.system: str | None = None
        self.messages: list[dict] = []
        self.tools: list[dict] = []
        self.functions: dict = {}
        self.turns: list[dict] = []
        self.ended: str | None = None
        self._in_transfer = False
        self._post_actions: list | None = None

    # ---- running ---------------------------------------------------------------
    async def start(self) -> None:
        """Enter the start node and let the agent speak first, as the bot does on connect."""
        await self.run_agent((self.builder.build_node(self.start_node), False))

    def caller_says(self, text: str, **extra) -> None:
        self.turns.append({"turn": len(self.turns) + 1, "speaker": "caller", "text": text, **extra})
        self.messages.append({"role": "user", "content": text})

    def end(self, reason: str) -> None:
        if self.ended is None:
            self.ended = reason

    async def run_agent(self, entering: tuple[dict, bool] | None = None) -> None:
        """Run the model until it waits for the caller, or the call ends. `entering` is
        a node to enter first and whether it is the transfer node."""
        steps = 0
        while self.ended is None:
            if entering is not None:
                self._enter(*entering)
                entering = None
                if self.ended:
                    return
            if steps == config.MAX_AGENT_STEPS:
                self.end("agent_loop")
                return
            steps += 1
            turn, entering = await self._model_turn()
            self._after_reply()
            if self.ended:
                return
            if entering is None and not any(call["kind"] != "ignored" for call in turn["calls"]):
                return

    def request(self) -> dict:
        """The chat request the model gets now, as Pipecat's OpenAI service builds it."""
        system = [{"role": "system", "content": self.system}] if self.system else []
        request = {"model": self.builder.config.model, "messages": system + self.messages}
        if self.tools:
            request["tools"] = self.tools
        return request

    def kind_of(self, name: str) -> str:
        """How the current node treats a function the model called: tool, edge or unknown."""
        if name not in self.functions:
            return "unknown"
        return "tool" if name in self._tools_by_node.get(self.node, ()) else "edge"

    def context(self) -> dict:
        """What the model is given at this point, without the model parameters."""
        return copy.deepcopy({"system": self.system, "messages": self.messages, "tools": self.tools})

    def record(self) -> dict:
        """The call as a record: what replay_turn and continue_from start from."""
        return {
            "agent": self.builder.config.name,
            "start_node": self.start_node,
            "date_line": self.world.date_line(),
            "world": self.initial_world,
            "end_reason": self.ended,
            "turns": self.turns,
        }

    # ---- node entry and actions ----------------------------------------------------
    def _enter(self, node: dict, transfer: bool = False, replaying: bool = False) -> None:
        self.node = node["name"]
        self._in_transfer = transfer
        for action in node.get("pre_actions", []):
            self._action(action, replaying)
            if self.ended:
                return
        if node.get("role_message"):
            self.system = node["role_message"]
        self.messages.extend(copy.deepcopy(node["task_messages"]))
        self.functions = {f.name: f for f in node.get("functions", [])}
        self.tools = [{"type": "function", "function": f.to_function_schema().to_default_dict()} for f in self.functions.values()]
        self._post_actions = list(node.get("post_actions", []))

    def _after_reply(self, replaying: bool = False) -> None:
        actions, self._post_actions = self._post_actions or [], None
        for action in actions:
            self._action(action, replaying)
            if self.ended:
                return

    def _action(self, action: dict, replaying: bool) -> None:
        kind = action.get("type")
        if kind in ("tts_say", "end_conversation") and action.get("text"):
            if action.get("append_text_to_context", True):
                self.messages.append({"role": "assistant", "content": action["text"]})
            if not replaying:
                self.turns.append(
                    {"turn": len(self.turns) + 1, "speaker": "agent", "node": self.node, "text": action["text"], "source": kind}
                )
        if kind == "end_conversation" and not replaying:
            self.end("transfer" if self._in_transfer else "end_node")
        # Other actions (functions, custom handlers) have no effect in text.

    # ---- one model call ----------------------------------------------------------------
    async def _model_turn(self) -> tuple[dict, tuple[dict, bool] | None]:
        context = self.context()
        completion = await self.models.agent.complete(self.request())
        self.usage.add(completion)
        turn = {
            "turn": len(self.turns) + 1,
            "speaker": "agent",
            "node": self.node,
            "text": completion.text,
            "calls": [],
            "context": context,
            "model": completion.model,
        }
        self.turns.append(turn)
        if completion.text:
            self.messages.append({"role": "assistant", "content": completion.text})

        next_node = None
        for tool_call in completion.tool_calls:
            call = {"id": tool_call.id, "name": tool_call.name}
            try:
                args = json.loads(tool_call.arguments or "{}")
            except json.JSONDecodeError:
                args = None
            if not isinstance(args, dict):
                # Pipecat drops a call whose arguments are not JSON (base_llm.py:536-540).
                turn["calls"].append({**call, "kind": "ignored", "arguments": tool_call.arguments})
                continue
            call["args"] = args
            function = self.functions.get(tool_call.name)
            if function is None:
                call.update(kind="unknown", result=LLMService.MISSING_FUNCTION_CALL_MESSAGE_TEMPLATE.format(function_name=tool_call.name))
                turn["calls"].append(call)
                self._add_call_messages(call)
                continue
            call["kind"] = self.kind_of(tool_call.name)
            try:
                result, node = await function.handler(args, self.flow)
            except Exception as error:  # as Flows does: the model reads the error
                result, node = {"status": "error", "error": str(error)}, None
            call["result"] = result
            if node is not None:
                if call["kind"] == "edge":
                    call["to"] = node["name"]
                next_node = (node, call["kind"] == "tool")  # the last transition wins, as in Flows
            turn["calls"].append(call)
            self._add_call_messages(call)
        return turn, next_node

    def _add_call_messages(self, call: dict) -> None:
        self.messages.append(
            {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": call["id"],
                        "function": {"name": call["name"], "arguments": json.dumps(call["args"], ensure_ascii=False)},
                        "type": "function",
                    }
                ],
            }
        )
        if call["kind"] == "unknown":
            # Pipecat's missing-function handler is a plain (not async) tool.
            self.messages.append(
                {"role": "tool", "content": json.dumps(call["result"], ensure_ascii=False), "tool_call_id": call["id"]}
            )
            return
        result = json.dumps(call["result"], ensure_ascii=False) if call["result"] else "COMPLETED"
        self.messages.append(async_tool_messages.build_started_message(call["id"]))
        self.messages.append(async_tool_messages.build_final_result_message(call["id"], result))

    # ---- rebuilding a recorded call --------------------------------------------------
    @classmethod
    def rebuild(cls, record: dict, agent: dict, before_turn: int, models: Models) -> "Conversation":
        """The call as it stood just before `before_turn`, with `agent` in place of the
        agent that ran it. The history is the record's (words, calls and their results);
        the system message, task messages and tools come from `agent`. The clinic is
        brought to that point by redoing the recorded changes on the record's world.
        With the agent that ran the call, the context equals the recorded one."""
        conversation = cls(agent, ClinicWorld(record["world"]), models)
        try:
            conversation._enter(conversation.builder.build_node(record["start_node"]), replaying=True)
            for turn in record["turns"]:
                if turn["turn"] >= before_turn:
                    break
                conversation._replay(turn)
        except KeyError as error:
            raise ReplayError(f"Node {error} is not in the agent '{conversation.builder.config.name}'.") from None
        conversation.turns = copy.deepcopy([t for t in record["turns"] if t["turn"] < before_turn])
        return conversation

    def _replay(self, turn: dict) -> None:
        if turn["speaker"] == "caller":
            self.messages.append({"role": "user", "content": turn["text"]})
            return
        if turn.get("source"):
            return  # an action's line: entering the node said it again
        if turn["text"]:
            self.messages.append({"role": "assistant", "content": turn["text"]})
        next_node = None
        for call in turn["calls"]:
            if call["kind"] == "ignored":
                continue
            self._add_call_messages(call)
            if call["kind"] == "edge":
                next_node = (self.builder.build_node(call["to"]), False)
            elif call["kind"] == "tool":
                spec = TOOLS[call["name"]]
                failed = isinstance(call["result"], dict) and "error" in call["result"]
                if spec.changes_world and not failed:
                    self.world.call(call["name"], call["args"])
                if spec.ends_call and not failed:
                    next_node = (self.builder.build_transfer_node(self.node), True)
        self._after_reply(replaying=True)
        if next_node is not None:
            self._enter(*next_node, replaying=True)
