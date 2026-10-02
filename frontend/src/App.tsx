import { Canvas } from "./canvas/Canvas";
import { Toolbar } from "./components/Toolbar";

export function App() {
  return (
    <div className="app">
      <Toolbar />
      <main>
        <Canvas />
      </main>
    </div>
  );
}
