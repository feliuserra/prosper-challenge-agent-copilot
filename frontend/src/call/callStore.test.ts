import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { APIRequest, DeviceStatus, RTVIEventCallbacks, RTVIMessage } from "@pipecat-ai/client-js";

import type { Health, ValidationIssue } from "../api";
import { blankAgent } from "../agent/templates";
import { useAgentStore } from "../store/agentStore";
import { hangUp, selectMic, setCallDeps, setMuted, startCall, useCallStore, type CallClient } from "./callStore";

/** A stand-in for PipecatClient; the test decides when the bot is ready. */
function fakeClient(callbacks: RTVIEventCallbacks) {
  let ready!: () => void;
  let failed!: (error: Error) => void;
  const client = {
    callbacks,
    requests: [] as APIRequest[],
    mediaState: { mic: { state: "uninitialized" } as DeviceStatus },
    initDevices: vi.fn(async () => {
      client.mediaState.mic = { state: "granted" };
    }),
    startBotAndConnect: vi.fn((request: APIRequest) => {
      client.requests.push(request);
      return new Promise<unknown>((resolve, reject) => {
        ready = () => resolve({ version: "2.0.0" });
        failed = reject;
      });
    }),
    // Like the real client: a disconnect is reported, and a pending connect fails.
    disconnect: vi.fn(async () => {
      failed?.(new Error("disconnected"));
      callbacks.onDisconnected?.();
    }),
    updateMic: vi.fn(),
    enableMic: vi.fn(),
    ready: () => ready(),
  };
  return client satisfies CallClient;
}
type FakeClient = ReturnType<typeof fakeClient>;

let clients: FakeClient[];
let health: Health;
let errors: ValidationIssue[];
const state = () => useCallStore.getState();
const flush = () => vi.advanceTimersByTimeAsync(0);

const fakeDeps = {
  health: async () => health,
  validate: async () => errors,
  createClient: async (callbacks: RTVIEventCallbacks) => {
    const client = fakeClient(callbacks);
    clients.push(client);
    return client;
  },
  botReadyTimeoutMs: 15_000,
};

/** Start a call and let it run up to waiting for bot-ready. */
async function callUntilConnecting() {
  const done = startCall();
  await flush();
  return { done, client: clients.at(-1)! };
}

beforeEach(() => {
  vi.useFakeTimers();
  clients = [];
  health = { ok: true, missing_keys: [] };
  errors = [];
  setCallDeps(fakeDeps);
  useAgentStore.getState().open("a", blankAgent("A"));
});

afterEach(async () => {
  await hangUp();
  useCallStore.setState({ phase: "idle", steps: null, notice: null, transcript: [], mics: [], micId: null });
  setCallDeps();
  vi.useRealTimers();
});

describe("startCall", () => {
  it("sends the current draft, unsaved, and goes through every step", async () => {
    useAgentStore.getState().updateAgent({ persona: "Edited, not saved" });
    const { done, client } = await callUntilConnecting();
    expect(state().phase).toBe("connecting");
    expect(state().steps).toEqual({ backend: "done", agent: "done", mic: "done", bot: "running" });
    client.ready();
    await done;
    expect(state().phase).toBe("in-call");
    expect(state().steps?.bot).toBe("done");
    expect(client.requests[0]).toEqual({ endpoint: "/start", requestData: { body: { agent: useAgentStore.getState().agent } } });
    expect(useAgentStore.getState().agent?.persona).toBe("Edited, not saved");
  });

  it("stops at missing keys with a readable message, before connecting", async () => {
    health = { ok: false, missing_keys: ["OPENAI_API_KEY", "ELEVENLABS_API_KEY"] };
    await startCall();
    expect(state().phase).toBe("idle");
    expect(state().steps).toMatchObject({ backend: "failed", agent: "pending" });
    expect(state().notice?.text).toContain("OPENAI_API_KEY, ELEVENLABS_API_KEY in backend/.env");
    expect(clients).toHaveLength(0);
  });

  it("says when the backend cannot be reached", async () => {
    setCallDeps({ ...fakeDeps, health: async () => Promise.reject(new Error("fetch failed")) });
    await startCall();
    expect(state().steps?.backend).toBe("failed");
    expect(state().notice?.text).toContain("Cannot reach the backend");
  });

  it("does not connect when the agent has errors", async () => {
    errors = [{ message: "Edge target missing", node: "start", edge: "go" }];
    await startCall();
    expect(state().steps).toMatchObject({ backend: "done", agent: "failed", mic: "pending" });
    expect(state().notice?.text).toContain("1 error.");
    expect(clients).toHaveLength(0);
  });

  it("says when the microphone cannot be used", async () => {
    setCallDeps({
      ...fakeDeps,
      createClient: async (callbacks) => {
        const client = fakeClient(callbacks);
        client.initDevices.mockRejectedValue(new Error("NotAllowedError"));
        return client;
      },
    });
    await startCall();
    expect(state().steps?.mic).toBe("failed");
    expect(state().notice?.text).toContain("Allow microphone access");
  });

  it("does not call with a blocked microphone, which initDevices does not report", async () => {
    setCallDeps({
      ...fakeDeps,
      createClient: async (callbacks) => {
        const client = fakeClient(callbacks);
        client.initDevices.mockImplementation(async () => {
          client.mediaState.mic = { state: "error", reason: "blocked" };
        });
        clients.push(client);
        return client;
      },
    });
    await startCall();
    expect(state().steps).toMatchObject({ mic: "failed", bot: "pending" });
    expect(state().notice?.text).toContain("Microphone access is blocked");
    expect(clients[0].startBotAndConnect).not.toHaveBeenCalled();
    expect(clients[0].disconnect).toHaveBeenCalled();
  });

  it("gives up on a bot that never gets ready and points to the backend terminal", async () => {
    const { done, client } = await callUntilConnecting();
    await vi.advanceTimersByTimeAsync(15_000);
    await done;
    expect(state().phase).toBe("idle");
    expect(state().steps?.bot).toBe("failed");
    expect(state().notice?.text).toContain("did not start within 15 seconds");
    expect(state().notice?.text).toContain("terminal");
    expect(client.disconnect).toHaveBeenCalled();
  });

  it("reports a failed connection", async () => {
    const { done, client } = await callUntilConnecting();
    // The transport gives up on its own (the real one rejects the connect).
    client.disconnect();
    await done;
    expect(state().steps?.bot).toBe("failed");
    expect(state().notice?.text).toContain("Could not connect to the bot (disconnected)");
  });
});

describe("during and after a call", () => {
  async function connected() {
    const { done, client } = await callUntilConnecting();
    client.ready();
    await done;
    return client;
  }

  it("returns to idle when the bot ends the call, keeping the transcript", async () => {
    const client = await connected();
    client.callbacks.onUserTranscript?.({ text: "Goodbye", final: true, timestamp: "", user_id: "" });
    client.callbacks.onDisconnected?.();
    expect(state()).toMatchObject({ phase: "idle", startedAt: null, botTrack: null });
    expect(state().notice).toEqual({ tone: "info", text: "The bot ended the call." });
    expect(state().transcript).toHaveLength(1);
  });

  it("hangs up, and a second call starts clean with a new client", async () => {
    const first = await connected();
    first.callbacks.onUserTranscript?.({ text: "Hello", final: true, timestamp: "", user_id: "" });
    await hangUp();
    expect(state().phase).toBe("idle");
    expect(state().notice?.text).toBe("Call ended.");

    const second = await connected();
    expect(second).not.toBe(first);
    expect(state()).toMatchObject({ phase: "in-call", notice: null, transcript: [] });
    // The first call's late events change nothing.
    first.callbacks.onUserTranscript?.({ text: "stale", final: true, timestamp: "", user_id: "" });
    first.callbacks.onDisconnected?.();
    expect(state()).toMatchObject({ phase: "in-call", transcript: [] });
  });

  it("keeps the bot's error as the notice when it then ends the call", async () => {
    const client = await connected();
    client.callbacks.onError?.({ data: { error: "Invalid agent: no nodes", fatal: true } } as RTVIMessage);
    client.callbacks.onDisconnected?.();
    expect(state().phase).toBe("idle");
    expect(state().notice).toEqual({ tone: "error", text: "The bot reported an error: Invalid agent: no nodes" });
  });

  it("cancels a call that is still connecting", async () => {
    const { done, client } = await callUntilConnecting();
    await hangUp();
    await done;
    expect(state()).toMatchObject({ phase: "idle", steps: null, notice: null });
    expect(client.disconnect).toHaveBeenCalled();
  });

  it("mutes and switches microphones on the live client", async () => {
    const client = await connected();
    setMuted(true);
    expect(client.enableMic).toHaveBeenCalledWith(false);
    expect(state().muted).toBe(true);
    selectMic("usb");
    expect(client.updateMic).toHaveBeenCalledWith("usb");
    await hangUp();
    expect(state().muted).toBe(false);
  });

  it("applies the chosen microphone to the next call", async () => {
    useCallStore.setState({ mics: [{ deviceId: "usb" } as MediaDeviceInfo] });
    selectMic("usb");
    const client = await connected();
    expect(client.updateMic).toHaveBeenCalledWith("usb");
  });
});
