import { useEffect } from "react";

import { Canvas } from "./canvas/Canvas";
import { Toolbar } from "./components/Toolbar";
import { Panel } from "./panel/Panel";
import { watchAgent } from "./validation/validationStore";

export function App() {
  // Validate the open agent as it changes; the canvas shows the problems.
  useEffect(() => watchAgent(), []);
  return (
    <div className="app">
      <Toolbar />
      <main>
        <div className="canvas-area">
          <Canvas />
        </div>
        <Panel />
      </main>
    </div>
  );
}
