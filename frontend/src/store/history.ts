import { useStore } from "zustand";

import { selectionExists, useAgentStore } from "./agentStore";

// Undo and redo for the toolbar and the keyboard. History holds the agent only
// (agentStore.ts), so after a step the selection may point at a node or edge
// the step removed (undoing a connect, redoing a delete); it is cleared then,
// and the panel shows the agent settings.

const history = () => useAgentStore.temporal.getState();

export function undo() {
  history().undo();
  dropStaleSelection();
}

export function redo() {
  history().redo();
  dropStaleSelection();
}

function dropStaleSelection() {
  const { agent, selection, select } = useAgentStore.getState();
  if (agent && !selectionExists(agent, selection)) select(null);
}

export const useCanUndo = () => useStore(useAgentStore.temporal, (s) => s.pastStates.length > 0);
export const useCanRedo = () => useStore(useAgentStore.temporal, (s) => s.futureStates.length > 0);

/**
 * Whether a key press belongs to a text field, whose own undo (Cmd/Ctrl+Z) must
 * keep working. Checkboxes and selects have none, so the editor's applies.
 */
export function isTextEntry(target: EventTarget | null): boolean {
  return (
    target instanceof HTMLElement &&
    (target.isContentEditable || target instanceof HTMLTextAreaElement || (target instanceof HTMLInputElement && target.type === "text"))
  );
}
