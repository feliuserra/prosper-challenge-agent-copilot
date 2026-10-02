import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { ValidationIssue } from "../api";
import type { Agent } from "../agent/schema";
import { blankAgent } from "../agent/templates";
import { useAgentStore } from "../store/agentStore";
import { checkAgent, clearErrors, useValidationStore, watchAgent } from "./validationStore";

const issue = (message: string): ValidationIssue => ({ message, node: null, edge: null });
const messages = () => useValidationStore.getState().errors.map((e) => e.message);
const store = () => useAgentStore.getState();

/** A stand-in for the backend whose answers each test gives, in any order. */
function fakeBackend() {
  const calls: { agent: Agent; answer(errors: ValidationIssue[]): void; fail(error: Error): void }[] = [];
  const run = (agent: Agent) =>
    new Promise<ValidationIssue[]>((answer, fail) => calls.push({ agent, answer, fail }));
  return { calls, run };
}

beforeEach(() => {
  store().open("a", blankAgent("A"));
  clearErrors();
});

describe("checkAgent", () => {
  it("publishes the errors and returns them", async () => {
    const errors = [issue("Agent needs a name.")];
    await expect(checkAgent(store().agent!, async () => errors)).resolves.toBe(errors);
    expect(messages()).toEqual(["Agent needs a name."]);
  });

  it("never lets an older check replace a newer one's result", async () => {
    const backend = fakeBackend();
    const older = checkAgent(store().agent!, backend.run);
    const newer = checkAgent(store().agent!, backend.run);
    backend.calls[1].answer([]);
    await newer;
    backend.calls[0].answer([issue("stale")]);
    await older;
    expect(messages()).toEqual([]);
  });

  it("publishes a failure, keeps the last errors and rethrows", async () => {
    await checkAgent(store().agent!, async () => [issue("known")]);
    await expect(
      checkAgent(store().agent!, async () => {
        throw new Error("backend down");
      }),
    ).rejects.toThrow("backend down");
    expect(useValidationStore.getState()).toMatchObject({ failure: "Error: backend down" });
    expect(messages()).toEqual(["known"]);
  });
});

describe("watchAgent", () => {
  let stop = () => {};
  beforeEach(() => void vi.useFakeTimers());
  afterEach(() => {
    stop();
    vi.useRealTimers();
  });

  it("checks the open agent at once, then once after the changes stop", async () => {
    const backend = fakeBackend();
    stop = watchAgent(400, backend.run);
    expect(backend.calls).toHaveLength(1);

    for (const name of ["B", "Bo", "Bob"]) {
      store().updateAgent({ name });
      await vi.advanceTimersByTimeAsync(100);
    }
    expect(backend.calls).toHaveLength(1);
    await vi.advanceTimersByTimeAsync(300);
    expect(backend.calls).toHaveLength(2);
    expect(backend.calls[1].agent.name).toBe("Bob");

    backend.calls[1].answer([issue("found")]);
    await vi.advanceTimersByTimeAsync(0);
    expect(messages()).toEqual(["found"]);
  });

  it("on opening another agent, drops the previous agent's errors and checks the new one at once", async () => {
    const backend = fakeBackend();
    stop = watchAgent(400, backend.run);
    backend.calls[0].answer([issue("from A")]);
    await vi.advanceTimersByTimeAsync(0);
    expect(messages()).toEqual(["from A"]);

    // An edit of A is pending and a check of A is still running when B opens.
    store().updateAgent({ name: "A2" });
    await vi.advanceTimersByTimeAsync(400);
    store().open("b", blankAgent("B"));
    expect(messages()).toEqual([]);
    expect(backend.calls.map((c) => c.agent.name)).toEqual(["A", "A2", "B"]);

    backend.calls[2].answer([issue("from B")]);
    backend.calls[1].answer([issue("from A2")]);
    await vi.advanceTimersByTimeAsync(400);
    expect(messages()).toEqual(["from B"]);
    expect(backend.calls).toHaveLength(3);
  });
});
