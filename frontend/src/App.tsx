import { Canvas } from "./canvas/Canvas";
import { Toolbar } from "./components/Toolbar";
import { Panel } from "./panel/Panel";

export function App() {
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
