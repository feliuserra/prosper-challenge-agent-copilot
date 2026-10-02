import {
  addField,
  fieldNameError,
  fieldsJson,
  fieldsOf,
  parseFieldsJson,
  removeField,
  renameField,
  setRequired,
  updateFieldSpec,
} from "../agent/fields";
import { functionNameError } from "../agent/names";
import { FIELD_TYPES } from "../agent/options";
import type { Agent, Edge } from "../agent/schema";
import { useAgentStore, type EdgePatch } from "../store/agentStore";
import { Field, JsonField, LiveText, NameInput } from "./controls";

const store = () => useAgentStore.getState();

export function EdgePanel({ source, edge, agent }: { source: string; edge: Edge; agent: Agent }) {
  const siblings = (agent.nodes.find((n) => n.name === source)?.edges ?? []).map((e) => e.function);
  const update = (patch: EdgePatch) => store().updateEdge(source, edge.function, patch);

  return (
    <>
      <h2>Transition</h2>
      <div className="field muted">
        From{" "}
        <button className="link" onClick={() => store().select({ kind: "node", name: source })}>
          {source}
        </button>
      </div>
      <Field label="Function name" hint="The tool the LLM calls to take this transition.">
        <NameInput
          label="Function name"
          className="mono"
          value={edge.function}
          check={(draft) => functionNameError(siblings, edge.function, draft)}
          commit={(draft) => update({ function: draft })}
        />
      </Field>
      <Field
        label="When to take it"
        hint="The function's description: it is what tells the LLM when to call it and move on, so be specific."
      >
        <LiveText
          label="Description"
          rows={3}
          value={edge.description}
          onChange={(description) => update({ description })}
        />
      </Field>
      <Field label="Goes to">
        <select aria-label="Target node" value={edge.target} onChange={(event) => update({ target: event.target.value })}>
          {!agent.nodes.some((n) => n.name === edge.target) && (
            <option value={edge.target}>{edge.target} (missing)</option>
          )}
          {agent.nodes.map((n) => (
            <option key={n.name} value={n.name}>
              {n.name}
            </option>
          ))}
        </select>
      </Field>

      <CollectedFields edge={edge} update={update} />

      <details className="field">
        <summary>Edit fields as JSON</summary>
        <JsonField
          label="Collected fields JSON"
          rows={12}
          value={fieldsJson(edge)}
          parse={parseFieldsJson}
          onValid={update}
        />
        <div className="hint">For what the table does not show, such as a list of allowed values ("enum").</div>
      </details>

      <div className="field">
        <button className="danger" onClick={() => store().deleteEdge(source, edge.function)}>
          Delete transition
        </button>
      </div>
    </>
  );
}

function CollectedFields({ edge, update }: { edge: Edge; update: (patch: EdgePatch) => void }) {
  const fields = fieldsOf(edge);
  return (
    <Field
      label="Collected fields"
      hint="Values the LLM fills in when it takes this transition, e.g. the caller's name. Required ones must be known first."
    >
      {fields.map((field) => {
        const type = typeof field.spec.type === "string" ? field.spec.type : "";
        const extra = Object.keys(field.spec).filter((k) => k !== "type" && k !== "description");
        return (
          <div className="collected" key={field.name}>
            <div className="row">
              <div className="grow">
                <NameInput
                  label="Field name"
                  className="mono"
                  value={field.name}
                  check={(draft) => fieldNameError(edge, field.name, draft)}
                  commit={(draft) => update(renameField(edge, field.name, draft))}
                />
              </div>
              <select
                aria-label="Field type"
                value={type}
                onChange={(event) => update(updateFieldSpec(edge, field.name, { type: event.target.value }))}
              >
                {!FIELD_TYPES.includes(type) && <option value={type}>{type || "(no type)"}</option>}
                {FIELD_TYPES.map((t) => (
                  <option key={t} value={t}>
                    {t}
                  </option>
                ))}
              </select>
              <label className="check" title="The LLM must know this value before it can take the transition">
                <input
                  type="checkbox"
                  checked={field.required}
                  onChange={(event) => update(setRequired(edge, field.name, event.target.checked))}
                />
                Required
              </label>
              <button className="small" aria-label={`Remove field ${field.name}`} onClick={() => update(removeField(edge, field.name))}>
                ×
              </button>
            </div>
            <LiveText
              label="Field description"
              value={typeof field.spec.description === "string" ? field.spec.description : ""}
              placeholder="Description, e.g. Caller's full name"
              onChange={(description) =>
                update(updateFieldSpec(edge, field.name, { description: description || undefined }))
              }
            />
            {extra.length > 0 && <div className="hint">Also set: {extra.join(", ")} (edit as JSON).</div>}
          </div>
        );
      })}
      <button className="small" onClick={() => update(addField(edge))}>
        + Field
      </button>
    </Field>
  );
}
