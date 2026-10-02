import { useEffect, useRef, useState } from "react";
import { PipecatClient, RTVIEvent, type APIRequest } from "@pipecat-ai/client-js";
import { SmallWebRTCTransport } from "@pipecat-ai/small-webrtc-transport";

import { useAgentStore } from "../store/agentStore";

// Minimal test call with the current draft. Issue #7 turns this into the call panel.
export function CallButton() {
  const clientRef = useRef<PipecatClient | null>(null);
  const audioRef = useRef<HTMLAudioElement>(null);
  const [status, setStatus] = useState("idle");
  const inCall = status !== "idle" && status !== "disconnected" && status !== "error";

  useEffect(() => () => void clientRef.current?.disconnect(), []);

  async function call() {
    const agent = useAgentStore.getState().agent;
    if (!agent) return;
    // A fresh client per call: reusing one after disconnect leaves stale state.
    const client = new PipecatClient({
      transport: new SmallWebRTCTransport(),
      enableMic: true,
      enableCam: false,
      callbacks: {
        onTransportStateChanged: (state) => setStatus(state),
        onServerMessage: (data) => console.log("[call] server message", data),
        onTrackStarted: (track, participant) => {
          if (!participant?.local && track.kind === "audio" && audioRef.current) {
            audioRef.current.srcObject = new MediaStream([track]);
          }
        },
        // Covers both our hang-up and the bot ending the call (end node).
        onDisconnected: () => {
          clientRef.current = null;
          setStatus("disconnected");
        },
      },
    });
    client.on(RTVIEvent.Error, (message) => console.error("[call] error", message));
    clientRef.current = client;
    try {
      // The runner keeps `body` for the session and hands it to bot() (docs/notes/runtime.md).
      await client.startBotAndConnect({
        endpoint: "/start",
        // The agent is plain JSON (loaded from a file, edited with JSON values);
        // its loose type, with `unknown` for unmodelled keys, just cannot say so.
        requestData: { body: { agent } } as unknown as APIRequest["requestData"],
      });
    } catch (error) {
      console.error("[call] failed", error);
      await client.disconnect();
      clientRef.current = null;
      setStatus("error");
    }
  }

  return (
    <span className="call">
      <button onClick={() => (inCall ? clientRef.current?.disconnect() : call())}>
        {inCall ? "Hang up" : "Test call"}
      </button>
      <span className="muted">{status}</span>
      <audio ref={audioRef} autoPlay />
    </span>
  );
}
