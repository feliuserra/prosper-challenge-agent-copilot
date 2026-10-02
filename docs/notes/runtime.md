# Runtime notes (Issue #1 spike)

What the spike proved about the Pipecat runtime, with references into the installed packages so the next upgrade can be checked quickly. Checked on 2026-10-01 and 2026-10-02 with a real call from the bare page in `frontend/`.

## Versions that work together

| Package | Version | Where |
| --- | --- | --- |
| `pipecat-ai` | 1.4.0 | backend venv |
| `pipecat-ai-flows` | 1.3.0 | backend venv |
| `@pipecat-ai/client-js` | 1.13.1 (pinned exactly) | `frontend/package.json` |
| `@pipecat-ai/small-webrtc-transport` | 1.10.8 (pinned exactly, peer dep `client-js ~1.13.0`) | `frontend/package.json` |
| `@pipecat-ai/client-react` | 1.8.2 (latest, peer dep `client-js *`; not installed yet, add in #3) | |
| Node | 24 | `frontend/.nvmrc` |

**RTVI protocol.** The server speaks protocol 2.0.0 (`pipecat/processors/frameworks/rtvi/models.py:31`). client-js 1.13.1 speaks 2.1.0 (`RTVI_PROTOCOL_VERSION` in `client-js/dist/index.d.ts:509`). The server only compares the major version (`pipecat/processors/frameworks/rtvi/processor.py:384-387`), so they are fully compatible. It also still serves any 1.x client through a legacy path (`models.py:35`, `processor.py:388-401`). The "1.12.0" the prebuilt client reported earlier was its library version, not the protocol version. The terminal shows the real handshake: `Received client-ready: version 2.1.0`, `library_version='1.13.1'`.

Pin the client packages exactly. They move fast, and the transport pins its client-js peer to a minor range.

## 1. Connect payload reaches `bot()` (ADR 0005, Option A)

The page calls:

```ts
client.startBotAndConnect({
  endpoint: "/start",
  requestData: { body: { agent: { name: "spike-test" } } },
});
```

What happens, step by step:

1. client-js POSTs `requestData` unchanged as the JSON body of `/start` (`makeRequest`, `client-js/dist/index.module.js:1321-1344`).
2. The runner stores `request_data["body"]` against a new session id and returns `{sessionId}` (`pipecat/runner/run.py:572`, `:627-630`).
3. The transport sees a `sessionId` and no explicit WebRTC params, so it derives the offer URL by replacing `/start` with `/sessions/{sessionId}/api/offer` (`small-webrtc-transport/dist/index.module.js:2604`, `:2612-2621`). The offer body is only `{sdp, type, pc_id, restart_pc}` and carries no request data (`:2900-2915`).
4. The session proxy falls back to the stored body when the offer has no `request_data`/`requestData` (`run.py:856-858`), then calls the `/api/offer` handler, which passes it to the bot as `runner_args.body` (`run.py:796`, `:811-815`).

**Consequence for #2/#7:** the draft must be sent as `requestData.body`, not at the top level of `requestData`. A top-level field would only reach the runner's `/start` handler and be dropped. Observed in the terminal:

```
pipecat.runner.run:start_agent:595 - Received request: {'body': {'agent': {'name': 'spike-test'}}}
__main__:bot:122 - runner_args.body: {'agent': {'name': 'spike-test'}}
```

The body sits in the runner's in-memory `active_sessions` dict between `/start` and the offer. It is never written to disk. A draft is a few kilobytes, so size is not a concern.

## 2. Custom routes on the runner app

`from pipecat.runner.run import app` and decorating routes at module level in `bot.py` works (`run.py:168-181` documents this). The routes are registered before `main()` adds the runner's own routes, so a `/composer/` prefix cannot collide with them. `_get_bot_module()` returns `__main__` (`run.py:386-395`), so `bot.py` is not imported a second time and routes are not registered twice.

Checked: `GET /composer/ping` returns `{"ok": true}` on 7860 directly and through the Vite proxy on 5173, and `/client` still serves the prebuilt UI.

## 3. Server messages from an edge handler (ADR 0006)

The edge handler in `backend/agent_builder/builder.py` queues the frame on the worker:

```python
await flow_manager.worker.queue_frame(
    RTVIServerMessageFrame(data={"type": "transition", "from": ..., "function": ..., "to": ..., "args": ...})
)
```

- `flow_manager.worker` is the `PipelineWorker` (`pipecat_flows/manager.py:251`). `queue_frame` pushes downstream from the start of the pipeline (`pipecat/pipeline/worker.py:709`).
- The worker adds an `RTVIProcessor` and an RTVI observer by default (`worker.py:237`, `:403-406`). The observer turns `RTVIServerMessageFrame` into an RTVI `server-message` (`pipecat/processors/frameworks/rtvi/observer.py:549-551`, model at `models.py:613`).
- client-js delivers it to the `onServerMessage` callback (`RTVIEvent.ServerMessage`, `client-js/dist/index.d.ts:740`, `:1044`) with `data` as sent.
- An alternative is `flow_manager.worker.rtvi.send_server_message(data)` (`processor.py:146`), which skips the observer. We use the frame because it is the documented pattern and does not depend on the processor instance.
- The source node name is passed into `_make_edge_function`, so the message does not depend on when Flows updates `current_node`.

Observed in Chrome: `[choose_intent] -> collect_details | collected: {'intent': 'book'}` in the terminal, and in the browser console `bot ready {version: '2.0.0'}` followed by `server message {type: 'transition', from: 'greeting', function: 'choose_intent', to: 'collect_details', args: {...}}`.

## 4. Rejecting an invalid agent (added in #2)

`bot()` validates the received agent before building anything. When it is invalid, closing the WebRTC connection directly does not work: the runner has already answered the offer, the client is still connecting, and it never notices the close (it waits at "connecting" and its ICE `PATCH` requests get 400 for the discarded peer). Instead `bot()` runs an empty pipeline (`transport.input()` to `transport.output()`), and when the client is ready it sends `rtvi.send_error("Invalid agent: ...")` (`pipecat/processors/frameworks/rtvi/processor.py:162`) and queues an `EndFrame`. The client sees bot-ready, then an RTVI `error` whose `data.error` names the problems, then a normal disconnect, about 3 seconds in total. #7 can show that message, although the client should already have validated the draft before calling.

## Other observations

- **Video transceivers.** With `enableCam: false` the server still logs `Track video received` twice. The transport always negotiates the transceivers. This is harmless.
- **Barge-in.** In the first test call the user's "Hello? Hello?" interrupted the greeting before it was spoken. This is normal VAD interruption, not a bug.
- **First call ended early.** The first test call came from a WebKit browser (the client reported `Safari 18`), possibly not the one the user meant to test in, and ended about 20 seconds in while still in the greeting node (`Track audio ended`, then `Client disconnected`). The cause is unknown. The Chrome calls ran normally. Test in Chrome; if early disconnects show up again, look at them in #7.
- **Speech-to-text language.** Names are still transcribed in the wrong script (`Фелиу Сера Боррел`). This is tracked in #13.
- **Deprecation.** `OpenAILLMService(model=...)` is deprecated in favour of `settings=OpenAILLMService.Settings(model=...)` (`bot.py:65`). The fix is trivial; do it in #2 when `bot()` is reworked.
- **Async tool wording.** Pipecat Flows reports edge handlers to the LLM as async tools (`"type": "async_tool"` messages in the context). Transitions still work. It only matters if we later inspect or trim the context.

## Spike code: what stays

Applied in #2.

| Code | Fate |
| --- | --- |
| `frontend/` bare Vite + TS page | Seed for #3, which adds React. The proxy config, `.nvmrc` and pinned client packages carry over. |
| `GET /composer/ping` in `bot.py` | Replaced by `/composer/health` in #2. |
| `runner_args.body` log in `bot()` | Becomes the draft handover in #2. Stop logging the full body there, because it will hold the whole agent. |
| Transition message in `builder.py` | Kept. #8 builds the UI on it. |
