import { useEffect, useRef, useState } from "react";

import { useAgentStore } from "../store/agentStore";
import { useValidationStore } from "../validation/validationStore";
import {
  hangUp,
  listMicsIfAllowed,
  selectMic,
  setMuted,
  setPanelOpen,
  startCall,
  useCallStore,
  type CallPhase,
  type StepName,
  type Steps,
} from "./callStore";
import { turnText } from "./transcript";

const STEP_LABELS: Record<StepName, string> = {
  backend: "Backend keys",
  agent: "Agent valid",
  mic: "Microphone",
  bot: "Bot ready",
};
const STEP_ICONS = { pending: "○", running: "…", done: "✓", failed: "✕" };

const PHASE_LABELS: Record<CallPhase, string> = {
  idle: "Not in a call",
  checking: "Checking…",
  connecting: "Connecting…",
  "in-call": "In call",
};

/** The test call: controls, setup progress, how the last call ended, transcript. */
export function CallPanel() {
  const phase = useCallStore((s) => s.phase);
  const steps = useCallStore((s) => s.steps);
  const notice = useCallStore((s) => s.notice);
  const hasAgent = useAgentStore((s) => s.agent !== null);
  // From the latest check, which may be a moment behind the draft: Call checks
  // the current draft again before connecting.
  const errorCount = useValidationStore((s) => s.errors.length);

  useEffect(() => void listMicsIfAllowed().catch(() => {}), []);

  const idle = phase === "idle";
  // Setup progress while placing a call, and after a call that never started.
  const showSteps = steps && (!idle || Object.values(steps).includes("failed"));

  return (
    <aside className="call-panel nokey" aria-label="Test call">
      <div className="call-panel-header">
        <h2>Test call</h2>
        <button className="link" onClick={() => setPanelOpen(false)} title="Close (a call keeps going)">
          Close
        </button>
      </div>

      <div className="row">
        {idle ? (
          <button
            className="primary"
            onClick={() => void startCall()}
            disabled={!hasAgent || errorCount > 0}
            title={errorCount > 0 ? "Fix the errors in Problems first" : undefined}
          >
            Call
          </button>
        ) : (
          <button className="danger" onClick={() => void hangUp()}>
            {phase === "in-call" ? "Hang up" : "Cancel"}
          </button>
        )}
        <MuteButton />
        <PhaseLabel phase={phase} />
      </div>
      <div className="hint">Calls the agent as it is in the editor; saving is not needed.</div>

      {showSteps && <StepList steps={steps} />}
      {notice && <div className={`call-notice ${notice.tone}`}>{notice.text}</div>}
      <MicPicker />
      <Transcript />
    </aside>
  );
}

function MuteButton() {
  const phase = useCallStore((s) => s.phase);
  const muted = useCallStore((s) => s.muted);
  if (phase !== "in-call") return null;
  return (
    <button onClick={() => setMuted(!muted)} aria-pressed={muted}>
      {muted ? "Unmute" : "Mute"}
    </button>
  );
}

function PhaseLabel({ phase }: { phase: CallPhase }) {
  const startedAt = useCallStore((s) => s.startedAt);
  const [now, setNow] = useState(Date.now);
  useEffect(() => {
    if (startedAt === null) return;
    setNow(Date.now());
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [startedAt]);

  let label = PHASE_LABELS[phase];
  if (phase === "in-call" && startedAt !== null) {
    const seconds = Math.max(0, Math.floor((now - startedAt) / 1000));
    label += ` · ${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
  }
  return <span className={phase === "in-call" ? "call-live" : "muted"}>{label}</span>;
}

function StepList({ steps }: { steps: Steps }) {
  return (
    <ol className="call-steps">
      {(Object.keys(STEP_LABELS) as StepName[]).map((name) => (
        <li key={name} className={steps[name]}>
          <span className="call-step-icon" aria-hidden>
            {STEP_ICONS[steps[name]]}
          </span>
          {STEP_LABELS[name]}
        </li>
      ))}
    </ol>
  );
}

function MicPicker() {
  const mics = useCallStore((s) => s.mics);
  const micId = useCallStore((s) => s.micId);
  if (!mics.length) return null;
  return (
    <label className="field call-mic">
      <div className="field-label">Microphone</div>
      <select value={micId ?? ""} onChange={(event) => selectMic(event.target.value)}>
        {!micId && <option value="">Default</option>}
        {mics.map((mic) => (
          <option key={mic.deviceId} value={mic.deviceId}>
            {mic.label || mic.deviceId}
          </option>
        ))}
      </select>
    </label>
  );
}

function Transcript() {
  const turns = useCallStore((s) => s.transcript);
  const phase = useCallStore((s) => s.phase);
  const listRef = useRef<HTMLOListElement>(null);
  const shown = turns.map((turn) => ({ turn, text: turnText(turn) })).filter((t) => t.text);

  // Follow the conversation as it grows.
  useEffect(() => {
    const list = listRef.current;
    if (list) list.scrollTop = list.scrollHeight;
  }, [turns]);

  return (
    <section className="call-transcript">
      <div className="field-label">Transcript</div>
      {shown.length === 0 ? (
        <div className="muted">{phase === "in-call" ? "Say something…" : "The conversation shows here during a call."}</div>
      ) : (
        <ol ref={listRef} className="turns">
          {shown.map(({ turn, text }, i) => (
            <li key={i} className={`turn ${turn.role}`}>
              <span className="turn-role">{turn.role === "user" ? "You" : "Bot"}</span>
              {turn.role === "user" && turn.partial ? (
                // Still being transcribed: the partial is replaced as it firms up.
                <span className="turn-text">
                  {turn.text && `${turn.text} `}
                  <span className="partial">{turn.partial}</span>
                </span>
              ) : (
                <span className="turn-text">{text}</span>
              )}
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}

/** Plays the bot. Always mounted, so closing the panel does not silence a call. */
export function CallAudio() {
  const track = useCallStore((s) => s.botTrack);
  const audioRef = useRef<HTMLAudioElement>(null);
  useEffect(() => {
    if (audioRef.current) audioRef.current.srcObject = track ? new MediaStream([track]) : null;
  }, [track]);
  return <audio ref={audioRef} autoPlay />;
}
