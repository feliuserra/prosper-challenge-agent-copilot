import { displayName } from "../agent/names";
import type { Stage } from "../agent/stages";
import { useAgentStore } from "../store/agentStore";
import { Field, NameInput } from "./controls";

const store = () => useAgentStore.getState();

/** A stage (#50): its name, its steps in call order, and ungrouping it. */
export function StagePanel({ stage }: { stage: Stage }) {
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
      <Field label="Steps" hint="In the order a call reaches them. A node's stage is set in its panel.">
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
        <button onClick={() => store().ungroupStage(stage.name)}>Ungroup</button>
        <div className="hint">Removes the stage. Its nodes stay where they are.</div>
      </div>
    </>
  );
}
