import { useEffect, useMemo, useRef } from "react";

import { getAgent } from "../api";
import { displayName } from "../agent/names";
import { fixIssue, fixRefusal, useCopilotStore } from "../copilot/copilotStore";
import { selectIsDirty, useAgentStore } from "../store/agentStore";
import { callTime, ENDINGS, toolCalls, turnMarks } from "./calls";
import { selectNode, useCallsStore } from "./callsStore";
import { pathText } from "./heat";
import type { CallDetail, CallIssue, RecordedTurn } from "./types";

// The Calls tab (#32): the calls the judge read (every call the signals flagged, plus a
// random sample), then one call: its tickets, the judge's issues, the caller card the
// judge inferred, and the transcript with each issue at its quoted turn. Opening an
// issue scrolls there and selects its decisive node on the canvas; "Fix" starts a fix
// from it (#33) in the Copilot tab.

export function CallsPanel() {
  const open = useCallsStore((s) => s.open);
  return open ? <CallView /> : <CallList />;
}

function CallList() {
  const list = useCallsStore((s) => s.list);
  const loadList = useCallsStore((s) => s.loadList);
  const openCall = useCallsStore((s) => s.openCall);
  useEffect(() => void loadList(), [loadList]);
  if (list.state === "loading" || list.state === "idle") return <p className="muted">Loading the judged calls…</p>;
  if (list.state === "error") return <p className="error-text">{list.error}</p>;
  if (!list.data.length)
    return (
      <p className="muted">
        No judged calls yet. <code>make demo-seed</code> installs the demo's 22 calls with their results; <code>make judge</code>{" "}
        judges a workspace's calls.
      </p>
    );
  return (
    <div className="calls">
      {list.data.map((space) => {
        const withIssues = space.calls.filter((c) => c.issues > 0).length;
        return (
          <section key={space.id}>
            <h3>{space.id}</h3>
            <p className="muted">
              {space.calls.length} calls read by the judge: every call the signals flagged, plus a random sample. {withIssues}{" "}
              have issues.
            </p>
            <ul className="call-rows">
              {space.calls.map((row) => (
                <li key={row.call}>
                  <button className="call-row" onClick={() => void openCall(space.id, row.call)}>
                    <span className="call-row-head">
                      <strong>{callTime(row.start)}</strong>
                      <span className="muted">{ENDINGS[row.end_reason ?? ""] ?? row.end_reason}</span>
                      {row.severity && <span className={`chip severity-${row.severity}`}>{row.issues}</span>}
                    </span>
                    <span className="muted call-row-why">{row.why}</span>
                    {row.labels.length > 0 && <span className="call-row-labels">{[...new Set(row.labels)].join(" · ")}</span>}
                  </button>
                </li>
              ))}
            </ul>
          </section>
        );
      })}
    </div>
  );
}

function CallView() {
  const open = useCallsStore((s) => s.open)!;
  const detail = useCallsStore((s) => s.detail);
  const close = useCallsStore((s) => s.close);
  return (
    <div className="calls">
      <button className="link" onClick={close}>
        ← All calls
      </button>
      {detail.state === "loading" && <p className="muted">Loading {open.call}…</p>}
      {detail.state === "error" && <p className="error-text">{detail.error}</p>}
      {detail.state === "ready" && <CallBody detail={detail.data} />}
    </div>
  );
}

function CallBody({ detail }: { detail: CallDetail }) {
  const { call, judge } = detail;
  const focus = useCallsStore((s) => s.focus);
  const focused = useCallsStore((s) => s.open?.issue ?? null);
  const nodeNames = useAgentStore((s) => s.agent?.nodes.map((n) => n.name).join("\n") ?? "");
  const agentId = useAgentStore((s) => s.agentId);
  const issues = judge?.issues ?? [];
  const missing = issues.some((i) => !nodeNames.split("\n").includes(i.node));
  return (
    <>
      <h3 className="call-title">
        {call.id} <span className="muted">· {callTime(call.start)}</span>
      </h3>
      <p className="muted call-meta">
        {call.agent ?? detail.workspace}, v{call.version ?? "?"} · {ENDINGS[call.end_reason ?? ""] ?? call.end_reason} ·{" "}
        {judge?.why ?? "not judged"}
      </p>
      <p className="example-path">{pathText(detail.path)}</p>
      {missing && agentId !== detail.workspace && <OpenAgent workspace={detail.workspace} />}
      {detail.tickets.map((t) => (
        <blockquote key={t.id} className="call-ticket">
          <strong>
            Ticket {t.id}, {t.from}, {callTime(t.received)}
          </strong>
          <span>{t.text}</span>
        </blockquote>
      ))}
      {judge && (
        <>
          <h4>{issues.length ? `${issues.length} ${issues.length === 1 ? "issue" : "issues"}` : "No issues found"}</h4>
          <ol className="call-issues">
            {issues.map((issue, i) => (
              <IssueRow
                key={i}
                issue={issue}
                workspace={detail.workspace}
                call={call.id}
                open={focused === i}
                onOpen={() => focus(focused === i ? null : i)}
              />
            ))}
          </ol>
          {judge.other.length > 0 && (
            <details className="call-aside">
              <summary>Other requirements the judge mentioned ({judge.other.length}, not ranked)</summary>
              <ul>
                {judge.other.map((o, i) => (
                  <li key={i}>
                    {o.requirement}, turn {o.turn}: {o.summary}
                  </li>
                ))}
              </ul>
            </details>
          )}
          {judge.card && (
            <details className="call-aside">
              <summary>Caller card, inferred from the call ({judge.card.answers.length} recorded answers)</summary>
              <p>{judge.card.persona}</p>
              <p>{judge.card.goal}</p>
              <dl className="card-facts">
                {Object.entries(judge.card.facts).map(([k, v]) => (
                  <div key={k}>
                    <dt>{k.replace(/_/g, " ")}</dt>
                    <dd>{v}</dd>
                  </div>
                ))}
              </dl>
              <p className="muted">{judge.card.style}</p>
            </details>
          )}
        </>
      )}
      <Transcript detail={detail} />
    </>
  );
}

function IssueRow({
  issue,
  workspace,
  call,
  open,
  onOpen,
}: {
  issue: CallIssue;
  workspace: string;
  call: string;
  open: boolean;
  onOpen: () => void;
}) {
  // Re-render on what decides whether a fix can start.
  useCopilotStore((s) => `${s.workspace}|${s.step?.running}`);
  useAgentStore((s) => `${s.agentId}|${selectIsDirty(s)}`);
  const refusal = fixRefusal(workspace);
  return (
    <li className={open ? "call-issue open" : "call-issue"}>
      <button className="issue-head" onClick={onOpen} aria-expanded={open}>
        <span className={`chip severity-${issue.severity}`}>{issue.severity}</span>
        <span className="issue-title">{issue.label}</span>
        {issue.requirement && <span className="chip">{issue.requirement}</span>}
        {issue.fixed && <span className="chip">fixed in v{issue.fixed.version}</span>}
        <span className="issue-line">{issue.summary}</span>
        <span className="issue-line muted">
          Turn {issue.quote_turn}: “{issue.quote}”
        </span>
        <span className="issue-line muted">
          Decided at turn {issue.turn}, in {displayName(issue.node)}
          {issue.agreed
            ? ""
            : issue.second_turn === null
              ? " (the second run did not report it)"
              : ` (the second run said turn ${issue.second_turn})`}
        </span>
      </button>
      {open && !issue.fixed && (
        <div className="row issue-fix">
          <button disabled={refusal !== null} title={refusal ?? undefined} onClick={() => void fixIssue(call, issue.turn)}>
            Fix this issue
          </button>
          <span className="muted">{refusal ?? "Reproduce it, try 3 changes at turn " + issue.turn + ", then test: about $6."}</span>
        </div>
      )}
    </li>
  );
}

function OpenAgent({ workspace }: { workspace: string }) {
  async function openIt() {
    if (selectIsDirty(useAgentStore.getState()) && !confirm("Discard unsaved changes?")) return;
    useAgentStore.getState().open(workspace, await getAgent(workspace));
  }
  return (
    <p className="call-notice">
      These calls ran on <strong>{workspace}</strong>.{" "}
      <button className="link" onClick={() => void openIt()}>
        Open it
      </button>{" "}
      to see their nodes on the canvas.
    </p>
  );
}

function Transcript({ detail }: { detail: CallDetail }) {
  const issues = useMemo(() => detail.judge?.issues ?? [], [detail]);
  const marks = useMemo(() => turnMarks(issues), [issues]);
  const open = useCallsStore((s) => s.open);
  const list = useRef<HTMLOListElement>(null);
  useEffect(() => {
    if (open?.turn == null) return;
    list.current?.querySelector(`[data-turn="${open.turn}"]`)?.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [open?.turn, open?.nonce]);
  return (
    <>
      <h4>Transcript</h4>
      <p className="muted">The caller's words as speech-to-text heard them.</p>
      <ol className="turns call-turns" ref={list}>
        {detail.call.turns.map((turn) => (
          <TurnRow
            key={turn.turn}
            turn={turn}
            issues={issues}
            quoted={marks.get(turn.turn)?.quoted ?? []}
            decisive={marks.get(turn.turn)?.decisive ?? []}
            focused={open?.issue != null && (marks.get(turn.turn)?.quoted ?? []).includes(open.issue)}
          />
        ))}
      </ol>
    </>
  );
}

function TurnRow({
  turn,
  issues,
  quoted,
  decisive,
  focused,
}: {
  turn: RecordedTurn;
  issues: CallIssue[];
  quoted: number[];
  decisive: number[];
  focused: boolean;
}) {
  const focus = useCallsStore((s) => s.focus);
  const tools = turn.speaker === "agent" ? toolCalls(turn) : [];
  const moves = (turn.calls ?? []).filter((c) => c.kind === "edge" && c.to);
  if (turn.speaker === "agent" && !turn.text && !tools.length && !moves.length && !quoted.length) return null;
  const classes = ["turn", turn.speaker === "caller" ? "user" : "bot", quoted.length ? "marked" : "", focused ? "focused" : ""];
  return (
    <li className={classes.join(" ")} data-turn={turn.turn}>
      <span className="turn-role">
        {turn.turn}. {turn.speaker === "caller" ? "Caller" : "Agent"}
        {turn.node && (
          <>
            {" · "}
            <button className="link turn-node" onClick={() => selectNode(turn.node!)} title="Select this node on the canvas">
              {displayName(turn.node)}
            </button>
          </>
        )}
      </span>
      {turn.text && <span>{turn.text}</span>}
      {tools.map((t, i) => (
        <code key={i} className={t.failed ? "turn-tool tool-error" : "turn-tool"}>
          {t.text}
        </code>
      ))}
      {moves.map((m, i) => (
        <span key={i} className="turn-move muted">
          → {displayName(m.to!)}
        </span>
      ))}
      {quoted.map((i) => (
        <button key={`q${i}`} className="turn-mark" onClick={() => focus(i)}>
          {issues[i].label}
        </button>
      ))}
      {decisive
        .filter((i) => !quoted.includes(i))
        .map((i) => (
          <button key={`d${i}`} className="turn-mark decisive" onClick={() => focus(i)}>
            decided here: {issues[i].label}
          </button>
        ))}
    </li>
  );
}
