import { useEffect } from "react";

import { CallAudio, CallPanel } from "./call/CallPanel";
import { useCallStore } from "./call/callStore";
import { Canvas } from "./canvas/Canvas";
import { Toolbar } from "./components/Toolbar";
import { Panel } from "./panel/Panel";
import { watchAgent } from "./validation/validationStore";

export function App() {
  // Validate the open agent as it changes; the canvas shows the problems.
  useEffect(() => watchAgent(), []);
  const callPanelOpen = useCallStore((s) => s.panelOpen);
  return (
    <div className="app">
      <Toolbar />
      <main>
        <div className="canvas-area">
          <Canvas />
        </div>
        <Panel />
        {callPanelOpen && <CallPanel />}
      </main>
      <CallAudio />
    </div>
  );
}
