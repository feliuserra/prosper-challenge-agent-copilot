import { create } from "zustand";

import { getJudgedCall, listJudgedCalls } from "../api";
import { setSideTab } from "../components/sideStore";
import { useAgentStore } from "../store/agentStore";
import type { CallDetail, JudgedCallRow } from "./types";

// The Calls tab's state (#32): the judged calls, and the call open in it with the issue
// in focus. Opening an issue scrolls to its quote and selects its decisive node on the
// canvas, when the open agent has that node. View state only.

type Load<T> = { state: "idle" } | { state: "loading" } | { state: "ready"; data: T } | { state: "error"; error: string };

interface Open {
  workspace: string;
  call: string;
  /** The issue in focus, by index in the call's issues. */
  issue: number | null;
  /** The turn to show; bumped on every focus so the panel scrolls again. */
  turn: number | null;
  nonce: number;
}

interface CallsState {
  list: Load<{ id: string; calls: JudgedCallRow[] }[]>;
  open: Open | null;
  detail: Load<CallDetail>;
  loadList(): Promise<void>;
  /** Open a call in the Calls tab, at an issue if given. */
  openCall(workspace: string, call: string, issue?: number | null): Promise<void>;
  /** Focus one of the open call's issues: its quoted turn and its decisive node. */
  focus(issue: number | null): void;
  close(): void;
}

let request = 0;
let nonce = 0;

export const useCallsStore = create<CallsState>()((set, get) => ({
  list: { state: "idle" },
  open: null,
  detail: { state: "idle" },

  async loadList() {
    set({ list: { state: "loading" } });
    try {
      set({ list: { state: "ready", data: await listJudgedCalls() } });
    } catch (error) {
      set({ list: { state: "error", error: message(error) } });
    }
  },

  async openCall(workspace, call, issue = null) {
    setSideTab("calls");
    const mine = ++request;
    set({ open: { workspace, call, issue: null, turn: null, nonce: ++nonce }, detail: { state: "loading" } });
    try {
      const data = await getJudgedCall(workspace, call);
      if (mine !== request) return;
      set({ detail: { state: "ready", data } });
      if (issue !== null) get().focus(issue);
    } catch (error) {
      if (mine === request) set({ detail: { state: "error", error: message(error) } });
    }
  },

  focus(issue) {
    const { open, detail } = get();
    if (!open || detail.state !== "ready") return;
    const found = issue === null ? null : detail.data.judge?.issues[issue];
    set({ open: { ...open, issue: found ? issue : null, turn: found ? found.quote_turn : null, nonce: ++nonce } });
    if (found) selectNode(found.node);
  },

  close() {
    request++;
    set({ open: null, detail: { state: "idle" } });
  },
}));

/** Select a node on the canvas if the open agent has it (outlining it). */
export function selectNode(node: string): boolean {
  const { agent, select } = useAgentStore.getState();
  if (!agent?.nodes.some((n) => n.name === node)) return false;
  select({ kind: "node", name: node });
  return true;
}

function message(error: unknown) {
  return error instanceof Error ? error.message : String(error);
}
