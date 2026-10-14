import { displayName } from "../agent/names";
import type { Stage } from "../agent/stages";
import { useAgentStore } from "../store/agentStore";
import { Field, NameInput } from "./controls";

const store = () => useAgentStore.getState();

/** A stage (#50): its name, its steps in call order, collapsing it (#51) and ungrouping it. */
export function StagePanel({ stage }: { stage: Stage }) {
  const collapsed = useAgentStore((s) => s.collapsed.includes(stage.name));
  return (
    <>
      <h2>Stage</h2>
      <Field label="Name" hint="Renaming it to another stage's name puts both in one stage.">
        <NameInput
          label="Stage name"
          value={stage.name}
          check={(draft) => (draft.trim() ? null : "Stage name cannot be empty.")}
          commit={(draft) => store().renameStage(stage.name, draft)}
        />
      </Field>
      <Field
        label="Steps"
        hint="In the order a call reaches them. Opening a step expands the stage. A node's stage is set in its panel."
      >
        <ol className="links">
          {stage.nodes.map((name) => (
            <li key={name}>
              <button className="link" title={name} onClick={() => store().select({ kind: "node", name })}>
                {displayName(name)}
              </button>
            </li>
          ))}
        </ol>
      </Field>
      <div className="field">
        <button onClick={() => store().setCollapsed(stage.name, !collapsed)}>
          {collapsed ? "Expand" : "Collapse"}
        </button>
        <div className="hint">
          {collapsed
            ? "Shows every step of the stage on the canvas again."
            : "Shows the stage as one card; what is below it moves up. Only the canvas changes, not the agent."}
        </div>
      </div>
      <div className="field">
        <button onClick={() => store().ungroupStage(stage.name)}>Ungroup</button>
        <div className="hint">Removes the stage. Its nodes stay where they are.</div>
      </div>
    </>
  );
}
