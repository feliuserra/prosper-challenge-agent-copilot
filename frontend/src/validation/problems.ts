import { useMemo } from "react";

import type { ValidationIssue } from "../api";
import type { Agent } from "../agent/schema";
import { useAgentStore, type Selection } from "../store/agentStore";
import { useValidationStore } from "./validationStore";
import { agentWarnings } from "./warnings";

// One list for everything wrong with the agent: backend validation errors (#6),
// which block a test call, and client-side authoring warnings (#9), which do not.
// Problems point at a node or edge by name (`node`, `edge` = function name),
// never by parsing their message.

export type Severity = "error" | "warning";

export type Problem = ValidationIssue & { severity: Severity };

/**
 * The problems of the open agent, errors first. Errors come from the latest
 * backend check (debounced); warnings are computed from the draft as it is now.
 */
export function useProblems(): Problem[] {
  const errors = useValidationStore((s) => s.errors);
  const agent = useAgentStore((s) => s.agent);
  const warnings = useMemo(() => (agent ? agentWarnings(agent) : []), [agent]);
  return useMemo(
    () => [...errors.map((e) => ({ ...e, severity: "error" as const })), ...warnings],
    [errors, warnings],
  );
}

/** What a problem points at: an edge, a node, or (null) the agent's own settings. */
export function problemSelection(problem: Problem): Selection {
  if (problem.node === null) return null;
  if (problem.edge === null) return { kind: "node", name: problem.node };
  return { kind: "edge", source: problem.node, function: problem.edge };
}

/** Where a problem is, for the list: "node", "node › function" or "Agent". */
export function problemLocation(problem: Problem): string {
  if (problem.node === null) return "Agent";
  return problem.edge === null ? problem.node : `${problem.node} › ${problem.edge}`;
}

/**
 * The canvas nodes to bring into view for a problem: its node, and for an edge
 * also the target, so the whole transition is visible. Nodes that do not exist
 * (any more) are left out.
 */
export function problemNodes(agent: Agent, problem: Problem): string[] {
  const node = agent.nodes.find((n) => n.name === problem.node);
  if (!node) return [];
  const target = node.edges?.find((e) => e.function === problem.edge)?.target;
  const ids = [node.name];
  if (target !== undefined && target !== node.name && agent.nodes.some((n) => n.name === target)) ids.push(target);
  return ids;
}
