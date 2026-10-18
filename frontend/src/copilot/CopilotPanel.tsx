import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import { EXAMPLE_AGENT_ID } from "../agent/templates";
import { ClinicSections } from "../clinic/ClinicView";
import { readClinic } from "../clinic/clinic";
import { useAgentStore } from "../store/agentStore";
import type { FixReport, Proposal, Requirement, Spec, SpecTest, TestRow, TestRun, TestSummary } from "./api";
import {
  accept,
  acceptRefusal,
  approve,
  build,
  createFromGuidelines,
  isPending,
  reject,
  removeTest,
  runTests,
  setGuidelines,
  showProposal,
  stop,
  useCopilotStore,
  type Step,
  type StepKind,
} from "./copilotStore";
import { nodeDiff } from "./diff";

// The Copilot tab (#31): the workspace of the open agent, top to bottom in the order of
// the work: paste the guidelines, review what the spec step wrote (requirements, client
// questions, the clinic configuration, tests), approve tests, build, decide on the
// proposal, run the tests. Every button calls the endpoint directly. A fix from an issue
// (#33) starts in the Calls tab; its progress and its proposal show here.

export function CopilotPanel() {
  const workspace = useCopilotStore((s) => s.workspace);
  const loading = useCopilotStore((s) => s.loading);
  const loadError = useCopilotStore((s) => s.loadError);
  const spec = useCopilotStore((s) => s.spec);
  const proposal = useCopilotStore((s) => s.proposal);
  const run = useCopilotStore((s) => s.run);
  const fix = useCopilotStore((s) => s.fix);
  const fixing = useCopilotStore((s) => s.step?.kind === "fix");

  if (!workspace) return <p className="muted">No agent open.</p>;
  // Accepting writes the agent's file: into the template, every later build would start
  // from that clinic's agent. The backend refuses it too.
  if (workspace === EXAMPLE_AGENT_ID) {
    return (
      <div className="copilot">
        <p>
          <strong>This is the template</strong> the Copilot builds every agent from, so it does not work in it.
        </p>
        <p className="muted">
          Create an agent with "New from example" (or "New blank"), save it, and use the Copilot there.
        </p>
      </div>
    );
  }
  if (loading) return <p className="muted">Loading the workspace…</p>;
  if (loadError) return <p className="field-error">Could not load the workspace: {loadError}</p>;
  const hasSpec = spec !== null && spec.requirements.length > 0;
  return (
    <div className="copilot">
      <p className="muted">
        Workspace <code>{workspace}</code>. You review the requirements and tests; the Copilot writes the agent.
      </p>
      <Guidelines />
      {hasSpec && (
        <>
          <Requirements spec={spec} proposal={proposal} />
          <Questions spec={spec} proposal={proposal} />
          <Configuration configuration={spec.configuration} />
          <Tests spec={spec} run={run} />
          <Build spec={spec} />
          {(fixing || fix) && <Fix report={fix} />}
          {proposal && <ProposalCard proposal={proposal} />}
          <RunTests spec={spec} run={run} />
        </>
      )}
    </div>
  );
}

function Card(props: {
  title: ReactNode;
  aside?: ReactNode;
  children: ReactNode;
  /** Whether a collapsible card starts open; afterwards the person opens and closes it. */
  open?: boolean;
  collapsible?: boolean;
}) {
  const [open, setOpen] = useState(props.open ?? false);
  const header = (
    <div className="copilot-card-header">
      <h3>{props.title}</h3>
      {props.aside}
    </div>
  );
  if (props.collapsible) {
    return (
      <details className="copilot-card" open={open} onToggle={(e) => setOpen(e.currentTarget.open)}>
        <summary>{header}</summary>
        {props.children}
      </details>
    );
  }
  return (
    <section className="copilot-card">
      {header}
      {props.children}
    </section>
  );
}

const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;

// ---- guidelines ---------------------------------------------------------------------------------
function Guidelines() {
  const text = useCopilotStore((s) => s.guidelines);
  const saved = useCopilotStore((s) => s.savedGuidelines);
  const spec = useCopilotStore((s) => s.spec);
  const busy = useCopilotStore((s) => s.step?.running === true);
  const hasSpec = (spec?.requirements.length ?? 0) > 0;
  return (
    <Card title="Client guidelines" collapsible open={!hasSpec}>
      <textarea
        className="copilot-guidelines"
        value={text}
        onChange={(e) => setGuidelines(e.target.value)}
        placeholder="Paste the clinic's guidelines document here."
        rows={10}
        aria-label="Client guidelines"
      />
      <div className="row">
        <button className="primary" disabled={busy || !text.trim()} onClick={() => void createFromGuidelines()}>
          {hasSpec ? "Create again from guidelines" : "Create from guidelines"}
        </button>
        {text !== saved && <span className="dirty">● Not saved yet</span>}
      </div>
      <div className="hint">
        Writes the requirements, client questions, clinic configuration and draft tests. Model calls, about $0.35.
      </div>
      <StepLog kind="spec" />
    </Card>
  );
}

// ---- the step's progress ------------------------------------------------------------------------
const STEP_TITLES: Record<StepKind, string> = {
  spec: "Writing the spec",
  build: "Building",
  tests: "Running the tests",
  fix: "Fixing the issue",
};

/** The running or last step's log, shown in the card of its kind. */
function StepLog({ kind }: { kind: StepKind }) {
  const step = useCopilotStore((s) => (s.step?.kind === kind ? s.step : null));
  if (!step) return null;
  return <StepView step={step} />;
}

function StepView({ step }: { step: Step }) {
  const [all, setAll] = useState(false);
  const shown = all ? step.log : step.log.slice(-8);
  // A step started from a button above or on the canvas: bring its progress into view.
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (step.running) box.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [step.running]);
  return (
    <div ref={box} className={step.running ? "copilot-step running" : "copilot-step"} aria-live="polite">
      <div className="copilot-step-header">
        <strong>
          {step.running ? `${STEP_TITLES[step.kind]}…` : step.error ? "Stopped with an error" : "Last run"}
        </strong>
        {step.progress && (
          <span className="muted">
            {step.progress.done}/{step.progress.total}
          </span>
        )}
        <span className="spacer" />
        {step.running && (
          <button className="small danger" onClick={stop}>
            Stop
          </button>
        )}
        {step.log.length > 8 && (
          <button className="link" onClick={() => setAll(!all)}>
            {all ? "Fewer" : `All ${step.log.length} lines`}
          </button>
        )}
      </div>
      <ol className="copilot-log">
        {shown.map((line, i) => (
          <li key={i} className={line.tone}>
            {line.text}
          </li>
        ))}
      </ol>
      {step.error && (
        <div className="call-notice error">
          {step.error.message}
          {step.error.problems.length > 0 && (
            <ul>
              {step.error.problems.map((p, i) => (
                <li key={i}>{p}</li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

// ---- requirements -------------------------------------------------------------------------------
function Requirements({ spec, proposal }: { spec: Spec; proposal: Proposal | null }) {
  // What carries each requirement comes from the build: before one, nothing is flagged.
  const uncarried = useMemo(
    () => new Map((proposal?.uncarried ?? []).map((u) => [u.requirement, u.reason])),
    [proposal],
  );
  const untested = new Set(spec.gaps?.untested ?? []);
  const flagged = spec.requirements.filter((r) => uncarried.has(r.id) || untested.has(r.id)).length;
  return (
    <Card
      title={`Requirements (${spec.requirements.length})`}
      aside={flagged > 0 && <span className="badge warning">{flagged} flagged</span>}
      collapsible
    >
      {!proposal && (
        <div className="hint">The build says what carries each one; until then none is flagged as uncarried.</div>
      )}
      <ul className="copilot-list">
        {spec.requirements.map((r) => (
          <RequirementRow key={r.id} requirement={r} uncarried={uncarried.get(r.id)} untested={untested.has(r.id)} />
        ))}
      </ul>
      {spec.set_aside.length > 0 && (
        <details className="copilot-aside">
          <summary className="muted">{plural(spec.set_aside.length, "sentence")} set aside</summary>
          <ul className="copilot-list">
            {spec.set_aside.map((s, i) => (
              <li key={i}>
                <q>{s.source}</q> <span className="muted">{s.reason}</span>
              </li>
            ))}
          </ul>
        </details>
      )}
    </Card>
  );
}

function RequirementRow({
  requirement: r,
  uncarried,
  untested,
}: {
  requirement: Requirement;
  uncarried?: string;
  untested: boolean;
}) {
  return (
    <li className={uncarried !== undefined ? "requirement uncarried" : "requirement"}>
      <div>
        <code className="muted">{r.id}</code> {r.text}{" "}
        {r.baseline && (
          <span className="badge" title="A rule every agent has, not from the guidelines">
            Baseline
          </span>
        )}
        {r.question && (
          <span className="badge" title="The default answer to a client question">
            Default for {r.question}
          </span>
        )}
        {untested && <span className="badge warning">No test</span>}
      </div>
      {r.sources.map((source, i) => (
        <blockquote key={i} className="copilot-source">
          {source}
        </blockquote>
      ))}
      {uncarried !== undefined && (
        <div className="copilot-flag">
          <span className="badge warning">Nothing carries it</span> <span className="muted">{uncarried}</span>
        </div>
      )}
    </li>
  );
}

// ---- client questions ---------------------------------------------------------------------------
/** The questions as text for the client: the spec's, then those the build's diagnoses raised. */
export function questionsText(spec: Spec, proposal: Proposal | null): string {
  const lines = ["Questions about your guidelines:", ""];
  spec.questions.forEach((q, i) => {
    lines.push(`${i + 1}. ${q.question}`, `   Until we hear from you: ${q.default}`, "");
  });
  (proposal?.questions ?? []).forEach((q, i) => lines.push(`${spec.questions.length + i + 1}. ${q.question}`, ""));
  return lines.join("\n").trimEnd() + "\n";
}

function Questions({ spec, proposal }: { spec: Spec; proposal: Proposal | null }) {
  const [copied, setCopied] = useState(false);
  const fromBuild = proposal?.questions ?? [];
  if (!spec.questions.length && !fromBuild.length) return null;
  async function copy() {
    await navigator.clipboard.writeText(questionsText(spec, proposal));
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  }
  return (
    <Card
      title={`Client questions (${spec.questions.length + fromBuild.length})`}
      aside={
        <button className="small" onClick={() => void copy()}>
          {copied ? "Copied" : "Copy for the client"}
        </button>
      }
    >
      <ul className="copilot-list">
        {spec.questions.map((q) => (
          <li key={q.id}>
            <code className="muted">{q.id}</code> {q.question}
            <div className="muted">Until answered: {q.default}</div>
          </li>
        ))}
        {fromBuild.map((q, i) => (
          <li key={`build-${i}`}>
            {q.question}
            <div className="muted">Raised by the build, from test {q.test}.</div>
          </li>
        ))}
      </ul>
    </Card>
  );
}

// ---- configuration ------------------------------------------------------------------------------
function Configuration({ configuration }: { configuration: unknown }) {
  const info = useMemo(() => (configuration ? readClinic(configuration) : null), [configuration]);
  if (!info) return null;
  return (
    <Card title="Clinic configuration" collapsible>
      <div className="hint">
        What the tools enforce, read-only. Change it through the guidelines and a new spec step.
      </div>
      <div className="copilot-clinic">
        <ClinicSections info={info} />
      </div>
    </Card>
  );
}

// ---- tests --------------------------------------------------------------------------------------
const RESULT_ICONS: Record<TestRow["status"], string> = { pass: "✓", flaky: "~", fail: "✕", error: "!" };

function Tests({ spec, run }: { spec: Spec; run: TestRun | null }) {
  const busy = useCopilotStore((s) => s.step?.running === true);
  const results = useMemo(() => new Map((run?.summary?.tests ?? []).map((r) => [r.test_id, r])), [run]);
  const drafts = spec.tests.filter((t) => t.status === "draft").length;
  return (
    <Card
      title={`Tests (${spec.tests.length})`}
      aside={
        drafts > 0 && (
          <button className="small primary" disabled={busy} onClick={() => void approve()}>
            Approve all {drafts}
          </button>
        )
      }
      collapsible
      open={drafts > 0}
    >
      <div className="hint">
        {drafts > 0
          ? `${plural(drafts, "draft")} to review. Approved tests are locked; the build must pass them.`
          : "All approved. Approved tests are locked; the build must pass them."}
      </div>
      <ul className="copilot-list">
        {spec.tests.map((t) => (
          <TestItem key={t.id} test={t} result={results.get(t.id)} busy={busy} />
        ))}
      </ul>
    </Card>
  );
}

function TestItem({ test: t, result, busy }: { test: SpecTest; result?: TestRow; busy: boolean }) {
  return (
    <li className="copilot-test">
      <div className="copilot-test-head">
        <span
          className={`result-icon ${result?.status ?? "none"}`}
          title={result ? `Last run: ${result.status}` : "Not run yet"}
        >
          {result ? RESULT_ICONS[result.status] : "○"}
        </span>
        <span className="grow">{t.title}</span>
      </div>
      <div className="copilot-test-meta">
        <code className="muted">{t.id}</code>
        <span className={t.tier === "safety" ? "badge error" : "badge"}>{t.tier}</span>
        <span className="muted">{t.requirements.join(", ")}</span>
        <span className="spacer" />
        {t.status === "approved" ? (
          <span className="badge optional">Approved</span>
        ) : (
          <>
            <button className="small" disabled={busy} onClick={() => void approve(t.id)}>
              Approve
            </button>
            <button className="small danger" disabled={busy} onClick={() => void removeTest(t.id)}>
              Delete
            </button>
          </>
        )}
      </div>
      {result && result.failed.length > 0 && (
        <ul className="copilot-failed">
          {result.failed.map((c, i) => (
            <li key={i}>
              {c.turn !== null && <span className="muted">turn {c.turn}: </span>}
              {c.detail ?? c.rule ?? c.type}
            </li>
          ))}
        </ul>
      )}
    </li>
  );
}

// ---- build --------------------------------------------------------------------------------------
function Build({ spec }: { spec: Spec }) {
  const busy = useCopilotStore((s) => s.step?.running === true);
  const approved = spec.tests.filter((t) => t.status === "approved").length;
  const why = approved === 0 ? "Approve the tests the agent must pass first." : undefined;
  return (
    <Card title="Build">
      <div className="row">
        <button className="primary" disabled={busy || approved === 0} title={why} onClick={() => void build(true)}>
          Build and test
        </button>
        <button disabled={busy || approved === 0} title={why} onClick={() => void build(false)}>
          Build only
        </button>
      </div>
      <div className="hint">
        Customizes the scheduling template, then fixes it until the {plural(approved, "approved test")} pass, at most 3
        rounds: about $3 to $12 in model calls (tests are cached). Build only skips the tests: about $0.05. The canvas
        shows the agent as it is built.
      </div>
      <StepLog kind="build" />
    </Card>
  );
}

// ---- a fix from an issue (#33) ------------------------------------------------------------------
function Fix({ report }: { report: FixReport | null }) {
  const running = useCopilotStore((s) => s.step?.kind === "fix" && s.step.running);
  return (
    <Card title="Fix from an issue">
      {report && !running && (
        <p>
          {report.issue.label ?? report.issue.kind} in call <code>{report.issue.call}</code>, decided at turn{" "}
          {report.issue.turn}: {report.message}
        </p>
      )}
      <div className="hint">
        Started from an issue in the Calls tab. The issue is reproduced first (the call continued 5 times on the saved
        agent); then 3 candidate changes are tried on the decisive turn and in full, and the one that passes the
        reproduction most often goes through the tests: about $6 in model calls, mostly simulated calls.
      </div>
      <StepLog kind="fix" />
    </Card>
  );
}

// ---- the proposal -------------------------------------------------------------------------------
function ProposalCard({ proposal }: { proposal: Proposal }) {
  const draft = useAgentStore((s) => s.agent);
  const notice = useCopilotStore((s) => s.notice);
  const shown = useCopilotStore((s) => s.canvas?.mode === "proposal");
  const busy = useCopilotStore((s) => s.step?.running === true);
  // Against the draft as it is now: after accepting, nothing is left to mark.
  const diff = useMemo(() => (draft ? nodeDiff(proposal.agent, draft) : null), [proposal, draft]);
  const pending = isPending(proposal);
  const blocked = proposal.status === "blocked";
  const leaked = proposal.leaks.length > 0;
  const refusal = pending ? acceptRefusal() : null;
  const added = diff ? [...diff.marks].filter(([, m]) => m === "added").map(([n]) => n) : [];
  const changed = diff ? [...diff.marks].filter(([, m]) => m === "changed").map(([n]) => n) : [];
  const decision = proposal.decision;
  const cost = (proposal.meta.cost.copilot ?? 0) + (proposal.meta.cost.tests ?? 0);

  return (
    <Card
      title={`Proposal ${proposal.number}`}
      aside={
        decision ? (
          <span className="badge optional">
            {decision.status === "accepted" ? `Accepted as version ${decision.version}` : "Rejected"}
          </span>
        ) : (
          <span className={blocked ? "badge error" : "badge"}>{blocked ? "Blocked" : "Ready"}</span>
        )
      }
    >
      <ul className="copilot-facts">
        {proposal.kind === "fix" ? (
          <FixFacts proposal={proposal} />
        ) : (
          <>
            <li>
              {plural(proposal.operations.length, "operation")} on the template ({operationCounts(proposal)})
            </li>
            <li>
              {plural(proposal.configuration_entries ?? 0, "configuration entry").replace("entrys", "entries")}
              {proposal.configuration_changes.length > 0 &&
                `, ${plural(proposal.configuration_changes.length, "change")} by the fix loop (${proposal.configuration_changes.map((c) => c.key).join(", ")})`}
            </li>
          </>
        )}
        {pending && diff && (
          <li>
            Against your draft: {added.length > 0 ? <NodeNames label="added" names={added} /> : "none added"},{" "}
            {changed.length > 0 ? <NodeNames label="changed" names={changed} /> : "none changed"}
            {diff.removed.length > 0 && (
              <>
                , <NodeNames label="removed" names={diff.removed} />
              </>
            )}
            .
          </li>
        )}
        {proposal.results ? (
          <li>
            Tests: <Score summary={proposal.results.before} />{" "}
            {proposal.kind === "fix" ? "on the current agent" : "before the fixes"}, <Score summary={proposal.results.after} />{" "}
            after
            {proposal.not_rerun && proposal.not_rerun.length > 0 && ` (the ${plural(proposal.not_rerun.length, "test")} failing before were not run again)`}
            {proposal.rounds.length > 0 &&
              ` (${plural(proposal.rounds.length, "round")}, ${proposal.rounds.filter((r) => r.kept).length} kept)`}
          </li>
        ) : (
          <li>Tests not run (built without them).</li>
        )}
        <li className="muted">
          {Math.round(proposal.meta.seconds)} s, about ${cost.toFixed(2)}
        </li>
      </ul>

      {proposal.candidates && <Candidates proposal={proposal} />}

      {proposal.outline && proposal.outline.length > 0 && (
        <details className="copilot-aside">
          <summary className="muted">What the build did ({proposal.outline.length})</summary>
          <ol className="copilot-list">
            {proposal.outline.map((line, i) => (
              <li key={i}>{line}</li>
            ))}
          </ol>
        </details>
      )}

      {proposal.diagnoses.length > 0 && (
        <details className="copilot-aside" open={pending}>
          <summary>Why {plural(proposal.diagnoses.length, "test")} still fail</summary>
          <ul className="copilot-list">
            {proposal.diagnoses.map((d) => (
              <li key={d.test}>
                <code>{d.test}</code> {d.link && <span className="badge warning">{d.link.replace(/_/g, " ")}</span>}
                {d.turn !== null && <span className="muted"> turn {d.turn}</span>}
                <div>{d.explanation}</div>
                {d.question && <div className="muted">Question for the client: {d.question}</div>}
              </li>
            ))}
          </ul>
        </details>
      )}

      {pending && blocked && (
        <div className="call-notice error">
          <strong>Blocked:</strong>
          <ul>
            {/* The diagnosis of each failing test is above; here only what fails. */}
            {proposal.blocked.map((reason, i) => (
              <li key={i}>{reason.split(" Broken link:")[0]}</li>
            ))}
          </ul>
          {leaked
            ? "A test caller's details are in it, so it cannot be accepted."
            : "You can still accept it, knowingly."}
        </div>
      )}

      {pending && (
        <div className="row copilot-decide">
          {blocked ? (
            <button
              className="danger"
              disabled={busy || leaked || refusal !== null}
              title={refusal ?? undefined}
              onClick={() => void accept(true)}
            >
              Accept anyway
            </button>
          ) : (
            <button
              className="primary"
              disabled={busy || refusal !== null}
              title={refusal ?? undefined}
              onClick={() => void accept(false)}
            >
              Accept
            </button>
          )}
          <button disabled={busy} onClick={() => void reject()}>
            Reject
          </button>
          <span className="spacer" />
          <button className="link" disabled={busy} onClick={() => showProposal(!shown)}>
            {shown ? "Show my draft" : "Show on canvas"}
          </button>
        </div>
      )}
      {pending && refusal && <div className="call-notice error">{refusal}</div>}
      {notice && <div className={`call-notice ${notice.tone === "error" ? "error" : "info"}`}>{notice.text}</div>}
    </Card>
  );
}

/** What a fix's proposal shows first: the issue, the reproduction before and after, the turn. */
function FixFacts({ proposal }: { proposal: Proposal }) {
  const { issue, reproduction, turn_before: turnBefore, diagnosis } = proposal;
  if (!issue || !reproduction) return null;
  const chosen = proposal.candidates?.find((c) => c.number === proposal.chosen);
  return (
    <>
      <li>
        Fixes <strong>{issue.label ?? issue.kind}</strong> in call <code>{issue.call}</code>
        {issue.requirement && <span className="chip">{issue.requirement}</span>}, decided at turn {issue.turn} in{" "}
        <code>{issue.node}</code>.
      </li>
      <li>
        Reproduction <code>{reproduction.test.id}</code>: <strong>{reproduction.before.failed}/{reproduction.before.k}</strong> fail on
        the current agent
        {reproduction.after && (
          <>
            , <strong>{reproduction.after.passed}/{reproduction.after.k}</strong> pass with the fix
          </>
        )}
        .
      </li>
      {reproduction.corrections.length > 0 && (
        <li className="muted">
          The caller said{" "}
          {reproduction.corrections.map((c) => `“${c.said}”, heard as “${c.heard}” (ticket ${c.ticket})`).join("; ")}.
        </li>
      )}
      {diagnosis && (
        <li>
          <span className="badge warning">{diagnosis.link.replace(/_/g, " ")}</span> {diagnosis.explanation}
        </li>
      )}
      {chosen && (
        <li>
          Decisive turn replayed: {turnBefore?.rate ?? "?"} on the current agent, {chosen.turn.rate} with candidate{" "}
          {chosen.number} ({plural(proposal.operations.length, "operation")}: {operationCounts(proposal)}).
        </li>
      )}
    </>
  );
}

function Candidates({ proposal }: { proposal: Proposal }) {
  const candidates = proposal.candidates ?? [];
  const agreement = proposal.agreement;
  return (
    <details className="copilot-aside">
      <summary className="muted">
        {plural(candidates.length, "candidate")}
        {agreement && `: the turn replay agreed with the full reproduction on ${agreement.agreed} of ${agreement.of}`}
      </summary>
      <ol className="copilot-list">
        {candidates.map((c) => (
          <li key={c.number}>
            {c.number === proposal.chosen && <span className="badge">chosen</span>} {c.rationale}
            <div className="muted">
              Turn {c.turn.rate ?? `not replayed: ${c.turn.error}`}
              {c.full && `, full reproduction ${c.full.rate}`} · {plural(c.operations.length, "operation")}
            </div>
          </li>
        ))}
      </ol>
      <div className="hint">
        The candidate is chosen on the turn replay alone, before any full call runs; every candidate's full reproduction
        is reported to measure how well the turn replay predicts it.
      </div>
    </details>
  );
}

function operationCounts(proposal: Proposal): string {
  const counts = new Map<string, number>();
  for (const op of proposal.operations) counts.set(op.op, (counts.get(op.op) ?? 0) + 1);
  return [...counts].map(([op, n]) => `${n} ${op.replace(/_/g, " ")}`).join(", ") || "none";
}

function NodeNames({ label, names }: { label: string; names: string[] }) {
  return (
    <span title={names.join(", ")}>
      <span className={`diff-key ${label}`} /> {names.length} {label} ({names.join(", ")})
    </span>
  );
}

function Score({ summary }: { summary: TestSummary }) {
  return (
    <strong>
      {summary.passing}/{summary.total}
    </strong>
  );
}

// ---- running the tests --------------------------------------------------------------------------
function RunTests({ spec, run }: { spec: Spec; run: TestRun | null }) {
  const busy = useCopilotStore((s) => s.step?.running === true);
  const hasAgent = useAgentStore((s) => s.agent !== null);
  const approved = spec.tests.filter((t) => t.status === "approved").length;
  return (
    <Card title="Run tests">
      <div className="row">
        <button disabled={busy || !hasAgent || approved === 0} onClick={() => void runTests()}>
          Run the {plural(approved, "approved test")}
        </button>
      </div>
      <div className="hint">
        On the agent as it is in the editor, against the workspace's configuration. Cached results are free; a full
        uncached run is about $2.50.
      </div>
      {run?.summary && (
        <div className="copilot-run">
          Last run: <Score summary={run.summary} /> passing
          {run.summary.counts.flaky > 0 && `, ${run.summary.counts.flaky} flaky`}
          <span className="muted">
            {" "}
            · {new Date(run.created).toLocaleString()}
            {run.proposal !== null && ` · proposal ${run.proposal}`}
            {run.cost !== null && run.cost !== undefined && ` · $${run.cost.toFixed(2)}`}
          </span>
        </div>
      )}
      <StepLog kind="tests" />
    </Card>
  );
}
