import { PipecatClient, RTVIEvent } from "@pipecat-ai/client-js";
import { SmallWebRTCTransport } from "@pipecat-ai/small-webrtc-transport";

const button = document.querySelector<HTMLButtonElement>("#call")!;
const status = document.querySelector<HTMLSpanElement>("#status")!;

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
  client = new PipecatClient({
    transport: new SmallWebRTCTransport(),
    enableMic: true,
    enableCam: false,
    callbacks: {
      onTransportStateChanged: (state) => setStatus(state),
      onBotReady: (data) => console.log("[spike] bot ready", data),
      onServerMessage: (data) => console.log("[spike] server message", data),
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
  client.on(RTVIEvent.Error, (message) => console.error("[spike] rtvi error", message));

  button.textContent = "Hang up";
  // POST /start with this JSON. The runner keeps `body` for the session and
  // hands it to bot() as runner_args.body when the offer arrives.
  try {
    await client.startBotAndConnect({
      endpoint: "/start",
      requestData: { body: { agent: { name: "spike-test" } } },
    });
  } catch (error) {
    console.error("[spike] call failed", error);
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

// Proves custom routes on the runner app are reachable through the proxy.
fetch("/composer/ping")
  .then((res) => res.json())
  .then((data) => console.log("[spike] /composer/ping", data))
  .catch((error) => console.error("[spike] /composer/ping failed", error));
