// What GET /composer/detection returns (backend/detect/api.py, #58): the ranked
// issues and every node's numbers per clinic and version, from the call logs.

export type SignalKey =
  | "reentry"
  | "stall"
  | "hang_up"
  | "transfer"
  | "error"
  | "tool_error"
  | "duplicate"
  | "callback"
  | "quick_change";

export type Compare = "version" | "fleet";

/** A baseline's numbers, with a raw one-sided p-value and whether the detector flagged it. */
export interface BaselineNumbers {
  k: number;
  n: number;
  rate: number;
  p: number;
  flagged: boolean;
}

/** One signal at one node: `k` events out of `n` calls. */
export interface SignalNumbers {
  k: number;
  n: number;
  rate: number;
  version?: BaselineNumbers;
  fleet?: BaselineNumbers;
}

export interface NodeNumbers {
  /** Calls that entered the node. */
  entered: number;
  /** Transitions out of the node, by edge function. */
  exits: Record<string, number>;
  signals: Partial<Record<SignalKey, SignalNumbers>>;
}

export interface Evidence {
  signal: SignalKey;
  label: string;
  baseline: Compare;
  against: number | string;
  rate: number;
  base_rate: number;
  k: number;
  n: number;
  p: number;
  extra_per_week: number;
}

export interface Issue {
  id: string;
  clinic: string;
  node: string;
  shape: string;
  severity: "high" | "medium" | "low";
  version: number;
  signal: SignalKey;
  label: string;
  rate: number;
  base_rate: number;
  baseline: Compare;
  extra_per_week: number;
  score: number;
  since_week: string;
  since_version: number;
  trend: { week: string; versions: number[]; k: number; n: number; rate: number }[];
  direction: "new" | "rising" | "falling" | "steady";
  evidence: Evidence[];
  examples: string[];
}

/** A call summary (backend/detect/summary.py). */
export interface CallSummary {
  id: string;
  clinic: string;
  version: number;
  start: string;
  end: string;
  caller: string;
  /** One [node, turns, via] per visit; `via` is absent for the first node. */
  path: [string, number, string?][];
  tools: [string, string, boolean][];
  ended: "completed" | "hang_up" | "transfer" | "error";
}

export interface Detection {
  available: true;
  /** The week the issues are for (its Monday). */
  week: string;
  end: string;
  calls: number;
  clinics: { id: string; versions: { version: number; from: string; to: string; calls: number }[] }[];
  issues: Issue[];
  example_calls: Record<string, CallSummary>;
  /** clinic -> version -> node -> numbers. */
  nodes: Record<string, Record<string, Record<string, NodeNumbers>>>;
  settings: {
    window_weeks: number;
    alpha: number;
    allowance: Record<Compare, number>;
    min_relative: Record<Compare, number>;
    min_absolute: number;
    min_events: number;
    stall_turns: number;
  };
  signals: Record<SignalKey, { label: string; shape: string }>;
}

export type DetectionResponse = Detection | { available: false; reason: string };
