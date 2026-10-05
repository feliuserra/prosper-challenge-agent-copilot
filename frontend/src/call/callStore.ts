import { create } from "zustand";
import type { APIRequest, DeviceStatus, RTVIEventCallbacks } from "@pipecat-ai/client-js";

import { getHealth, type Health, type ValidationIssue } from "../api";
import type { Agent } from "../agent/schema";
import { useAgentStore } from "../store/agentStore";
import { checkAgent } from "../validation/validationStore";
import { addBotOutput, addUserTranscript, type Turn } from "./transcript";

// The test call: one at a time, with a fresh Pipecat client each, so nothing
// from an earlier call (state, callbacks) can leak into the next one.
//
// Placing a call runs four steps, each shown in the panel so a failure says
// where it happened:
//   backend  GET /composer/health: the keys the bot needs are set
//   agent    POST /composer/validate on the current draft (errors block the call)
//   mic      microphone access
//   bot      start the bot with the draft and wait for bot-ready
// The bot step has a timeout: missing keys or a crash in bot() leave the client
// waiting forever, because the runner answers the offer before the bot runs.

export type CallPhase = "idle" | "checking" | "connecting" | "in-call";
export type StepName = "backend" | "agent" | "mic" | "bot";
export type StepState = "pending" | "running" | "done" | "failed";
export type Steps = Record<StepName, StepState>;

export interface Notice {
  tone: "error" | "info";
  text: string;
}

interface CallState {
  panelOpen: boolean;
  phase: CallPhase;
  /** Progress of the latest call's setup steps; null before the first call. */
  steps: Steps | null;
  /** How the latest call ended or failed, or a problem the bot reported. */
  notice: Notice | null;
  /** The latest call's transcript, kept after it ends until the next call. */
  transcript: Turn[];
  /** When the bot became ready (ms since epoch), for the call timer. */
  startedAt: number | null;
  mics: MediaDeviceInfo[];
  /** The microphone in use, or the one chosen for the next call. */
  micId: string | null;
  muted: boolean;
  /** The bot's audio, played by `CallAudio`. */
  botTrack: MediaStreamTrack | null;
}

export const useCallStore = create<CallState>()(() => ({
  panelOpen: false,
  phase: "idle",
  steps: null,
  notice: null,
  transcript: [],
  startedAt: null,
  mics: [],
  micId: null,
  muted: false,
  botTrack: null,
}));

/** The part of `PipecatClient` a call uses. */
export interface CallClient {
  initDevices(): Promise<void>;
  readonly mediaState: { mic: DeviceStatus };
  startBotAndConnect(params: APIRequest): Promise<unknown>;
  disconnect(): Promise<void>;
  updateMic(micId: string): void;
  enableMic(enable: boolean): void;
}

export interface CallDeps {
  health: () => Promise<Health>;
  validate: (agent: Agent) => Promise<ValidationIssue[]>;
  createClient: (callbacks: RTVIEventCallbacks) => Promise<CallClient>;
  botReadyTimeoutMs: number;
}

async function createPipecatClient(callbacks: RTVIEventCallbacks): Promise<CallClient> {
  // Loaded on the first call: the WebRTC stack is most of the bundle.
  const [{ PipecatClient }, { SmallWebRTCTransport }] = await Promise.all([
    import("@pipecat-ai/client-js"),
    import("@pipecat-ai/small-webrtc-transport"),
  ]);
  return new PipecatClient({ transport: new SmallWebRTCTransport(), enableMic: true, enableCam: false, callbacks });
}

const defaultDeps: CallDeps = {
  health: getHealth,
  // Publishes the errors to the problems list too.
  validate: (agent) => checkAgent(agent),
  createClient: createPipecatClient,
  botReadyTimeoutMs: 15_000,
};
let deps = defaultDeps;

/** Replace the backend and client for tests; `undefined` restores the real ones. */
export function setCallDeps(overrides?: Partial<CallDeps>) {
  deps = { ...defaultDeps, ...overrides };
}

/** Why the microphone could not be used, from client-js's device state. */
function micProblem(mic: DeviceStatus): string {
  const reason = mic.state === "error" ? mic.reason : "unknown";
  if (reason === "blocked") return "Microphone access is blocked. Allow it for this page (icon in the address bar) and call again.";
  if (reason === "already-in-use") return "The microphone is in use by another app.";
  if (reason === "not-found") return "No microphone was found.";
  return "Could not use the microphone. Allow microphone access for this page and try again.";
}

const BACKEND_HINT = "Check the terminal running the backend (make dev) for errors.";

interface Call {
  client: CallClient | null;
  /** We hung up, as opposed to the bot ending the call. */
  hungUp: boolean;
  /** The bot reported an error, which stays as the notice when the call ends. */
  failed: boolean;
}

// The call in progress. Callbacks and awaits from a call that is no longer
// current (hung up, failed, replaced) change nothing.
let current: Call | null = null;
// The microphone the user picked. Kept apart from `micId`, which the client
// overwrites with its default while it starts.
let preferredMic: string | null = null;

const set = useCallStore.setState;
const get = useCallStore.getState;

function setStep(name: StepName, state: StepState) {
  const steps = get().steps;
  if (steps) set({ steps: { ...steps, [name]: state } });
}

/** End `call` before the bot was ready: mark the step and say why. */
function fail(call: Call, step: StepName, text: string) {
  if (current !== call) return;
  current = null;
  setStep(step, "failed");
  set({ phase: "idle", notice: { tone: "error", text }, botTrack: null });
  void call.client?.disconnect();
}

/** The connected call ended, by either side. */
function finish(call: Call) {
  if (current !== call) return;
  current = null;
  const notice: Notice | null = call.failed
    ? get().notice
    : { tone: "info", text: call.hungUp ? "Call ended." : "The bot ended the call." };
  set({ phase: "idle", notice, startedAt: null, muted: false, botTrack: null });
}

function callbacks(call: Call): RTVIEventCallbacks {
  const live = () => current === call;
  return {
    onUserTranscript: (data) => live() && set({ transcript: addUserTranscript(get().transcript, data) }),
    onBotOutput: (data) => live() && set({ transcript: addBotOutput(get().transcript, data) }),
    onTrackStarted: (track, participant) => {
      if (live() && !participant?.local && track.kind === "audio") set({ botTrack: track });
    },
    onAvailableMicsUpdated: (mics) => live() && set({ mics: mics.filter((m) => m.deviceId) }),
    onMicUpdated: (mic) => live() && mic.deviceId && set({ micId: mic.deviceId }),
    // An invalid agent that reaches the bot ends this way ("Invalid agent: ..."),
    // and so do errors in the pipeline.
    onError: (message) => {
      if (!live()) return;
      const data = message.data as { error?: string; message?: string } | undefined;
      call.failed = true;
      set({ notice: { tone: "error", text: `The bot reported an error: ${data?.error ?? data?.message ?? "unknown"}` } });
    },
    // Transition events, logged for now (#8 shows them).
    onServerMessage: (data) => console.log("[call] server message", data),
    // Both our hang-up and the bot's (an end node). Before bot-ready a lost
    // connection rejects startBotAndConnect instead, handled in startCall.
    onDisconnected: () => {
      if (get().phase === "in-call") finish(call);
    },
  };
}

/**
 * Place a test call with the current draft. Saving is not needed: the draft
 * goes to the bot in the connect request (ADR 0005).
 */
export async function startCall() {
  if (current || !useAgentStore.getState().agent) return;
  const call: Call = { client: null, hungUp: false, failed: false };
  current = call;
  const live = () => current === call;
  set({
    phase: "checking",
    steps: { backend: "running", agent: "pending", mic: "pending", bot: "pending" },
    notice: null,
    transcript: [],
    startedAt: null,
    muted: false,
    botTrack: null,
  });

  try {
    const health = await deps.health();
    if (!live()) return;
    if (!health.ok) {
      const keys = health.missing_keys.join(", ");
      const them = health.missing_keys.length === 1 ? "it" : "them";
      return fail(call, "backend", `The backend is missing ${keys} in backend/.env. Add ${them} and restart the backend.`);
    }
  } catch {
    return fail(call, "backend", "Cannot reach the backend. Is it running (make dev)?");
  }
  setStep("backend", "done");

  // The draft as it is now: this exact object is validated and sent.
  const agent = useAgentStore.getState().agent;
  if (!agent) return fail(call, "agent", "No agent is open.");
  setStep("agent", "running");
  try {
    const errors = await deps.validate(agent);
    if (!live()) return;
    if (errors.length) {
      const count = errors.length === 1 ? "1 error. Fix it" : `${errors.length} errors. Fix them`;
      return fail(call, "agent", `The agent has ${count} in Problems, then call again.`);
    }
  } catch (error) {
    return fail(call, "agent", `Could not validate the agent: ${error}`);
  }
  setStep("agent", "done");

  set({ phase: "connecting" });
  setStep("mic", "running");
  try {
    call.client = await deps.createClient(callbacks(call));
    if (!live()) return void call.client.disconnect();
    // Asks for mic access the first time; not timed, the user may take a while.
    await call.client.initDevices();
  } catch {
    return fail(call, "mic", micProblem(call.client?.mediaState.mic ?? { state: "uninitialized" }));
  }
  if (!live()) return void call.client.disconnect();
  // A blocked mic does not make initDevices throw; the call would go ahead
  // with the bot unable to hear anything.
  const mic = call.client.mediaState.mic;
  if (mic.state !== "granted") return fail(call, "mic", micProblem(mic));
  if (preferredMic && get().mics.some((m) => m.deviceId === preferredMic)) {
    call.client.updateMic(preferredMic);
    set({ micId: preferredMic });
  }
  setStep("mic", "done");

  setStep("bot", "running");
  let timer: ReturnType<typeof setTimeout> | undefined;
  const timeout = new Promise<"timeout">((resolve) => {
    timer = setTimeout(() => resolve("timeout"), deps.botReadyTimeoutMs);
  });
  try {
    const started = call.client.startBotAndConnect({
      endpoint: "/start",
      // The runner keeps `body` for the session and hands it to bot()
      // (docs/notes/runtime.md). The agent is plain JSON (loaded from a file,
      // edited with JSON values); its loose type, with `unknown` for unmodelled
      // keys, just cannot say so.
      requestData: { body: { agent } } as unknown as APIRequest["requestData"],
    });
    const ready = started.then(() => "ready" as const);
    // After a timeout or a hang-up the client is disconnected and this rejects
    // with nobody waiting for it.
    ready.catch(() => {});
    const result = await Promise.race([ready, timeout]);
    if (!live()) return;
    if (result === "timeout") {
      const seconds = Math.round(deps.botReadyTimeoutMs / 1000);
      return fail(call, "bot", `The bot did not start within ${seconds} seconds. ${BACKEND_HINT}`);
    }
  } catch (error) {
    const reason = error instanceof Error && error.message ? ` (${error.message})` : "";
    return fail(call, "bot", `Could not connect to the bot${reason}. ${BACKEND_HINT}`);
  } finally {
    clearTimeout(timer);
  }
  setStep("bot", "done");
  set({ phase: "in-call", startedAt: Date.now() });
}

/** Hang up, or cancel a call that is still being placed. */
export async function hangUp() {
  const call = current;
  if (!call) return;
  if (get().phase !== "in-call") {
    // Nothing was said yet: forget this attempt as if it never started.
    current = null;
    set({ phase: "idle", steps: null, notice: null, botTrack: null });
    await call.client?.disconnect();
    return;
  }
  call.hungUp = true;
  await call.client?.disconnect();
  // In case the client does not report its own disconnect.
  finish(call);
}

export function setMuted(muted: boolean) {
  if (get().phase !== "in-call") return;
  current?.client?.enableMic(!muted);
  set({ muted });
}

/** Use this microphone now (during a call) and for the next calls. */
export function selectMic(micId: string) {
  preferredMic = micId;
  set({ micId });
  if (get().phase === "in-call") current?.client?.updateMic(micId);
}

/**
 * Fill the microphone list before the first call, if the browser already
 * allows mic access (device labels are hidden until it does).
 */
export async function listMicsIfAllowed() {
  if (get().mics.length || !navigator.mediaDevices?.enumerateDevices) return;
  const devices = await navigator.mediaDevices.enumerateDevices();
  const mics = devices.filter((d) => d.kind === "audioinput" && d.deviceId && d.label);
  if (mics.length && !get().mics.length) set({ mics });
}

export function setPanelOpen(panelOpen: boolean) {
  set({ panelOpen });
}
