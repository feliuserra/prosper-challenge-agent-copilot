#
# Voice pipeline — Prosper Product Engineer Challenge
#
# The runnable voice agent: WebRTC transport + ElevenLabs STT/TTS + OpenAI LLM,
# driven by a Pipecat Flows node graph. This file is generic — it loads an agent
# definition (JSON) via AgentBuilder and runs it. Swapping the agent is a data
# change (edit/replace the JSON), not a code change.
#
#   agent JSON  ->  AgentBuilder  ->  Pipecat Flows graph  ->  FlowManager
#
# The agent comes from the connect request (the editor's current draft) or, when
# none is sent, the default agent in agents/. This file also mounts the editor's
# agents API (composer_api.py) on the runner, so everything runs on one port.
#
# Run:  python bot.py   then open http://localhost:7860/client
#

import os
from pathlib import Path

from dotenv import load_dotenv
from loguru import logger

from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.frames.frames import EndFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams, PipelineWorker
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
)
from pipecat.runner.run import app
from pipecat.runner.types import RunnerArguments
from pipecat.runner.utils import create_transport
from pipecat.services.elevenlabs.stt import ElevenLabsRealtimeSTTService
from pipecat.services.elevenlabs.tts import ElevenLabsTTSService
from pipecat.services.openai.llm import OpenAILLMService
from pipecat.transcriptions.language import Language
from pipecat.transports.base_transport import BaseTransport, TransportParams
from pipecat.workers.runner import WorkerRunner
from pipecat_flows import FlowManager

from agent_builder import AgentBuilder, ValidationError, ValidationIssue
from composer_api import make_router

# Load .env next to this file, so the bot runs the same from the repo root or backend/.
load_dotenv(Path(__file__).parent / ".env", override=True)


# Agents the editor lists and saves. The default runs when a client connects
# without sending an agent (e.g. the prebuilt client at /client).
AGENTS_DIR = Path(__file__).parent / "agents"
DEFAULT_AGENT = AGENTS_DIR / "prosper-scheduler.json"

app.include_router(make_router(AGENTS_DIR))


transport_params = {
    "webrtc": lambda: TransportParams(audio_in_enabled=True, audio_out_enabled=True),
}


async def run_bot(
    transport: BaseTransport, runner_args: RunnerArguments, builder: AgentBuilder
) -> None:
    config = builder.config
    logger.info(f"Starting '{config.name}' with {len(config.nodes)} nodes")

    # Fixed to English: left unset, the service detects the language per utterance
    # and short answers with an unusual name come back in other scripts (#13).
    stt = ElevenLabsRealtimeSTTService(
        api_key=os.environ["ELEVENLABS_API_KEY"],
        settings=ElevenLabsRealtimeSTTService.Settings(language=Language.EN),
    )
    tts = ElevenLabsTTSService(
        api_key=os.environ["ELEVENLABS_API_KEY"],
        settings=ElevenLabsTTSService.Settings(voice=config.voice_id),
    )
    llm = OpenAILLMService(
        api_key=os.environ["OPENAI_API_KEY"],
        settings=OpenAILLMService.Settings(model=config.model),
    )

    context = LLMContext()
    context_aggregator = LLMContextAggregatorPair(
        context,
        user_params=LLMUserAggregatorParams(vad_analyzer=SileroVADAnalyzer()),
    )

    pipeline = Pipeline(
        [
            transport.input(),
            stt,
            context_aggregator.user(),
            llm,
            tts,
            transport.output(),
            context_aggregator.assistant(),
        ]
    )

    worker = PipelineWorker(
        pipeline,
        params=PipelineParams(enable_metrics=True, enable_usage_metrics=True),
        idle_timeout_secs=runner_args.pipeline_idle_timeout_secs,
    )

    flow_manager = FlowManager(
        llm=llm,
        context_aggregator=context_aggregator,
        worker=worker,
        transport=transport,
    )

    @transport.event_handler("on_client_connected")
    async def on_client_connected(transport, client):
        logger.info("Client connected — starting flow at initial node")
        await flow_manager.initialize(builder.build_initial_node())

    @transport.event_handler("on_client_disconnected")
    async def on_client_disconnected(transport, client):
        logger.info("Client disconnected")
        await worker.cancel()

    runner = WorkerRunner(handle_sigint=runner_args.handle_sigint)
    await runner.add_workers(worker)
    await runner.run()


async def reject_call(
    transport: BaseTransport, runner_args: RunnerArguments, errors: list[ValidationIssue]
) -> None:
    """End the call without running the agent, telling the client why.

    Runs an empty pipeline so the call ends the normal way: the client gets
    bot-ready, then an RTVI error, then a disconnect. Closing the WebRTC
    connection directly is not enough, because the client is still connecting
    at that point and never notices.
    """
    worker = PipelineWorker(
        Pipeline([transport.input(), transport.output()]),
        idle_timeout_secs=runner_args.pipeline_idle_timeout_secs,
    )

    @worker.rtvi.event_handler("on_client_ready")
    async def on_client_ready(rtvi):
        await rtvi.send_error("Invalid agent: " + "; ".join(e.message for e in errors))
        await worker.queue_frame(EndFrame())

    runner = WorkerRunner(handle_sigint=runner_args.handle_sigint)
    await runner.add_workers(worker)
    await runner.run()


def load_agent(body) -> AgentBuilder:
    """Build the agent sent with the connect request, or the default one.

    The client sends {"agent": {...}} as the request body (see docs/notes/runtime.md).
    Raises ValidationError for an invalid agent: never fall back to another agent,
    or the author would hear something other than what they are testing.
    """
    agent = body.get("agent") if isinstance(body, dict) else None
    if agent is None:
        logger.info(f"No agent in the request; using {DEFAULT_AGENT.name}")
        return AgentBuilder.from_json(DEFAULT_AGENT)
    return AgentBuilder.from_dict(agent)


async def bot(runner_args: RunnerArguments):
    """Entry point invoked by the Pipecat dev runner (and Pipecat Cloud)."""
    transport = await create_transport(runner_args, transport_params)
    try:
        builder = load_agent(runner_args.body)
    except ValidationError as e:
        # The client validates before connecting, so this means a stale or
        # hand-edited draft. Never fall back to another agent.
        for error in e.errors:
            logger.error(f"Invalid agent: {error.to_dict()}")
        await reject_call(transport, runner_args, e.errors)
        return
    await run_bot(transport, runner_args, builder)


if __name__ == "__main__":
    from pipecat.runner.run import main

    main()
