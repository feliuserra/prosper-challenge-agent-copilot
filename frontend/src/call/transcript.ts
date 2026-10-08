import type { BotOutputData, TranscriptData } from "@pipecat-ai/client-js";

// The live transcript of a test call, as alternating user and bot turns, built
// from two RTVI events, with the agent's transitions in between (#8):
// - `user-transcription`: speech-to-text partials, then a final for each segment.
//   Finals in a row belong to one turn; the latest partial shows after them.
// - `bot-output`: one message per sentence (`segment_id`) when it is queued for
//   speech, then progress messages as its words are spoken. A turn shows only
//   what was actually spoken, so a sentence cut off by the user stays cut off.
// - `server-message` of type "transition": an edge the bot took, sent by the
//   edge handler in backend/agent_builder/builder.py.
// - `server-message` of type "tool_call": a tool the bot called inside a node,
//   with the clinic's answer (#25), sent by the tool handler in the same file.

export interface UserTurn {
  role: "user";
  /** Final transcripts so far, joined. */
  text: string;
  /** The latest partial transcript after them, replaced by the next one. */
  partial: string;
}

export interface BotTurn {
  role: "bot";
  segments: { id: number | undefined; text: string }[];
}

/** An edge the bot took, with the arguments the LLM collected for it. */
export interface Transition {
  role: "transition";
  from: string;
  function: string;
  to: string;
  args: Record<string, unknown>;
}

/** A tool the bot called inside a node, with its arguments and what the clinic answered. */
export interface ToolCall {
  role: "tool";
  node: string;
  tool: string;
  args: Record<string, unknown>;
  result: Record<string, unknown>;
}

export type Turn = UserTurn | BotTurn | Transition | ToolCall;

const join = (...parts: string[]) => parts.filter(Boolean).join(" ");

export function turnText(turn: Turn): string {
  if (turn.role === "transition") return `${turn.function} -> ${turn.to}`;
  if (turn.role === "tool") return turn.tool;
  return turn.role === "user" ? join(turn.text, turn.partial) : join(...turn.segments.map((s) => s.text));
}

const asRecord = (value: unknown): Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value) ? (value as Record<string, unknown>) : {};

/** The transition in a server message, or null for any other message. */
export function parseTransition(data: unknown): Transition | null {
  if (typeof data !== "object" || data === null) return null;
  const { type, from, function: fn, to, args } = data as Record<string, unknown>;
  if (type !== "transition" || typeof from !== "string" || typeof fn !== "string" || typeof to !== "string") return null;
  return { role: "transition", from, function: fn, to, args: asRecord(args) };
}

/** The tool call in a server message, or null for any other message. */
export function parseToolCall(data: unknown): ToolCall | null {
  if (typeof data !== "object" || data === null) return null;
  const { type, node, tool, args, result } = data as Record<string, unknown>;
  if (type !== "tool_call" || typeof node !== "string" || typeof tool !== "string") return null;
  return { role: "tool", node, tool, args: asRecord(args), result: asRecord(result) };
}

export function addUserTranscript(turns: Turn[], data: Pick<TranscriptData, "text" | "final">): Turn[] {
  const last = turns.at(-1);
  const current: UserTurn = last?.role === "user" ? last : { role: "user", text: "", partial: "" };
  const next: UserTurn = data.final
    ? { role: "user", text: join(current.text, data.text), partial: "" }
    : { ...current, partial: data.text };
  return current === last ? [...turns.slice(0, -1), next] : [...turns, next];
}

export function addBotOutput(turns: Turn[], data: BotOutputData): Turn[] {
  // Word and token messages repeat what the sentence messages say; the 2.0
  // server does not send them, but older protocol versions did.
  if (data.aggregated_by === "word" || data.aggregated_by === "token") return turns;
  // Spoken text when the server tracks it ("new" means none of it yet), else
  // the whole text (output that is not spoken).
  const text = data.spoken_progress ? data.spoken_progress.accumulated_text : data.text;

  // A progress message updates its sentence, wherever it is: the user may
  // have started a new turn by talking over it.
  if (data.segment_id !== undefined) {
    for (let i = turns.length - 1; i >= 0; i--) {
      const turn = turns[i];
      if (turn.role !== "bot") continue;
      const index = turn.segments.findIndex((s) => s.id === data.segment_id);
      if (index === -1) continue;
      const segments = turn.segments.map((s, j) => (j === index ? { id: data.segment_id, text } : s));
      return turns.map((t, j) => (j === i ? { role: "bot", segments } : t));
    }
  }
  const segment = { id: data.segment_id, text };
  const last = turns.at(-1);
  return last?.role === "bot"
    ? [...turns.slice(0, -1), { role: "bot", segments: [...last.segments, segment] }]
    : [...turns, { role: "bot", segments: [segment] }];
}
