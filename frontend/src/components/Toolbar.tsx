import { useCallback, useEffect, useState } from "react";

import { getAgent, listAgents, saveAgent, type AgentSummary } from "../api";
import { agentIdFor } from "../agent/names";
import { blankAgent, EXAMPLE_AGENT_ID } from "../agent/templates";
import { selectIsDirty, useAgentStore } from "../store/agentStore";
import { checkAgent } from "../validation/validationStore";
import { CallButton } from "./CallButton";

export function Toolbar() {
  const agentId = useAgentStore((s) => s.agentId);
  const name = useAgentStore((s) => s.agent?.name);
  const dirty = useAgentStore(selectIsDirty);
  const [agents, setAgents] = useState<AgentSummary[]>([]);
  const [message, setMessage] = useState("");

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

  // Cmd/Ctrl+S saves; leaving with unsaved changes asks first.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "s") {
        event.preventDefault();
        void save();
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
      <button onClick={save} disabled={!dirty} title="Save (Cmd/Ctrl+S)">
        Save
      </button>
      <span className={dirty ? "dirty" : "muted"}>{dirty ? "● Unsaved changes" : "All changes saved"}</span>
      <span className="muted">{message}</span>
      <span className="spacer" />
      <CallButton />
    </header>
  );
}
