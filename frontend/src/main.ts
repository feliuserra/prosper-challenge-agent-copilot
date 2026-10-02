import { PipecatClient, RTVIEvent } from "@pipecat-ai/client-js";
import { SmallWebRTCTransport } from "@pipecat-ai/small-webrtc-transport";

const button = document.querySelector<HTMLButtonElement>("#call")!;
const status = document.querySelector<HTMLSpanElement>("#status")!;
const agentInput = document.querySelector<HTMLTextAreaElement>("#agent")!;

// A fresh client per call: reusing one after disconnect leaves stale state.
let client: PipecatClient | null = null;

function setStatus(text: string) {
  status.textContent = text;
}

function playBotAudio(track: MediaStreamTrack) {
  let audio = document.querySelector<HTMLAudioElement>("#bot-audio");
  if (!audio) {
    audio = document.createElement("audio");
    audio.id = "bot-audio";
    audio.autoplay = true;
    document.body.appendChild(audio);
  }
  audio.srcObject = new MediaStream([track]);
}

async function call() {
  let agent; // any: sent as is, the backend validates it
  try {
    agent = JSON.parse(agentInput.value);
  } catch {
    setStatus("agent is not valid JSON");
    return;
  }
  client = new PipecatClient({
    transport: new SmallWebRTCTransport(),
    enableMic: true,
    enableCam: false,
    callbacks: {
      onTransportStateChanged: (state) => setStatus(state),
      onBotReady: (data) => console.log("[test] bot ready", data),
      onServerMessage: (data) => console.log("[test] server message", data),
      onTrackStarted: (track, participant) => {
        if (!participant?.local && track.kind === "audio") playBotAudio(track);
      },
      onDisconnected: () => {
        // Covers both our hang-up and the bot ending the call (end node).
        client = null;
        button.textContent = "Call";
        setStatus("disconnected");
      },
    },
  });
  client.on(RTVIEvent.Error, (message) => console.error("[test] rtvi error", message));

  button.textContent = "Hang up";
  // POST /start with this JSON. The runner keeps `body` for the session and
  // hands it to bot() as runner_args.body when the offer arrives.
  try {
    await client.startBotAndConnect({
      endpoint: "/start",
      requestData: { body: { agent } },
    });
  } catch (error) {
    console.error("[test] call failed", error);
    setStatus("error (see console)");
    await client?.disconnect();
    client = null;
    button.textContent = "Call";
  }
}

button.addEventListener("click", async () => {
  if (client) {
    await client.disconnect();
    return;
  }
  await call();
});

// Start from the saved default agent.
fetch("/composer/agents/prosper-scheduler")
  .then((res) => res.json())
  .then((agent) => (agentInput.value = JSON.stringify(agent, null, 2)))
  .catch((error) => console.error("[test] could not load the default agent", error));
