import { useEffect, useState, type ReactNode } from "react";

import { getClinic, type ClinicProblem } from "../api";
import { patientsLabel, readClinic, type ClinicField, type ClinicInfo } from "./clinic";

// The Clinic tab (#43, ADR 0016): the open agent's clinic, read-only. An agent is
// a template graph plus a clinic configuration; the graph says how to talk, the
// configuration says what the clinic offers, and the tools enforce it. Editing it at
// approval time was cut from #31: it changes through the guidelines and a new spec step.

export type ClinicLoad =
  | { id: string; info: ClinicInfo | null; problems: ClinicProblem[] }
  | { id: string; error: string }
  | null;

/**
 * The clinic file and its problems, fetched when `id` changes and again when
 * `reload` changes (the Clinic tab is opened), so edits to the file show.
 */
export function useClinic(id: string, reload: unknown): ClinicLoad {
  const [state, setState] = useState<ClinicLoad>(null);
  useEffect(() => {
    let current = true;
    getClinic(id)
      .then((body) => current && setState({ id, info: body.clinic === null ? null : readClinic(body.clinic), problems: body.problems }))
      .catch((error) => current && setState({ id, error: String(error) }));
    return () => {
      current = false;
    };
  }, [id, reload]);
  // Until the new clinic arrives, show nothing rather than the previous one.
  return state?.id === id ? state : null;
}

export function ClinicView({ load }: { load: ClinicLoad }) {
  let content: ReactNode;
  if (!load) content = <p className="muted">Loading the clinic…</p>;
  else if ("error" in load) content = <p className="field-error">Could not load clinic '{load.id}': {load.error}</p>;
  else content = <ClinicPage id={load.id} info={load.info} problems={load.problems} />;
  return (
    <div className="clinic-view nokey" role="tabpanel" aria-label="Clinic">
      <div className="clinic-page">{content}</div>
    </div>
  );
}

function ClinicPage({ id, info, problems }: { id: string; info: ClinicInfo | null; problems: ClinicProblem[] }) {
  return (
    <>
      <header className="clinic-header">
        <h2>{info?.name ?? id}</h2>
        <div className="muted">
          <span className="mono">backend/clinic/clinics/{id}.json</span>
          {info?.now && <> · clinic time {clinicTime(info.now)}</>}
        </div>
        <p>
          An agent is a template graph plus a clinic configuration. The graph says how to talk; this configuration
          says what the clinic offers, and the tools enforce it, so none of it is in a prompt. Read-only here; the agent
          panel picks the clinic.
        </p>
      </header>
      {problems.length > 0 && <Problems problems={problems} />}
      {info && <ClinicSections info={info} />}
    </>
  );
}

/** The configuration's grids and lists, also shown by the Copilot panel's configuration card (#31). */
export function ClinicSections({ info }: { info: ClinicInfo }) {
  return (
    <>
      <WhoDoesWhat info={info} />
      <Coverage info={info} />
      <Fields info={info} />
      <LateChanges info={info} />
      <Facts info={info} />
    </>
  );
}

function Section(props: { title: string; tools: string[]; children: ReactNode }) {
  return (
    <section className="clinic-section">
      <div className="clinic-section-header">
        <h3>{props.title}</h3>
        <span className="muted">
          enforced by{" "}
          {props.tools.map((tool, i) => (
            <span key={tool}>
              {i > 0 && ", "}
              <code>{tool}</code>
            </span>
          ))}
        </span>
      </div>
      {props.children}
    </section>
  );
}

function Problems({ problems }: { problems: ClinicProblem[] }) {
  return (
    <section className="clinic-section clinic-problems" aria-label="Clinic problems">
      <h3>
        {problems.length} problem{problems.length === 1 ? "" : "s"} in the configuration
      </h3>
      <ul>
        {problems.map((p, i) => (
          <li key={i}>
            <span className="problem-dot error" aria-hidden />
            <span className="mono">{p.path || "(file)"}</span>
            <span>{p.message}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}

const Yes = ({ label }: { label: string }) => (
  <span className="cell-yes" role="img" aria-label={label}>
    ✓
  </span>
);
const No = ({ label }: { label: string }) => (
  <span className="cell-no" role="img" aria-label={label}>
    –
  </span>
);

/** Appointment types by providers; each provider with their weekly hours. */
function WhoDoesWhat({ info }: { info: ClinicInfo }) {
  return (
    <Section title="Who does what" tools={["list_appointment_types", "find_slots", "book_appointment"]}>
      <div className="clinic-table-wrap">
        <table className="clinic-table">
          <thead>
            <tr>
              <th className="type-col">Appointment type</th>
              {info.providers.map((p, i) => (
                <th key={i} className="grid-col">
                  <div>{p.name}</div>
                  <div className="muted clinic-sub">
                    {p.specialty && <div>{p.specialty}</div>}
                    <div>{p.slotMinutes} min slots</div>
                    {p.hours.length ? (
                      p.hours.map((h) => (
                        <div key={h.days}>
                          {h.days}{" "}
                          {h.hours.map((range, k) => (
                            <span key={k} className="nowrap">
                              {range}
                              {k < h.hours.length - 1 && ", "}
                            </span>
                          ))}
                        </div>
                      ))
                    ) : (
                      <div>No hours</div>
                    )}
                  </div>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {info.types.length === 0 && (
              <tr>
                <td className="muted">No appointment types: every provider takes any visit, and the tools take no type.</td>
                {info.providers.map((p, i) => (
                  <td key={i} className="grid-col">
                    <Yes label={`${p.name}: any visit`} />
                  </td>
                ))}
              </tr>
            )}
            {info.types.map((t, i) => (
              <tr key={i}>
                <td>
                  <div className="type-name">
                    {t.name} <code className="muted">{t.id}</code>
                  </div>
                  {t.description && <div className="clinic-sub">{t.description}</div>}
                  <span className={`who ${["new", "existing", "any"].includes(t.patients) ? t.patients : "invalid"}`}>
                    {patientsLabel(t.patients)}
                  </span>
                </td>
                {info.providers.map((p, j) =>
                  t.providers.includes(p.id) ? (
                    <td key={j} className="grid-col">
                      <Yes label={`${p.name} does ${t.name}`} />
                    </td>
                  ) : (
                    <td key={j} className="grid-col">
                      <No label={`${p.name} does not do ${t.name}`} />
                    </td>
                  ),
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Section>
  );
}

/** Appointment types by insurance plans. */
function Coverage({ info }: { info: ClinicInfo }) {
  let content: ReactNode;
  if (!info.plans.length) {
    content = <p className="muted">No insurance plans: check_coverage answers that the clinic has none on file.</p>;
  } else if (!info.types.length) {
    content = <p>Plans accepted: {info.plans.map((p) => p.name).join(", ")}. No appointment types to cover.</p>;
  } else {
    content = (
      <div className="clinic-table-wrap">
        <table className="clinic-table">
          <thead>
            <tr>
              <th className="type-col">Appointment type</th>
              {info.plans.map((p, i) => (
                <th key={i} className="grid-col">
                  {p.name}
                  <div className="muted clinic-sub">
                    <code>{p.id}</code>
                  </div>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {info.types.map((t, i) => (
              <tr key={i}>
                <td className="type-name">{t.name}</td>
                {info.plans.map((p, j) => (
                  <td key={j} className="grid-col">
                    {p.covers.includes(t.id) ? (
                      <Yes label={`${p.name} covers ${t.name}`} />
                    ) : (
                      <No label={`${p.name} does not cover ${t.name}`} />
                    )}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }
  return (
    <Section title="Coverage" tools={["check_coverage"]}>
      {content}
    </Section>
  );
}

function Fields({ info }: { info: ClinicInfo }) {
  return (
    <div className="clinic-columns">
      <Section title="Asked at registration" tools={["register_patient"]}>
        <FieldList fields={info.registrationFields} tool="register_patient" />
      </Section>
      <Section title="Asked at booking" tools={["book_appointment"]}>
        <FieldList fields={info.bookingFields} tool="book_appointment" />
      </Section>
    </div>
  );
}

function FieldList({ fields, tool }: { fields: ClinicField[]; tool: string }) {
  if (!fields.length) return <p className="muted">Nothing beyond {tool}'s own parameters.</p>;
  return (
    <>
      <p className="muted">Added to {tool}'s parameters, so the model sees them in its schema.</p>
      <ul className="clinic-fields">
        {fields.map((f, i) => (
          <li key={i}>
            <code>{f.name}</code>{" "}
            <span className={f.required ? "badge required" : "badge optional"}>{f.required ? "Required" : "Optional"}</span>
            {f.description && <div className="clinic-sub">{f.description}</div>}
          </li>
        ))}
      </ul>
    </>
  );
}

function LateChanges({ info }: { info: ClinicInfo }) {
  const rule = info.cancellation;
  return (
    <Section title="Late changes" tools={["cancel_appointment", "reschedule_appointment"]}>
      {rule ? (
        <p>
          Cancelling or rescheduling less than <strong>{rule.windowHours} hours</strong> before the visit costs{" "}
          <strong>${rule.fee}</strong>. Both tools refuse, stating the fee, until the caller accepts it (
          <code>fee_acknowledged</code>).
        </p>
      ) : (
        <p className="muted">No fee: changes are free at any time, and the tools take no fee_acknowledged.</p>
      )}
    </Section>
  );
}

function Facts({ info }: { info: ClinicInfo }) {
  return (
    <Section title="Facts" tools={["get_clinic_info"]}>
      {info.facts.length ? (
        <dl className="clinic-facts">
          {info.facts.map((f) => (
            <div key={f.label}>
              <dt>{f.label}</dt>
              <dd>{f.text || <span className="muted">(empty)</span>}</dd>
            </div>
          ))}
        </dl>
      ) : (
        <p className="muted">No facts: get_clinic_info has nothing to answer with.</p>
      )}
    </Section>
  );
}

/** "2026-10-12T08:30" as "Mon, Oct 12, 2026, 8:30 AM". The seed's time has no zone, so it is read as is. */
function clinicTime(now: string): string {
  const date = new Date(now);
  if (Number.isNaN(date.getTime())) return now;
  return date.toLocaleString("en-US", {
    weekday: "short",
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}
