import type { CallDetail, CallIssue, RecordedTurn } from "./types";

// Pure helpers for the Calls tab (#32): which turns carry an issue, and how a call and
// its tool calls read.

export interface TurnMarks {
  /** Issues whose quote is in this turn. */
  quoted: number[];
  /** Issues whose decisive turn this is. */
  decisive: number[];
}

/** Turn number -> the issues (by index) quoted in it or decided at it. */
export function turnMarks(issues: CallIssue[]): Map<number, TurnMarks> {
  const marks = new Map<number, TurnMarks>();
  const at = (turn: number) => {
    if (!marks.has(turn)) marks.set(turn, { quoted: [], decisive: [] });
    return marks.get(turn)!;
  };
  issues.forEach((issue, i) => {
    at(issue.quote_turn).quoted.push(i);
    at(issue.turn).decisive.push(i);
  });
  return marks;
}

export const ENDINGS: Record<string, string> = {
  end_node: "ended by the agent",
  caller_hung_up: "the caller hung up",
  transfer: "transferred",
  max_turns: "cut off",
  agent_loop: "dropped",
};

/** "Mon, Oct 19, 08:04". */
export function callTime(at: string | null): string {
  if (!at) return "";
  const when = new Date(at);
  return `${when.toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" })}, ${at.slice(11, 16)}`;
}

/** The catalog tool calls of an agent turn, each as `name(args)` and whether it failed. */
export function toolCalls(turn: RecordedTurn): { text: string; failed: boolean }[] {
  return (turn.calls ?? [])
    .filter((c) => c.kind === "tool")
    .map((c) => ({
      text: `${c.name}(${Object.entries(c.args ?? {})
        .map(([k, v]) => `${k}: ${typeof v === "string" ? v : JSON.stringify(v)}`)
        .join(", ")})`,
      failed: !!c.result && typeof c.result === "object" && "error" in (c.result as object),
    }));
}

/** Where the issue's quote is: the turn to scroll to when it is opened. */
export const quotedTurn = (detail: CallDetail, index: number): number | null =>
  detail.judge?.issues[index]?.quote_turn ?? null;
