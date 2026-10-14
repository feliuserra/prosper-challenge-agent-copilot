import { useEffect, useId, useState } from "react";

import { listTools, type ToolInfo } from "../api";
import { parseAction } from "../agent/fields";
import { nodeNameError } from "../agent/names";
import { TASK_ROLES } from "../agent/options";
import type { Action, Agent, Node, TaskMessage } from "../agent/schema";
import { stageOf, stagesOf } from "../agent/stages";
import { useAgentStore } from "../store/agentStore";
import { Field, JsonField, LiveText, NameInput } from "./controls";

const store = () => useAgentStore.getState();

// Fetched once per page load: the catalog is fixed in the backend.
let toolsRequest: Promise<{ tools: ToolInfo[]; error?: string }> | null = null;

function useTools() {
  const [state, setState] = useState<{ tools: ToolInfo[]; error?: string } | null>(null);
  useEffect(() => {
    toolsRequest ??= listTools()
      .then((tools) => ({ tools }))
      .catch((error) => {
        toolsRequest = null; // try again next time the panel opens
        return { tools: [], error: `Could not load the tools: ${String(error)}` };
      });
    void toolsRequest.then(setState);
  }, []);
  return state;
}

/** First sentence of a tool description, for the checkbox hint. */
const firstSentence = (text: string) => text.split(/(?<=\.)\s/)[0];

/** `list` with item `i` replaced, removed (`undefined`), or moved up one place. */
function replaceAt<T>(list: T[], i: number, item: T | undefined): T[] {
  return item === undefined ? list.filter((_, j) => j !== i) : list.map((x, j) => (j === i ? item : x));
}
function moveUp<T>(list: T[], i: number): T[] {
  const next = [...list];
  [next[i - 1], next[i]] = [next[i], next[i - 1]];
  return next;
}

export function NodePanel({ node, agent }: { node: Node; agent: Agent }) {
  const [error, setError] = useState("");
  const isStart = agent.initial_node === node.name;
  const edges = node.edges ?? [];
  // Backend rule (agent_builder/builder.py): explicit post-actions replace the
  // end_conversation action that `end` adds, so the call would not hang up.
  const endIsOverridden =
    node.end && (node.post_actions ?? []).length > 0 && !node.post_actions!.some((a) => a.type === "end_conversation");

  return (
    <>
      <h2>Node</h2>
      <Field label="Name">
        <NameInput
          label="Node name"
          value={node.name}
          check={(draft) =>
            nodeNameError(
              agent.nodes.map((n) => n.name),
              node.name,
              draft,
            )
          }
          commit={(draft) => store().renameNode(node.name, draft)}
        />
      </Field>
      <div className="field row">
        {isStart ? (
          <span className="badge start">Start node</span>
        ) : (
          <button onClick={() => store().setInitialNode(node.name)}>Set as start</button>
        )}
        <label className="check">
          <input
            type="checkbox"
            checked={!!node.end}
            onChange={(event) => store().updateNode(node.name, { end: event.target.checked || undefined })}
          />
          End node
        </label>
      </div>
      {node.end && (
        <div className={endIsOverridden ? "field field-error" : "field hint"}>
          {endIsOverridden
            ? "This node has After actions, which replace the hang-up. Add an end_conversation action to end the call."
            : "The bot gives its reply for this node, then hangs up."}
        </div>
      )}

      <StageField node={node} agent={agent} />

      <TaskMessages node={node} />

      <Tools node={node} />

      <Field label="Role" hint="Replaces the agent persona for this node only. Leave empty to use the persona.">
        <LiveText
          label="Role"
          rows={3}
          value={node.role_message ?? ""}
          onChange={(role_message) => store().updateNode(node.name, { role_message: role_message || undefined })}
        />
      </Field>

      <Actions node={node} which="pre_actions" label="Before the step" hint="Run when the conversation enters this node." />
      <Actions node={node} which="post_actions" label="After the step" hint="Run after the bot's reply in this node." />

      <Field label="Transitions" hint="Drag from this node's bottom dot to another node to add one.">
        {edges.length ? (
          <ul className="links">
            {edges.map((e) => (
              <li key={e.function}>
                <button
                  className="link mono"
                  onClick={() => store().select({ kind: "edge", source: node.name, function: e.function })}
                >
                  {e.function}
                </button>{" "}
                → {e.target}
              </li>
            ))}
          </ul>
        ) : (
          <div className="muted">None.</div>
        )}
      </Field>

      <div className="field">
        <button
          className="danger"
          disabled={isStart}
          title={isStart ? "Choose another start node first" : undefined}
          onClick={() => {
            const result = store().deleteNode(node.name);
            if (!result.ok) setError(result.error);
          }}
        >
          Delete node
        </button>
        {isStart && <div className="hint">The start node cannot be deleted. Set another node as start first.</div>}
        {error && <div className="field-error">{error}</div>}
      </div>
    </>
  );
}

function TaskMessages({ node }: { node: Node }) {
  const messages = node.task_messages ?? [];
  const write = (next: TaskMessage[]) => store().updateNode(node.name, { task_messages: next.length ? next : undefined });

  return (
    <Field label="Task" hint="What the bot should do in this step. Messages go to the LLM in this order.">
      {messages.map((message, i) => (
        <div className="list-item" key={i}>
          <div className="row">
            <select
              aria-label="Message role"
              value={message.role}
              onChange={(event) => write(replaceAt(messages, i, { ...message, role: event.target.value }))}
            >
              {/* Keep a role the editor does not offer, e.g. from a hand-written file. */}
              {[...new Set([...TASK_ROLES, message.role])].map((role) => (
                <option key={role} value={role}>
                  {role}
                </option>
              ))}
            </select>
            <span className="spacer" />
            {i > 0 && (
              <button className="small" onClick={() => write(moveUp(messages, i))} title="Move up">
                ↑
              </button>
            )}
            <button className="small" onClick={() => write(replaceAt<TaskMessage>(messages, i, undefined))}>
              Remove
            </button>
          </div>
          <LiveText
            label="Message content"
            rows={4}
            value={message.content}
            onChange={(content) => write(replaceAt(messages, i, { ...message, content }))}
          />
        </div>
      ))}
      <button className="small" onClick={() => write([...messages, { role: "developer", content: "" }])}>
        + Task message
      </button>
    </Field>
  );
}

/** Catalog tools as checkboxes, kept in catalog order; tools the catalog lacks stay until unchecked. */
function Tools({ node }: { node: Node }) {
  const catalog = useTools();
  const listed = node.tools ?? [];
  const write = (next: string[]) => store().updateNode(node.name, { tools: next.length ? next : undefined });
  const names = catalog?.tools.map((t) => t.name) ?? [];
  const unknown = listed.filter((t) => !names.includes(t));
  const toggle = (name: string, on: boolean) =>
    write([...names.filter((n) => (n === name ? on : listed.includes(n))), ...unknown.filter((n) => n !== name || on)]);

  return (
    <Field
      label="Tools"
      hint="The bot can call these during this step to look things up or act. The conversation stays in this node; transitions still move it on."
    >
      {!catalog && <div className="muted">Loading…</div>}
      {catalog?.error && <div className="field-error">{catalog.error}</div>}
      {catalog?.tools.map((tool) => (
        <div className="tool-option" key={tool.name}>
          <label className="check" title={tool.description}>
            <input type="checkbox" checked={listed.includes(tool.name)} onChange={(e) => toggle(tool.name, e.target.checked)} />
            <span className="mono">{tool.name}</span>
          </label>
          <div className="hint">{firstSentence(tool.description)}</div>
        </div>
      ))}
      {catalog &&
        unknown.map((name) => (
          <label className="check" key={name}>
            <input type="checkbox" checked onChange={() => toggle(name, false)} />
            <span className="mono">{name}</span> <span className="muted">(not in the catalog)</span>
          </label>
        ))}
    </Field>
  );
}

type ActionsProps = { node: Node; which: "pre_actions" | "post_actions"; label: string; hint: string };

/** `tts_say` actions as a text field; any other action as raw JSON. */
function Actions({ node, which, label, hint }: ActionsProps) {
  const actions = node[which] ?? [];
  const write = (next: Action[]) => store().updateNode(node.name, { [which]: next.length ? next : undefined });

  return (
    <Field label={label} hint={hint}>
      {actions.map((action, i) => (
        <div className="list-item" key={i}>
          <div className="row">
            <strong>{action.type === "tts_say" ? "Say" : "Action (JSON)"}</strong>
            <span className="spacer" />
            {i > 0 && (
              <button className="small" onClick={() => write(moveUp(actions, i))} title="Move up">
                ↑
              </button>
            )}
            <button className="small" onClick={() => write(replaceAt<Action>(actions, i, undefined))}>
              Remove
            </button>
          </div>
          {action.type === "tts_say" ? (
            <LiveText
              label="Text to say"
              rows={2}
              value={typeof action.text === "string" ? action.text : ""}
              onChange={(text) => write(replaceAt(actions, i, { ...action, text }))}
            />
          ) : (
            <JsonField
              label="Action JSON"
              rows={3}
              value={action}
              parse={parseAction}
              onValid={(value) => write(replaceAt(actions, i, value))}
            />
          )}
        </div>
      ))}
      <div className="row">
        <button className="small" onClick={() => write([...actions, { type: "tts_say", text: "" }])}>
          + Say text
        </button>
        <button className="small" onClick={() => write([...actions, { type: "end_conversation" }])}>
          + Other action
        </button>
      </div>
    </Field>
  );
}

/** The node's stage: pick one of the agent's stages or type a new one; empty for none. */
function StageField({ node, agent }: { node: Node; agent: Agent }) {
  const listId = useId();
  return (
    <Field label="Stage" hint="Groups this node with others in a frame on the canvas. Leave empty for none.">
      <NameInput
        label="Stage"
        value={stageOf(node) ?? ""}
        placeholder="No stage"
        list={listId}
        check={() => null}
        commit={(draft) => store().setStage(node.name, draft)}
      />
      <datalist id={listId}>
        {stagesOf(agent).map((stage) => (
          <option key={stage.name} value={stage.name} />
        ))}
      </datalist>
    </Field>
  );
}
