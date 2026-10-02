import { create } from "zustand";
import { temporal } from "zundo";

import { autoLayout, placeMissing, withPositions } from "../agent/layout";
import { placeholderFunctionName, uniqueName } from "../agent/names";
import type { Agent, Edge, Node, Position } from "../agent/schema";

// One agent document plus editor state. Every change to the agent goes through a
// named operation below (ADR 0001), so the canvas, the side panel and later the
// Composer all edit it the same way. Undo history (zundo) tracks the agent only.

export type Selection =
  | { kind: "node"; name: string }
  | { kind: "edge"; source: string; function: string }
  | null;

export type Result = { ok: true } | { ok: false; error: string };

export type NodePatch = Partial<Omit<Node, "name" | "edges">>;
export type EdgePatch = Partial<Edge>;
export type AgentPatch = Partial<Omit<Agent, "nodes" | "initial_node">>;

interface AgentState {
  agent: Agent | null;
  /** File id on the backend (`backend/agents/<id>.json`). */
  agentId: string | null;
  /** JSON of the agent as last loaded or saved, to detect unsaved changes. */
  savedJson: string | null;
  selection: Selection;

  open(agentId: string, agent: Agent, saved?: boolean): void;
  markSaved(): void;
  select(selection: Selection): void;

  addNode(position?: Position): string;
  deleteNode(name: string): Result;
  renameNode(name: string, newName: string): Result;
  updateNode(name: string, patch: NodePatch): void;
  connect(source: string, target: string): string;
  updateEdge(source: string, fn: string, patch: EdgePatch): Result;
  deleteEdge(source: string, fn: string): void;
  setInitialNode(name: string): Result;
  moveNode(name: string, position: Position): void;
  tidyLayout(): void;
  updateAgent(patch: AgentPatch): void;
}

const ok: Result = { ok: true };
const fail = (error: string): Result => ({ ok: false, error });

const edgesOf = (node: Node): Edge[] => node.edges ?? [];
const findNode = (agent: Agent, name: string) => agent.nodes.find((n) => n.name === name);

/** Whether the selected node or edge still exists in `agent`. */
function selectionExists(agent: Agent, selection: Selection): boolean {
  if (!selection) return true;
  const node = findNode(agent, selection.kind === "node" ? selection.name : selection.source);
  if (!node) return false;
  return selection.kind === "node" || edgesOf(node).some((e) => e.function === selection.function);
}

/** Replace the node called `name` with `update(node)`; other nodes keep their identity. */
function mapNode(agent: Agent, name: string, update: (node: Node) => Node): Agent {
  return { ...agent, nodes: agent.nodes.map((n) => (n.name === name ? update(n) : n)) };
}

export const useAgentStore = create<AgentState>()(
  temporal(
    (set, get) => {
      /** Apply a change to the loaded agent. No-op when nothing is open. */
      const change = (update: (agent: Agent) => Agent) => {
        const { agent } = get();
        if (agent) set({ agent: update(agent) });
      };

      return {
        agent: null,
        agentId: null,
        savedJson: null,
        selection: null,

        open(agentId, loaded, saved = true) {
          // Fill in missing canvas positions. They are derived from the agent
          // alone (same result on every load), so they are not unsaved changes.
          const agent = withPositions(loaded);
          set({
            agent,
            agentId,
            savedJson: saved ? JSON.stringify(agent) : null,
            selection: null,
          });
          // A different document: undo must not go back into the previous one.
          useAgentStore.temporal.getState().clear();
        },

        markSaved() {
          set({ savedJson: JSON.stringify(get().agent) });
        },

        select(selection) {
          set({ selection });
        },

        addNode(position) {
          const agent = get().agent;
          if (!agent) return "";
          const name = uniqueName(
            "new_node",
            agent.nodes.map((n) => n.name),
          );
          const node: Node = {
            name,
            task_messages: [{ role: "developer", content: "" }],
            edges: [],
            ...(position ? { ui: position } : {}),
          };
          // Without a position, place it below the existing nodes (they never move).
          const next = placeMissing({ ...agent, nodes: [...agent.nodes, node] });
          set({ agent: next, selection: { kind: "node", name } });
          return name;
        },

        deleteNode(name) {
          const agent = get().agent;
          if (!agent || !findNode(agent, name)) return fail(`No node '${name}'.`);
          if (agent.initial_node === name) {
            return fail("This is the start node. Choose another start node before deleting it.");
          }
          // Outgoing edges go with the node; incoming edges are removed from their sources.
          const nodes = agent.nodes
            .filter((n) => n.name !== name)
            .map((n) =>
              edgesOf(n).some((e) => e.target === name)
                ? { ...n, edges: edgesOf(n).filter((e) => e.target !== name) }
                : n,
            );
          const next = { ...agent, nodes };
          const { selection } = get();
          set({ agent: next, selection: selectionExists(next, selection) ? selection : null });
          return ok;
        },

        renameNode(name, newName) {
          const agent = get().agent;
          const next = newName.trim();
          if (!agent || !findNode(agent, name)) return fail(`No node '${name}'.`);
          if (next === name) return ok;
          if (!next) return fail("Node name cannot be empty.");
          if (findNode(agent, next)) return fail(`A node called '${next}' already exists.`);

          // Name is the identifier (ADR 0003): cascade to edge targets, the start
          // node and the selection, in one step.
          const nodes = agent.nodes.map((n) => {
            const renamed = n.name === name ? { ...n, name: next } : n;
            return edgesOf(renamed).some((e) => e.target === name)
              ? { ...renamed, edges: edgesOf(renamed).map((e) => (e.target === name ? { ...e, target: next } : e)) }
              : renamed;
          });
          const initial_node = agent.initial_node === name ? next : agent.initial_node;

          let { selection } = get();
          if (selection?.kind === "node" && selection.name === name) selection = { kind: "node", name: next };
          if (selection?.kind === "edge" && selection.source === name) selection = { ...selection, source: next };

          set({ agent: { ...agent, nodes, initial_node }, selection });
          return ok;
        },

        updateNode(name, patch) {
          change((agent) => mapNode(agent, name, (n) => ({ ...n, ...patch })));
        },

        connect(source, target) {
          const agent = get().agent;
          const node = agent && findNode(agent, source);
          if (!agent || !node) return "";
          const fn = placeholderFunctionName(
            target,
            edgesOf(node).map((e) => e.function),
          );
          const edge: Edge = { function: fn, description: "", target };
          set({
            agent: mapNode(agent, source, (n) => ({ ...n, edges: [...edgesOf(n), edge] })),
            selection: { kind: "edge", source, function: fn },
          });
          return fn;
        },

        updateEdge(source, fn, patch) {
          const agent = get().agent;
          const node = agent && findNode(agent, source);
          if (!agent || !node || !edgesOf(node).some((e) => e.function === fn)) {
            return fail(`No edge '${fn}' in node '${source}'.`);
          }
          const renamed = patch.function !== undefined && patch.function !== fn;
          // Never store a duplicate, even transiently: (source, function) is the edge id.
          if (renamed && edgesOf(node).some((e) => e.function === patch.function)) {
            return fail(`'${patch.function}' is already used by another edge of this node.`);
          }
          let { selection } = get();
          if (renamed && selection?.kind === "edge" && selection.source === source && selection.function === fn) {
            selection = { ...selection, function: patch.function! };
          }
          set({
            agent: mapNode(agent, source, (n) => ({
              ...n,
              edges: edgesOf(n).map((e) => (e.function === fn ? { ...e, ...patch } : e)),
            })),
            selection,
          });
          return ok;
        },

        deleteEdge(source, fn) {
          const { agent, selection } = get();
          if (!agent) return;
          const next = mapNode(agent, source, (n) => ({
            ...n,
            edges: edgesOf(n).filter((e) => e.function !== fn),
          }));
          set({ agent: next, selection: selectionExists(next, selection) ? selection : null });
        },

        setInitialNode(name) {
          const agent = get().agent;
          if (!agent || !findNode(agent, name)) return fail(`No node '${name}'.`);
          set({ agent: { ...agent, initial_node: name } });
          return ok;
        },

        moveNode(name, position) {
          change((agent) => mapNode(agent, name, (n) => ({ ...n, ui: { ...n.ui, ...position } })));
        },

        tidyLayout() {
          change(autoLayout);
        },

        updateAgent(patch) {
          change((agent) => ({ ...agent, ...patch }));
        },
      };
    },
    {
      // History holds the agent only; selection and save state are UI state.
      partialize: (state) => ({ agent: state.agent }),
      // Record a step only when the agent changed (not on selection changes).
      equality: (past, current) => past.agent === current.agent,
    },
  ),
);

/** True when the open agent differs from what was last loaded or saved. */
export function selectIsDirty(state: AgentState): boolean {
  return state.agent !== null && JSON.stringify(state.agent) !== state.savedJson;
}
