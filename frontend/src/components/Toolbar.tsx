import { useCallback, useEffect, useRef, useState } from "react";

import { getAgent, listAgents, saveAgent, type AgentSummary } from "../api";
import { agentFileText, parseAgentFile } from "../agent/file";
import { agentIdFor } from "../agent/names";
import { blankAgent, EXAMPLE_AGENT_ID } from "../agent/templates";
import { setPanelOpen, useCallStore } from "../call/callStore";
import { selectIsDirty, useAgentStore } from "../store/agentStore";
import { isTextEntry, redo, undo, useCanRedo, useCanUndo } from "../store/history";
import { checkAgent } from "../validation/validationStore";

export function Toolbar() {
  const agentId = useAgentStore((s) => s.agentId);
  const name = useAgentStore((s) => s.agent?.name);
  const dirty = useAgentStore(selectIsDirty);
  const [agents, setAgents] = useState<AgentSummary[]>([]);
  const [message, setMessage] = useState("");
  const canUndo = useCanUndo();
  const canRedo = useCanRedo();
  const fileInput = useRef<HTMLInputElement>(null);

  const refresh = useCallback(async () => setAgents(await listAgents()), []);

  const confirmDiscard = () => !selectIsDirty(useAgentStore.getState()) || confirm("Discard unsaved changes?");

  const open = useCallback(async (id: string) => {
    try {
      useAgentStore.getState().open(id, await getAgent(id));
      setMessage("");
    } catch (error) {
      setMessage(String(error));
    }
  }, []);

  async function create(fromExample: boolean) {
    if (!confirmDiscard()) return;
    const newName = prompt("Name of the new agent")?.trim();
    if (!newName) return;
    const agent = fromExample ? { ...(await getAgent(EXAMPLE_AGENT_ID)), name: newName } : blankAgent(newName);
    const id = agentIdFor(newName, agents.map((a) => a.id));
    // Not saved yet: shows as unsaved until the first save creates the file.
    useAgentStore.getState().open(id, agent, false);
    setMessage("");
  }

  // Opens the file as a new agent, like "New": it is saved under its own id.
  async function importFile(file: File) {
    const parsed = parseAgentFile(await file.text());
    if (!parsed.ok) {
      setMessage(`Cannot import ${file.name}: ${parsed.error}.`);
      return;
    }
    const id = agentIdFor(parsed.agent.name, agents.map((a) => a.id));
    useAgentStore.getState().open(id, parsed.agent, false);
    setMessage(`Imported ${file.name} as a new agent. Save to keep it.`);
  }

  /** Downloads the agent as it is in the editor, unsaved changes included. */
  function exportFile() {
    const { agent, agentId } = useAgentStore.getState();
    if (!agent || !agentId) return;
    const url = URL.createObjectURL(new Blob([agentFileText(agent)], { type: "application/json" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = `${agentId}.json`;
    link.click();
    URL.revokeObjectURL(url);
  }

  // A field being typed in is one history step (editSession.ts): leave it first,
  // so the step is complete and history is no longer paused.
  const step = (action: () => void) => () => {
    if (document.activeElement instanceof HTMLElement) document.activeElement.blur();
    action();
  };

  const save = useCallback(async () => {
    // Names are written when their field is left: leave it first (Cmd/Ctrl+S
    // can be pressed while typing one), so the save includes it.
    if (document.activeElement instanceof HTMLElement) document.activeElement.blur();
    const { agent, agentId } = useAgentStore.getState();
    if (!agent || !agentId) return;
    try {
      // The backend validates on save; its errors go to the problems list.
      const errors = await checkAgent(agent, (draft) => saveAgent(agentId, draft));
      if (errors.length) {
        setMessage(`Not saved: ${errors.length} error${errors.length === 1 ? "" : "s"}, see Problems.`);
        return;
      }
      useAgentStore.getState().markSaved();
      setMessage("Saved");
      await refresh();
    } catch (error) {
      setMessage(String(error));
    }
  }, [refresh]);

  // Load the list and open the example (or the first agent) on start.
  useEffect(() => {
    listAgents()
      .then((list) => {
        setAgents(list);
        const first = list.find((a) => a.id === EXAMPLE_AGENT_ID) ?? list[0];
        if (first) return open(first.id);
      })
      .catch((error) => setMessage(String(error)));
  }, [open]);

  // Cmd/Ctrl+S saves; Cmd/Ctrl+Z undoes, with Shift (or Ctrl+Y) redoes, except
  // in a text field, which keeps its own undo. Leaving with unsaved changes asks first.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (!(event.metaKey || event.ctrlKey)) return;
      const key = event.key.toLowerCase();
      if (key === "s") {
        event.preventDefault();
        void save();
      } else if ((key === "z" || (key === "y" && event.ctrlKey)) && !isTextEntry(event.target)) {
        event.preventDefault();
        if (key === "y" || event.shiftKey) redo();
        else undo();
      }
    };
    const onUnload = (event: BeforeUnloadEvent) => {
      if (selectIsDirty(useAgentStore.getState())) event.preventDefault();
    };
    window.addEventListener("keydown", onKey);
    window.addEventListener("beforeunload", onUnload);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("beforeunload", onUnload);
    };
  }, [save]);

  const listed = agents.some((a) => a.id === agentId);

  return (
    <header className="toolbar">
      <select
        value={agentId ?? ""}
        onChange={(event) => confirmDiscard() && open(event.target.value)}
        aria-label="Open agent"
      >
        {!listed && agentId && <option value={agentId}>{name} (new)</option>}
        {agents.map((a) => (
          <option key={a.id} value={a.id}>
            {a.name ?? a.id}
          </option>
        ))}
      </select>
      <button onClick={() => create(false)}>New blank</button>
      <button onClick={() => create(true)}>New from example</button>
      <button onClick={() => confirmDiscard() && fileInput.current?.click()} title="Open an agent JSON file as a new agent">
        Import
      </button>
      <input
        ref={fileInput}
        type="file"
        accept=".json,application/json"
        hidden
        onChange={(event) => {
          const file = event.target.files?.[0];
          // Cleared, so choosing the same file again still fires a change.
          event.target.value = "";
          if (file) void importFile(file);
        }}
      />
      <button onClick={exportFile} disabled={!agentId} title="Download this agent as JSON, unsaved changes included">
        Export
      </button>
      <span className="toolbar-sep" />
      <button onClick={step(undo)} disabled={!canUndo} title="Undo (Cmd/Ctrl+Z)">
        Undo
      </button>
      <button onClick={step(redo)} disabled={!canRedo} title="Redo (Cmd/Ctrl+Shift+Z)">
        Redo
      </button>
      <button onClick={save} disabled={!dirty} title="Save (Cmd/Ctrl+S)">
        Save
      </button>
      <span className={dirty ? "dirty" : "muted"}>{dirty ? "● Unsaved changes" : "All changes saved"}</span>
      <span className="muted">{message}</span>
      <span className="spacer" />
      <CallToggle />
    </header>
  );
}

/** Opens and closes the test call panel, and shows when a call is on. */
function CallToggle() {
  const open = useCallStore((s) => s.panelOpen);
  const phase = useCallStore((s) => s.phase);
  const label = phase === "in-call" ? "● In call" : phase === "idle" ? "Test call" : "● Connecting…";
  return (
    <button onClick={() => setPanelOpen(!open)} aria-pressed={open} className={phase === "in-call" ? "call-live" : undefined}>
      {label}
    </button>
  );
}
