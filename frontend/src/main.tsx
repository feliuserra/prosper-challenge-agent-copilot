import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./App";
import "./index.css";
import { useAgentStore } from "./store/agentStore";

// Dev only: inspect or drive the store from the browser console.
if (import.meta.env.DEV) Object.assign(window, { agentStore: useAgentStore });

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
