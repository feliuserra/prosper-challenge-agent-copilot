import { useEffect, useState } from "react";

import { DEFAULT_CLINIC } from "./agent/options";
import { CallAudio, CallPanel } from "./call/CallPanel";
import { useCallStore } from "./call/callStore";
import { Canvas } from "./canvas/Canvas";
import { ClinicView, useClinic } from "./clinic/ClinicView";
import { useDetectionStore, wantedFromAddress } from "./detection/detectionStore";
import { IssuesPanel } from "./detection/IssuesPanel";
import { Toolbar } from "./components/Toolbar";
import { Panel } from "./panel/Panel";
import { useAgentStore } from "./store/agentStore";
import { watchAgent } from "./validation/validationStore";

export function App() {
  // Validate the open agent as it changes; the canvas shows the problems.
  useEffect(() => watchAgent(), []);
  const callPanelOpen = useCallStore((s) => s.panelOpen);
  return (
    <div className="app">
      <Toolbar />
      <main>
        <Workspace />
        <Panel />
        {callPanelOpen && <CallPanel />}
      </main>
      <CallAudio />
    </div>
  );
}

/** The canvas, or the open agent's clinic over it (Graph | Clinic, #43). */
function Workspace() {
  const hasAgent = useAgentStore((s) => s.agent !== null);
  const clinicId = useAgentStore((s) => s.agent?.clinic ?? DEFAULT_CLINIC);
  const [view, setView] = useState<"graph" | "clinic">("graph");
  // Fetched again each time the Clinic tab opens, so edits to the file show.
  const [opened, setOpened] = useState(0);
  const clinic = useClinic(clinicId, opened);
  const callsOpen = useDetectionStore((s) => s.open);
  // A link to a heatmap view (#calls=clinic/version/against/signal) opens it: on load,
  // once the first agent is open, and when the address changes to one.
  useEffect(() => {
    if (!hasAgent) return;
    const openFromAddress = () => {
      const wanted = wantedFromAddress();
      if (wanted) void useDetectionStore.getState().setOpen(true, wanted);
    };
    if (!useDetectionStore.getState().open) openFromAddress();
    window.addEventListener("hashchange", openFromAddress);
    return () => window.removeEventListener("hashchange", openFromAddress);
  }, [hasAgent]);
  const problems = clinic && "problems" in clinic ? clinic.problems.length : 0;
  const name = (clinic && "info" in clinic && clinic.info?.name) || clinicId;

  function show(next: "graph" | "clinic") {
    if (next === "clinic" && view !== "clinic") {
      // The side panel shows the agent settings, where the clinic is picked, and
      // nothing hidden under the Clinic view stays selected (Backspace would delete it).
      useAgentStore.getState().select(null);
      setOpened((n) => n + 1);
    }
    setView(next);
  }

  return (
    <div className="canvas-area">
      {hasAgent && (
        <div className="view-switch" role="tablist" aria-label="View">
          <button role="tab" aria-selected={view === "graph"} onClick={() => show("graph")}>
            Graph
          </button>
          <button role="tab" aria-selected={view === "clinic"} onClick={() => show("clinic")}>
            Clinic: {name}
            {problems > 0 && (
              <span className="badge error" title="Problems in the clinic's configuration">
                {problems}
              </span>
            )}
          </button>
        </div>
      )}
      <div className={hasAgent && callsOpen ? "workspace with-issues" : "workspace"}>
        {/* The canvas stays mounted under the Clinic view, so it keeps its zoom and position. */}
        <Canvas />
        {hasAgent && callsOpen && <IssuesPanel />}
        {hasAgent && view === "clinic" && <ClinicView load={clinic} />}
      </div>
    </div>
  );
}
