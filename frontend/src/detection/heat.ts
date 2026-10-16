import { displayName } from "../agent/names";
import type { Agent } from "../agent/schema";
import type { Stage } from "../agent/stages";
import { edgeId } from "../canvas/derive";
import type { CanvasView } from "../canvas/view";
import { isJudgeIssue, type Compare, type Detection, type Issue, type SignalKey } from "./types";

// The call heatmap (#59): the canvas tinted by the call logs. Derived only, never
// written to the agent (ADR 0001). The detector (#58) decides what is wrong; this
// shows where. Each node is tinted by how far a signal's rate is above its
// baseline, cards show the rate and the baseline, edge width is traffic, and a
// collapsed stage rolls its nodes up, weighted by traffic. Nodes are matched by name.

export type HeatSignal = SignalKey | "issues";

export interface HeatOptions {
  clinic: string;
  /** A version number, as the API's keys are strings. */
  version: string;
  compare: Compare;
  signal: HeatSignal;
}

/** This many percentage points above the baseline is the hottest tint. */
export const TINT_FULL = 0.05;
/** A rise is tinted only when its raw one-sided p-value is below this; otherwise it may be noise. */
export const SIGNIFICANT = 0.05;

export const SIGNAL_ORDER: HeatSignal[] = [
  "issues",
  "reentry",
  "stall",
  "hang_up",
  "transfer",
  "tool_error",
  "error",
  "callback",
  "quick_change",
  "duplicate",
];

export interface NodeHeat {
  /** 0 (no tint) to 1 (the hottest). */
  tint: number;
  /** The signal's rate here, or null in the issues view or without numbers. */
  rate: number | null;
  base: number | null;
  /** Calls the rate is a share of. */
  n: number;
  /** Calls that entered the node (for a stage, its busiest node: a call through several counts once). */
  entered: number;
  /** The detector flagged this signal against this baseline while the version ran. */
  flagged: boolean;
  /** Open issues at the node (or in the stage), most urgent first. */
  issues: Issue[];
  /** Why there is no tint, when there is a reason to say. */
  note: string | null;
  /** What the card says in place of its task (set by canvasHeat). */
  lines?: [string, string];
}

export interface EdgeTraffic {
  calls: number;
  /** Stroke width in pixels. */
  width: number;
}

export interface CanvasHeat {
  /** By node name and by collapsed stage card id. */
  nodes: Map<string, NodeHeat>;
  /** By edge id. */
  edges: Map<string, EdgeTraffic>;
  signal: HeatSignal;
  compare: Compare;
}

export const EDGE_MIN = 1.5;
export const EDGE_MAX = 8;

export function signalLabel(detection: Detection, signal: HeatSignal): string {
  return signal === "issues" ? "issues" : (detection.signals[signal]?.label ?? signal);
}

export function versionsOf(detection: Detection, clinic: string): number[] {
  return (detection.clinics.find((c) => c.id === clinic)?.versions ?? []).map((v) => v.version);
}

/** The version before `version` in a clinic's logs, if any. */
export function previousVersion(detection: Detection, clinic: string, version: string): number | null {
  const earlier = versionsOf(detection, clinic).filter((v) => v < Number(version));
  return earlier.length ? Math.max(...earlier) : null;
}

/** The version a clinic runs now (its latest in the logs). */
export function currentVersion(detection: Detection, clinic: string): number | null {
  const versions = versionsOf(detection, clinic);
  return versions.length ? Math.max(...versions) : null;
}

/**
 * Where the overlay opens: the agent's clinic (or the clinic of the most urgent
 * issue), the version it runs now, against the previous version when there is one,
 * showing the issues. Options already chosen are kept where the data has them.
 */
export function defaultOptions(detection: Detection, agentClinic?: string | null, chosen?: Partial<HeatOptions>): HeatOptions {
  const ids = detection.clinics.map((c) => c.id);
  const clinic = [chosen?.clinic, agentClinic, detection.issues[0]?.clinic, ids[0]].find(
    (c): c is string => !!c && ids.includes(c),
  )!;
  const versions = versionsOf(detection, clinic).map(String);
  const version = chosen?.version && versions.includes(chosen.version) ? chosen.version : String(currentVersion(detection, clinic));
  const hasPrevious = previousVersion(detection, clinic, version) !== null;
  const compare = chosen?.compare === "fleet" || (chosen?.compare === "version" && hasPrevious) ? chosen.compare : hasPrevious ? "version" : "fleet";
  const signal = chosen?.signal && SIGNAL_ORDER.includes(chosen.signal) ? chosen.signal : "issues";
  return { clinic, version, compare, signal };
}

/** The options that show an issue: its clinic and version, its signal, against its previous version when that flagged it. */
export function optionsFor(issue: Issue): HeatOptions {
  const againstVersion = issue.evidence.some((e) => e.signal === issue.signal && e.baseline === "version");
  return {
    clinic: issue.clinic,
    version: String(issue.version),
    compare: againstVersion ? "version" : "fleet",
    signal: issue.signal,
  };
}

/** #58's issues at a node for a clinic and version, most urgent first (the API ranks them).
 * The judge's own issues (#32) are left out: their versions are the workspace's, not the logs'. */
export function issuesAt(detection: Detection, options: HeatOptions, node: string): Issue[] {
  return detection.issues.filter(
    (i): i is Issue =>
      !isJudgeIssue(i) && i.clinic === options.clinic && String(i.version) === options.version && i.node === node,
  );
}

function tintFor(excess: number, significant: boolean): number {
  return excess > 0 && significant ? Math.min(1, excess / TINT_FULL) : 0;
}

/** Every agent node's heat for a clinic and version. */
export function nodeHeats(detection: Detection, options: HeatOptions, agent: Agent): Map<string, NodeHeat> {
  const numbers = detection.nodes[options.clinic]?.[options.version] ?? {};
  const where = `${options.clinic} v${options.version}`;
  const heats = new Map<string, NodeHeat>();
  const extra = (issues: Issue[]) => issues.reduce((sum, i) => sum + i.extra_per_week, 0);
  const worst = Math.max(0, ...agent.nodes.map((n) => extra(issuesAt(detection, options, n.name))));
  for (const node of agent.nodes) {
    const here = numbers[node.name];
    const issues = issuesAt(detection, options, node.name);
    const heat: NodeHeat = { tint: 0, rate: null, base: null, n: 0, entered: here?.entered ?? 0, flagged: false, issues, note: null };
    heats.set(node.name, heat);
    if (!here) {
      heat.note = `No calls went through a node called ${node.name} in ${where}: it is not in that version, or has another name there.`;
      continue;
    }
    if (options.signal === "issues") {
      heat.tint = worst > 0 ? extra(issues) / worst : 0;
      heat.flagged = issues.length > 0;
      continue;
    }
    const signal = here.signals[options.signal];
    if (!signal) {
      heat.note = `No ${signalLabel(detection, options.signal)} are measured at this node.`;
      continue;
    }
    heat.rate = signal.rate;
    heat.n = signal.n;
    const base = signal[options.compare];
    if (!base) {
      heat.note =
        options.compare === "version"
          ? `No earlier version of ${options.clinic} to compare with.`
          : `No other clinic has a node called ${node.name}, so there is no fleet baseline.`;
      continue;
    }
    heat.base = base.rate;
    heat.flagged = base.flagged;
    heat.tint = tintFor(signal.rate - base.rate, base.p < SIGNIFICANT);
  }
  return heats;
}

/**
 * A collapsed stage's heat: its nodes rolled up, weighted by traffic. The rate is
 * all their events over all their calls, the baseline what the baselines would give
 * on the same traffic. Tinted when the rolled-up rate is above it and a node in the
 * stage is tinted.
 */
export function stageHeat(stage: Stage, heats: Map<string, NodeHeat>, signal: HeatSignal): NodeHeat {
  const members = stage.nodes.map((name) => heats.get(name)).filter((h): h is NodeHeat => !!h);
  const issues = members.flatMap((h) => h.issues).sort((a, b) => b.score - a.score);
  const entered = Math.max(0, ...members.map((h) => h.entered));
  const flagged = members.some((h) => h.flagged);
  const anyTint = members.some((h) => h.tint > 0);
  if (signal === "issues") {
    return { tint: Math.max(0, ...members.map((h) => h.tint)), rate: null, base: null, n: 0, entered, flagged, issues, note: null };
  }
  const measured = members.filter((h) => h.rate !== null && h.n > 0);
  const compared = measured.filter((h) => h.base !== null);
  if (!measured.length) {
    const note = members.find((h) => h.note)?.note ?? null;
    return { tint: 0, rate: null, base: null, n: 0, entered, flagged, issues, note };
  }
  const n = measured.reduce((sum, h) => sum + h.n, 0);
  const rate = measured.reduce((sum, h) => sum + h.rate! * h.n, 0) / n;
  if (!compared.length) {
    return { tint: 0, rate, base: null, n, entered, flagged, issues, note: measured.find((h) => h.note)?.note ?? null };
  }
  const weight = compared.reduce((sum, h) => sum + h.n, 0);
  const comparedRate = compared.reduce((sum, h) => sum + h.rate! * h.n, 0) / weight;
  const base = compared.reduce((sum, h) => sum + h.base! * h.n, 0) / weight;
  return { tint: tintFor(comparedRate - base, anyTint), rate, base, n, entered, flagged, issues, note: null };
}

/** Each drawn edge's traffic in a clinic and version: calls that took it, and a width. */
export function edgeTraffic(detection: Detection, options: HeatOptions, agent: Agent): Map<string, EdgeTraffic> {
  const numbers = detection.nodes[options.clinic]?.[options.version] ?? {};
  const counts = agent.nodes.flatMap((node) =>
    (node.edges ?? []).map((edge) => [edgeId(node.name, edge.function), numbers[node.name]?.exits[edge.function] ?? 0] as const),
  );
  const most = Math.max(0, ...counts.map(([, calls]) => calls));
  return new Map(
    counts.map(([id, calls]) => [id, { calls, width: most ? EDGE_MIN + ((EDGE_MAX - EDGE_MIN) * calls) / most : EDGE_MIN }]),
  );
}

/** Everything the canvas needs: heat by node and stage card, traffic by edge. */
export function canvasHeat(detection: Detection, options: HeatOptions, agent: Agent, view: CanvasView): CanvasHeat {
  const nodes = nodeHeats(detection, options, agent);
  for (const heat of nodes.values()) heat.lines = heatLines(detection, heat, options);
  for (const card of view.cards.values()) {
    const heat = stageHeat(card.stage, nodes, options.signal);
    heat.lines = heatLines(detection, heat, options, card.stage.nodes.length);
    nodes.set(card.id, heat);
  }
  return { nodes, edges: edgeTraffic(detection, options, agent), signal: options.signal, compare: options.compare };
}

/** The tint as a colour: from white to a deep orange, light enough for dark text on a card. */
export function heatColor(tint: number): string {
  const t = Math.max(0, Math.min(1, tint));
  // White (255, 255, 255) to rgb(244, 140, 70).
  const mix = (to: number) => Math.round(255 + (to - 255) * t);
  return `rgb(${mix(244)} ${mix(140)} ${mix(70)})`;
}

const percent = (rate: number) => `${(rate * 100).toFixed(rate < 0.1 ? 1 : 0)}%`;

/** The two lines a card shows in place of its task; `steps` for a collapsed stage's card. */
export function heatLines(detection: Detection, heat: NodeHeat, options: HeatOptions, steps?: number): [string, string] {
  if (heat.entered === 0) return ["No calls here", heat.note ?? ""];
  if (options.signal === "issues") {
    const calls = `${heat.entered.toLocaleString("en-US")} calls entered`;
    // Issues are found for the version running now: an older one is not "clean".
    const now = currentVersion(detection, options.clinic);
    if (now !== null && Number(options.version) !== now) return [`Issues are for v${now}, running now`, calls];
    if (!heat.issues.length) return ["No issues", calls];
    const names = [...new Set(heat.issues.map((i) => i.shape))].join(", ");
    const extra = heat.issues.reduce((sum, i) => sum + i.extra_per_week, 0);
    return [
      `${heat.issues.length} ${heat.issues.length === 1 ? "issue" : "issues"}: ${names}`,
      `About ${Math.round(extra).toLocaleString("en-US")} more calls a week`,
    ];
  }
  const label = signalLabel(detection, options.signal);
  if (heat.rate === null) return [`No ${label}`, heat.note ?? ""];
  const of = steps ? `across ${steps} ${steps === 1 ? "step" : "steps"}` : `of ${heat.n.toLocaleString("en-US")}`;
  const first = `${label[0].toUpperCase()}${label.slice(1)}: ${percent(heat.rate)} ${of}`;
  if (heat.base === null) return [first, heat.note ?? "No baseline"];
  const against =
    options.compare === "version"
      ? `v${previousVersion(detection, options.clinic, options.version)}`
      : "other clinics";
  return [first, `${percent(heat.base)} in ${against}${heat.flagged ? " · flagged" : ""}`];
}

/** A call's path in words: "Greeting › Ask name › Confirm name ×3 › …". */
export function pathText(path: [string, number, string?][]): string {
  const steps: { name: string; times: number }[] = [];
  for (const [node] of path) {
    const last = steps.at(-1);
    if (last && last.name === node) last.times += 1;
    else steps.push({ name: node, times: 1 });
  }
  return steps.map((s) => displayName(s.name) + (s.times > 1 ? ` ×${s.times}` : "")).join(" › ");
}

/** Parse `#calls=clinic/version/compare/signal`: a link to a heatmap view. */
export function optionsFromHash(hash: string): Partial<HeatOptions> | null {
  const match = /^#calls(?:=(.*))?$/.exec(hash);
  if (!match) return null;
  const [clinic, version, compare, signal] = (match[1] ?? "").split("/").map(decodeURIComponent);
  return {
    ...(clinic ? { clinic } : {}),
    ...(version ? { version } : {}),
    ...(compare === "version" || compare === "fleet" ? { compare } : {}),
    ...(signal ? { signal: signal as HeatSignal } : {}),
  };
}

export function hashFor(options: HeatOptions): string {
  return `#calls=${[options.clinic, options.version, options.compare, options.signal].map(encodeURIComponent).join("/")}`;
}
