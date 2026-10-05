import { create } from "zustand";

import { validateAgent, type ValidationIssue } from "../api";
import type { Agent } from "../agent/schema";
import { useAgentStore } from "../store/agentStore";

// The backend validator is the authority on what can run (ADR 0004), so the
// editor asks it: shortly after every change, on save and before a test call.
// The result is UI state, kept apart from the agent store and its undo history.

interface ValidationState {
  /** Errors from the latest check of the open agent. */
  errors: ValidationIssue[];
  /** Why the latest check could not run (e.g. the backend is down), or null. */
  failure: string | null;
}

export const useValidationStore = create<ValidationState>()(() => ({ errors: [], failure: null }));

// Checks can finish out of order (a debounced check, then a save). Each one takes
// a number when it starts, and only a check newer than the last published one
// may publish, so an older agent's errors never replace a newer agent's.
let started = 0;
let published = 0;

/**
 * Validate `agent` with `run` (by default `POST /composer/validate`; a save
 * passes `saveAgent`, which returns the same errors) and publish the result.
 * Returns the errors. Throws if `run` does, after publishing the failure.
 */
export async function checkAgent(
  agent: Agent,
  run: (agent: Agent) => Promise<ValidationIssue[]> = validateAgent,
): Promise<ValidationIssue[]> {
  const check = ++started;
  const publish = (state: ValidationState) => {
    if (check <= published) return;
    published = check;
    useValidationStore.setState(state);
  };
  try {
    const errors = await run(agent);
    publish({ errors, failure: null });
    return errors;
  } catch (error) {
    publish({ errors: useValidationStore.getState().errors, failure: String(error) });
    throw error;
  }
}

/** Forget the previous agent's result, including checks still running for it. */
export function clearErrors() {
  published = ++started;
  useValidationStore.setState({ errors: [], failure: null });
}

/**
 * Keep the open agent checked: `delay` ms after it stops changing (typing, a
 * drag), and at once when another agent is opened. Returns a function that stops.
 */
export function watchAgent(delay = 400, run = validateAgent): () => void {
  let timer: ReturnType<typeof setTimeout> | undefined;
  const check = (agent: Agent | null) => {
    clearTimeout(timer);
    // A failure is published for the problems list; nothing else to do here.
    if (agent) checkAgent(agent, run).catch(() => {});
  };

  check(useAgentStore.getState().agent);
  const unsubscribe = useAgentStore.subscribe((state, previous) => {
    if (state.agentId !== previous.agentId) {
      clearErrors();
      check(state.agent);
    } else if (state.agent !== previous.agent) {
      clearTimeout(timer);
      timer = setTimeout(() => check(useAgentStore.getState().agent), delay);
    }
  });
  return () => {
    clearTimeout(timer);
    unsubscribe();
  };
}
