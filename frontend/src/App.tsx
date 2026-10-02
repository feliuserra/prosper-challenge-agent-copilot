import { Outline } from "./components/Outline";
import { Toolbar } from "./components/Toolbar";

export function App() {
  return (
    <div className="app">
      <Toolbar />
      <main>
        <Outline />
      </main>
    </div>
  );
}
