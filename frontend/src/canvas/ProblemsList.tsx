import { useState } from "react";
import { useReactFlow } from "@xyflow/react";

import { useAgentStore } from "../store/agentStore";
import { problemLocation, problemNodes, problemSelection, type Problem } from "../validation/problems";
import { useValidationStore } from "../validation/validationStore";

const count = (n: number, what: string) => `${n} ${what}${n === 1 ? "" : "s"}`;

/**
 * Everything wrong with the agent, in a strip below the canvas. Clicking a
 * problem selects its node or edge (the side panel opens its editor) and brings
 * it into view; an agent-level problem clears the selection, which shows the
 * agent settings.
 */
export function ProblemsList({ problems }: { problems: Problem[] }) {
  const failure = useValidationStore((s) => s.failure);
  const [open, setOpen] = useState(true);
  const { fitView } = useReactFlow();

  const errors = problems.filter((p) => p.severity === "error").length;
  const warnings = problems.length - errors;
  const summary =
    [errors && count(errors, "error"), warnings && count(warnings, "warning")].filter(Boolean).join(", ") ||
    (failure ? "Not checked" : "No problems");

  function show(problem: Problem) {
    const { agent, select } = useAgentStore.getState();
    select(problemSelection(problem));
    const nodes = agent ? problemNodes(agent, problem) : [];
    if (nodes.length) void fitView({ nodes: nodes.map((id) => ({ id })), maxZoom: 1, duration: 300 });
  }

  // `nokey`: Backspace on a focused problem must not delete the selected node.
  return (
    <section className="problems nokey" aria-label="Problems">
      <button className="problems-header" onClick={() => setOpen(!open)} aria-expanded={open}>
        <span>Problems</span>
        <span className={errors ? "problems-summary error" : "problems-summary muted"}>{summary}</span>
        {problems.length > 0 && <span className="muted">{open ? "▾" : "▸"}</span>}
      </button>
      {failure && <div className="problems-failure">Could not check the agent: {failure}</div>}
      {open && problems.length > 0 && (
        <ul className="problems-list">
          {problems.map((problem, i) => (
            <li key={i}>
              <button className="problem" onClick={() => show(problem)}>
                <span className={`problem-dot ${problem.severity}`} aria-label={problem.severity} />
                <span className="problem-text">
                  <span>{problem.message}</span>
                  <span className="problem-location mono">{problemLocation(problem)}</span>
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
