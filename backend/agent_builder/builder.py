#
# AgentBuilder — loads a declarative agent (JSON / dict) and compiles its node
# graph into Pipecat Flows objects.
#
#   JSON  ->  AgentConfig (validated)  ->  Pipecat Flows NodeConfig graph
#
# This is the seam between "agent as data" (what the Phase 2 Composer produces)
# and "agent as a running conversation" (what bot.py executes). Keeping the
# compile + validation here means bot.py never touches the graph internals.
#
# Tools (ADR 0008) run against a clinic: anything with `call(name, args)` and
# `date_line()`, such as the live clinic in bot.py or a fresh ClinicWorld in a
# test. The clinic's date is added to every node's system message.
#

import json
from dataclasses import asdict
from pathlib import Path
from typing import Optional, Protocol, Union

from loguru import logger
from pipecat.processors.frameworks.rtvi import RTVIServerMessageFrame
from pipecat_flows import FlowManager, FlowsFunctionSchema, NodeConfig

from clinic.catalog import TOOLS

from .schema import AgentConfig, Edge, Node
from .validation import ValidationError, validate_agent


# Said by the bot after transfer_to_human, before the call ends.
TRANSFER_TASK = (
    "Tell the caller in one short sentence that you are transferring them to a member of the "
    "clinic staff now. Do not ask anything else."
)


class Clinic(Protocol):
    def call(self, name: str, args: dict) -> dict: ...
    def date_line(self) -> str: ...


class AgentBuilder:
    """Builds a runnable Pipecat Flows graph from a declarative AgentConfig."""

    def __init__(self, config: AgentConfig, clinic: Optional[Clinic] = None):
        self.config = config
        self.clinic = clinic
        self._nodes_by_name = {n.name: n for n in config.nodes}
        self._validate()

    # ---- loading -----------------------------------------------------------
    @classmethod
    def from_dict(cls, data: dict, clinic: Optional[Clinic] = None) -> "AgentBuilder":
        # Validate the raw dict first: from_dict would raise KeyError on the first
        # missing key and hide every other problem.
        cls._raise_if_invalid(data)
        return cls(AgentConfig.from_dict(data), clinic)

    @classmethod
    def from_json(cls, path: Union[str, Path], clinic: Optional[Clinic] = None) -> "AgentBuilder":
        data = json.loads(Path(path).read_text())
        return cls.from_dict(data, clinic)

    # ---- validation --------------------------------------------------------
    def _validate(self) -> None:
        self._raise_if_invalid(asdict(self.config))

    @staticmethod
    def _raise_if_invalid(data: dict) -> None:
        errors = validate_agent(data)
        if errors:
            raise ValidationError(errors)

    # ---- compilation -------------------------------------------------------
    def build_initial_node(self) -> NodeConfig:
        """Return the entry NodeConfig; downstream nodes are built lazily on transition."""
        return self._make_node(self._nodes_by_name[self.config.initial_node])

    def _role_message(self, node: Node) -> str:
        role = node.role_message or self.config.persona
        if self.clinic is None:
            return role
        return f"{role}\n\n{self.clinic.date_line()}" if role else self.clinic.date_line()

    def _make_node(self, node: Node) -> NodeConfig:
        node_config: NodeConfig = {
            "name": node.name,
            "role_message": self._role_message(node),
            "task_messages": node.task_messages,
            "functions": [self._make_edge_function(node, edge) for edge in node.edges]
            + [self._make_tool_function(node, tool) for tool in node.tools],
        }
        if node.pre_actions:
            node_config["pre_actions"] = node.pre_actions
        # Explicit post_actions win; otherwise a terminal node ends the call.
        if node.post_actions:
            node_config["post_actions"] = node.post_actions
        elif node.end:
            node_config["post_actions"] = [{"type": "end_conversation"}]
        return node_config

    def _make_edge_function(self, node: Node, edge: Edge) -> FlowsFunctionSchema:
        async def handler(args: dict, flow_manager: FlowManager):
            # Persist what the caller gave us so later nodes can use it.
            flow_manager.state.update(args)
            logger.info(f"[{edge.function}] -> {edge.target} | collected: {args}")
            # Tell the UI which edge was taken (RTVI server message, ADR 0006).
            await flow_manager.worker.queue_frame(
                RTVIServerMessageFrame(
                    data={
                        "type": "transition",
                        "from": node.name,
                        "function": edge.function,
                        "to": edge.target,
                        "args": args,
                    }
                )
            )
            next_node = self._make_node(self._nodes_by_name[edge.target])
            return {"status": "success", **args}, next_node

        return FlowsFunctionSchema(
            name=edge.function,
            description=edge.description,
            properties=edge.properties,
            required=edge.required,
            handler=handler,
        )

    def _make_tool_function(self, node: Node, tool: str) -> FlowsFunctionSchema:
        spec = TOOLS[tool]

        async def handler(args: dict, flow_manager: FlowManager):
            if self.clinic is None:
                result = {"error": "No clinic is connected, so tools cannot run."}
            else:
                result = self.clinic.call(tool, args)
            logger.info(f"[{tool}] in {node.name} | args: {args} | result: {result}")
            await flow_manager.worker.queue_frame(
                RTVIServerMessageFrame(
                    data={"type": "tool_call", "node": node.name, "tool": tool, "args": args, "result": result}
                )
            )
            if spec.ends_call and "error" not in result:
                return result, self._transfer_node(node)
            # No next node: the conversation stays here and the model answers with the result.
            return result, None

        return FlowsFunctionSchema(
            name=tool,
            description=spec.description,
            properties=spec.properties,
            required=list(spec.required),
            handler=handler,
        )

    def _transfer_node(self, node: Node) -> NodeConfig:
        """One line from the bot, then the call ends. Not part of the graph: the UI stays on `node`."""
        return {
            "name": "transfer_to_human",
            "role_message": self._role_message(node),
            "task_messages": [{"role": "developer", "content": TRANSFER_TASK}],
            "functions": [],
            "post_actions": [{"type": "end_conversation"}],
        }
