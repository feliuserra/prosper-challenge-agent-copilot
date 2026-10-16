import { create } from "zustand";

import { getDetection } from "../api";
import { useAgentStore } from "../store/agentStore";
import { defaultOptions, hashFor, optionsFor, optionsFromHash, type HeatOptions } from "./heat";
import { isJudgeIssue, type Detection, type InboxIssue } from "./types";

// The call heatmap's state (#59): whether the overlay is on, the call logs' numbers,
// what is shown, and the issue in focus. View state only: not part of the agent,
// its undo history or its file.

export type DetectionLoad =
  | { state: "idle" }
  | { state: "loading" }
  | { state: "ready"; data: Detection }
  | { state: "none"; reason: string }
  | { state: "error"; error: string };

interface DetectionState {
  open: boolean;
  load: DetectionLoad;
  options: HeatOptions | null;
  /** The issue opened in the panel. */
  focus: string | null;
  /** Turn the overlay on (fetching the numbers again) or off. */
  setOpen(open: boolean, wanted?: Partial<HeatOptions>): Promise<void>;
  setOptions(patch: Partial<HeatOptions>): void;
  /** Show an issue: its clinic, version and signal, its node selected. A judge's issue
   * (#32) only selects its node: the heatmap has no signal for it. */
  focusIssue(issue: InboxIssue | null): void;
}

let request = 0;

export const useDetectionStore = create<DetectionState>()((set, get) => ({
  open: false,
  load: { state: "idle" },
  options: null,
  focus: null,

  async setOpen(open, wanted) {
    if (!open) {
      set({ open: false, focus: null });
      writeHash(null);
      return;
    }
    const mine = ++request;
    set({ open: true, load: get().load.state === "ready" ? get().load : { state: "loading" } });
    try {
      const body = await getDetection();
      if (mine !== request || !get().open) return;
      if (!body.available) return set({ load: { state: "none", reason: body.reason }, options: null });
      const agentClinic = useAgentStore.getState().agent?.clinic ?? null;
      const options = defaultOptions(body, agentClinic, { ...get().options, ...wanted });
      set({ load: { state: "ready", data: body }, options });
      writeHash(options);
    } catch (error) {
      if (mine === request) set({ load: { state: "error", error: error instanceof Error ? error.message : String(error) } });
    }
  },

  setOptions(patch) {
    const { load, options } = get();
    if (load.state !== "ready" || !options) return;
    const next = defaultOptions(load.data, null, { ...options, ...patch });
    // A new clinic opens on the version it runs now, unless one was asked for.
    if (patch.clinic && patch.clinic !== options.clinic && !patch.version) {
      Object.assign(next, defaultOptions(load.data, null, { clinic: next.clinic, compare: next.compare, signal: next.signal }));
    }
    set({ options: next });
    writeHash(next);
  },

  focusIssue(issue) {
    if (!issue) return set({ focus: null });
    if (isJudgeIssue(issue)) {
      set({ focus: issue.id });
    } else {
      const options = optionsFor(issue);
      set({ focus: issue.id, options });
      writeHash(options);
    }
    const agent = useAgentStore.getState().agent;
    if (agent?.nodes.some((n) => n.name === issue.node)) {
      useAgentStore.getState().select({ kind: "node", name: issue.node });
    }
  },
}));

/** Options asked for in the page's address, if it links to a heatmap view. */
export function wantedFromAddress(): Partial<HeatOptions> | null {
  return typeof window === "undefined" ? null : optionsFromHash(window.location.hash);
}

function writeHash(options: HeatOptions | null) {
  if (typeof window === "undefined" || typeof history === "undefined") return;
  const url = `${window.location.pathname}${window.location.search}${options ? hashFor(options) : ""}`;
  history.replaceState(null, "", url);
}
