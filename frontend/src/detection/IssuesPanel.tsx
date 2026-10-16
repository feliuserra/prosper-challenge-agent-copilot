import { displayName } from "../agent/names";
import { useAgentStore } from "../store/agentStore";
import { useCallsStore } from "./callsStore";
import { useDetectionStore } from "./detectionStore";
import { HeatControls } from "./HeatControls";
import { issuesAt, pathText, previousVersion, SIGNAL_ORDER, signalLabel, SIGNIFICANT, type HeatOptions } from "./heat";
import { isJudgeIssue, type CallSummary, type Detection, type Issue, type JudgeGroup, type JudgeIssue, type SignalKey } from "./types";

// The ranked issues from the call logs (#58) beside the canvas (#59), with the model
// judge's (#32) in the same list. Clicking an issue shows its clinic, version and signal
// on the canvas, selects its node and lists its example calls; a judge's issue lists its
// calls with their quotes, and each opens in the Calls tab at the quoted turn. Selecting
// a node lists its numbers and its issues.

const pct = (rate: number) => `${(rate * 100).toFixed(rate < 0.1 ? 1 : 0)}%`;
const count = (n: number) => Math.round(n).toLocaleString("en-US");
const ENDED = { completed: "completed", hang_up: "hung up", transfer: "transferred", error: "error" } as const;

function weekName(week: string) {
  return new Date(`${week}T00:00:00`).toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

function callTime(at: string) {
  const when = new Date(at);
  return `${when.toLocaleDateString("en-US", { month: "short", day: "numeric" })}, ${at.slice(11, 16)}`;
}

export function IssuesPanel() {
  const load = useDetectionStore((s) => s.load);
  const options = useDetectionStore((s) => s.options);
  const focus = useDetectionStore((s) => s.focus);
  const setOpen = useDetectionStore((s) => s.setOpen);
  const selection = useAgentStore((s) => s.selection);
  const nodeNames = useAgentStore((s) => s.agent?.nodes.map((n) => n.name).join("\n") ?? "");
  const judged = load.state === "ready" ? Object.values(load.data.judged ?? {}).reduce((a, b) => a + b, 0) : 0;

  return (
    <aside className="issues-panel nokey" aria-label="Issues from the call logs">
      <header className="issues-header">
        <h2>Issues in calls</h2>
        <button className="issues-close" onClick={() => void setOpen(false)} title="Turn the call heatmap off">
          ×
        </button>
      </header>
      {load.state === "loading" && <p className="muted">Reading the call logs… (a few seconds the first time)</p>}
      {load.state === "none" && <p className="muted">{load.reason}</p>}
      {load.state === "error" && <p className="error-text">{load.error}</p>}
      {load.state === "ready" && options && (
        <>
          <HeatControls />
          <p className="muted issues-summary">
            Week of {weekName(load.data.week)}: {load.data.issues.length} issues in {count(load.data.calls)} calls from{" "}
            {load.data.clinics.length} clinics, found with no model calls
            {judged > 0 && `, and by a model judge on ${judged} calls (flagged ones plus a sample)`}. Most urgent first: severity
            times extra calls a week.
          </p>
          <ol className="issues-list">
            {load.data.issues.map((issue) =>
              isJudgeIssue(issue) ? (
                <JudgeItem
                  key={issue.id}
                  issue={issue}
                  open={issue.id === focus}
                  inAgent={nodeNames.split("\n").includes(issue.node)}
                />
              ) : (
                <IssueItem
                  key={issue.id}
                  issue={issue}
                  data={load.data}
                  open={issue.id === focus}
                  inAgent={nodeNames.split("\n").includes(issue.node)}
                />
              ),
            )}
          </ol>
          {selection?.kind === "node" && <NodeNumbersView data={load.data} options={options} node={selection.name} />}
        </>
      )}
    </aside>
  );
}

function IssueItem({ issue, data, open, inAgent }: { issue: Issue; data: Detection; open: boolean; inAgent: boolean }) {
  const focusIssue = useDetectionStore((s) => s.focusIssue);
  const lead = issue.evidence.find((e) => e.signal === issue.signal && e.baseline === "version") ?? issue.evidence[0];
  return (
    <li className={open ? "issue open" : "issue"}>
      <button className="issue-head" onClick={() => focusIssue(open ? null : issue)} aria-expanded={open}>
        <span className="issue-title">
          {issue.clinic} · {displayName(issue.node)}
        </span>
        <span className={`chip shape-${issue.shape}`}>{issue.shape}</span>
        <span className={`chip severity-${issue.severity}`}>{issue.severity}</span>
        <span className="issue-line">
          {lead.label[0].toUpperCase() + lead.label.slice(1)} {pct(lead.rate)} in v{issue.version}, {pct(lead.base_rate)}{" "}
          {lead.baseline === "version" ? `in v${lead.against}` : "at other clinics"}
        </span>
        <span className="issue-line muted">
          About {count(issue.extra_per_week)} more calls a week · since v{issue.since_version} ({weekName(issue.since_week)}) ·{" "}
          {issue.direction}
        </span>
      </button>
      {open && (
        <div className="issue-body">
          {!inAgent && <p className="muted">The open agent has no node called {issue.node}.</p>}
          <ul className="evidence">
            {issue.evidence.map((e) => (
              <li key={`${e.signal}-${e.baseline}`}>
                {e.label}: {pct(e.rate)} of {count(e.n)} against {pct(e.base_rate)}{" "}
                {e.baseline === "version" ? `in v${e.against}` : "at other clinics"} (Holm p {e.p.toPrecision(2)})
              </li>
            ))}
          </ul>
          <Trend issue={issue} />
          {issue.judge && <JudgeCalls group={issue.judge} />}
          <h3>Example calls</h3>
          <ul className="examples">
            {issue.examples.map((id) => (
              <ExampleCall key={id} call={data.example_calls[id]} id={id} node={issue.node} />
            ))}
          </ul>
        </div>
      )}
    </li>
  );
}

/** An issue only the model judge found (#32): judged calls, not a signal's rate. */
function JudgeItem({ issue, open, inAgent }: { issue: JudgeIssue; open: boolean; inAgent: boolean }) {
  const focusIssue = useDetectionStore((s) => s.focusIssue);
  return (
    <li className={open ? "issue open" : "issue"}>
      <button className="issue-head" onClick={() => focusIssue(open ? null : issue)} aria-expanded={open}>
        <span className="issue-title">
          {issue.clinic} · {displayName(issue.node)}
        </span>
        <span className={`chip shape-${issue.shape}`}>{issue.shape}</span>
        <span className={`chip severity-${issue.severity}`}>{issue.severity}</span>
        <span className="chip judge">judge</span>
        <span className="issue-line">
          {issue.label[0].toUpperCase() + issue.label.slice(1)}: {issue.affected} of {issue.judged} judged calls
        </span>
        <span className="issue-line muted">
          About {count(issue.extra_per_week)} calls a week at {count(issue.volume)} a week · v{issue.version}
        </span>
      </button>
      {open && (
        <div className="issue-body">
          {!inAgent && <p className="muted">The open agent has no node called {issue.node}.</p>}
          <JudgeCalls group={issue.judge} />
        </div>
      )}
    </li>
  );
}

/** A judge group's calls with their quotes; each opens in the Calls tab at the quote. */
function JudgeCalls({ group }: { group: JudgeGroup }) {
  const openCall = useCallsStore((s) => s.openCall);
  return (
    <>
      <h3>
        Judged calls ({group.affected} of {group.judged})
      </h3>
      <ul className="examples judged">
        {group.calls.map((c) => (
          <li key={`${c.call}-${c.index}`}>
            <button className="link judged-call" onClick={() => void openCall(group.workspace, c.call, c.index)}>
              <strong>{c.call}</strong> <span className="muted">turn {c.quote_turn}</span>
            </button>
            <div>
              {c.label}: “{c.quote}”
            </div>
            <div className="muted">
              {c.summary}
              {!c.agreed && " The decisive turn is uncertain (the two runs differ)."}
            </div>
          </li>
        ))}
      </ul>
    </>
  );
}

/** The signal's weekly rate at the node, as small bars. */
function Trend({ issue }: { issue: Issue }) {
  const most = Math.max(...issue.trend.map((t) => t.rate), issue.base_rate, 0.0001);
  return (
    <div className="trend" aria-label="Weekly rate">
      {issue.trend.map((t) => (
        <span
          key={t.week}
          className="trend-week"
          title={`Week of ${weekName(t.week)} (v${t.versions.join(", v")}): ${pct(t.rate)} of ${count(t.n)}`}
        >
          <span className="trend-bar" style={{ height: `${Math.max(2, (t.rate / most) * 36)}px` }} />
          <span className="trend-label">{weekName(t.week).split(" ")[1]}</span>
        </span>
      ))}
    </div>
  );
}

function ExampleCall({ call, id, node }: { call: CallSummary | undefined; id: string; node: string }) {
  if (!call) return <li className="muted">{id}</li>;
  const turns = call.path.filter(([n]) => n === node).reduce((sum, [, t]) => sum + t, 0);
  return (
    <li>
      <div>
        <strong>{call.id}</strong> <span className="muted">{callTime(call.start)}, {ENDED[call.ended]}</span>
      </div>
      <div className="example-path" title={`${turns} agent turns in ${displayName(node)}`}>
        {pathText(call.path)}
      </div>
    </li>
  );
}

/** Every signal at the selected node, against the chosen baseline, and its issues. */
function NodeNumbersView({ data, options, node }: { data: Detection; options: HeatOptions; node: string }) {
  const numbers = data.nodes[options.clinic]?.[options.version]?.[node];
  const where = `${options.clinic} v${options.version}`;
  const against = options.compare === "version" ? `v${previousVersion(data, options.clinic, options.version) ?? "?"}` : "other clinics";
  const issues = issuesAt(data, options, node);
  return (
    <section className="node-numbers">
      <h3>
        {displayName(node)} in {where}
      </h3>
      {!numbers ? (
        <p className="muted">No calls went through a node called {node} there.</p>
      ) : (
        <>
          <p className="muted">
            {count(numbers.entered)} calls entered. Against {against}; marked when the detector flagged it.
          </p>
          <table>
            <tbody>
              {SIGNAL_ORDER.filter((s): s is SignalKey => s !== "issues" && !!numbers.signals[s as SignalKey]).map((signal) => {
                const s = numbers.signals[signal]!;
                const base = s[options.compare];
                const up = base && s.rate > base.rate && base.p < SIGNIFICANT;
                return (
                  <tr key={signal} className={base?.flagged ? "flagged" : up ? "up" : undefined}>
                    <td>{signalLabel(data, signal)}</td>
                    <td>{pct(s.rate)}</td>
                    <td className="muted">{base ? pct(base.rate) : "no baseline"}</td>
                    <td>{base?.flagged ? "flagged" : ""}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {issues.length > 0 && (
            <p>
              Issues here: {issues.map((i) => `${i.shape} (${i.label})`).join(", ")}.
            </p>
          )}
        </>
      )}
    </section>
  );
}
