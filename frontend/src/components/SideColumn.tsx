import { create } from "zustand";

import { CallPanel } from "../call/CallPanel";
import { useCallStore } from "../call/callStore";
import { CopilotPanel } from "../copilot/CopilotPanel";
import { useCopilotStore } from "../copilot/copilotStore";

// The right-hand column (#31): the Copilot and the test call (#7) as tabs, in the
// place the call panel had, so the editor keeps three columns.

export type SideTab = "copilot" | "call";

export const useSideStore = create<{ tab: SideTab | null }>(() => ({ tab: "copilot" }));

/** Open the column on a tab, or close it with null. */
export const setSideTab = (tab: SideTab | null) => useSideStore.setState({ tab });

export function SideColumn() {
  const tab = useSideStore((s) => s.tab);
  if (!tab) return null;
  // `nokey`: React Flow ignores key presses from here (Backspace in a text area).
  return (
    <aside className="side-column nokey">
      <div className="panel-tabs side-tabs" role="tablist">
        <button role="tab" aria-selected={tab === "copilot"} onClick={() => setSideTab("copilot")}>
          Copilot
        </button>
        <button role="tab" aria-selected={tab === "call"} onClick={() => setSideTab("call")}>
          Test call
        </button>
        <span className="spacer" />
        <button className="link" onClick={() => setSideTab(null)} title="Close (a call or a Copilot step keeps going)">
          Close
        </button>
      </div>
      <div className="side-body">{tab === "copilot" ? <CopilotPanel /> : <CallPanel />}</div>
    </aside>
  );
}

/** The toolbar's buttons for the column's tabs; each shows when its work is going on. */
export function SideToggles() {
  const tab = useSideStore((s) => s.tab);
  const phase = useCallStore((s) => s.phase);
  const busy = useCopilotStore((s) => s.step?.running === true);
  const callLabel = phase === "in-call" ? "● In call" : phase === "idle" ? "Test call" : "● Connecting…";
  const toggle = (which: SideTab) => setSideTab(tab === which ? null : which);
  return (
    <>
      <button
        onClick={() => toggle("copilot")}
        aria-pressed={tab === "copilot"}
        className={busy ? "call-live" : undefined}
      >
        {busy ? "● Copilot working" : "Copilot"}
      </button>
      <button
        onClick={() => toggle("call")}
        aria-pressed={tab === "call"}
        className={phase === "in-call" ? "call-live" : undefined}
      >
        {callLabel}
      </button>
    </>
  );
}
