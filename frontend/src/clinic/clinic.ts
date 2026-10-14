// What the Clinic tab shows, read from a clinic file (backend/clinic/clinics/<id>.json,
// ADR 0016). The backend loader (clinic/config.py) is the authority on what is wrong
// with a file and reports it with paths; this only reads what is there, and takes
// any shape without throwing, so a broken configuration still shows next to its problems.

export interface ClinicProvider {
  id: string;
  name: string;
  specialty: string | null;
  slotMinutes: number;
  hours: WeeklyHours[];
}

/** Days with the same opening hours, such as "Mon–Thu" and ["9:00–12:00", "13:00–17:00"]. */
export interface WeeklyHours {
  days: string;
  hours: string[];
}

export interface ClinicType {
  id: string;
  name: string;
  description: string;
  /** "new", "existing" or "any"; anything else is kept to show as invalid. */
  patients: string;
  providers: string[];
}

export interface ClinicPlan {
  id: string;
  name: string;
  covers: string[];
}

export interface ClinicField {
  name: string;
  description: string;
  required: boolean;
}

export interface ClinicInfo {
  name: string | null;
  now: string | null;
  providers: ClinicProvider[];
  types: ClinicType[];
  plans: ClinicPlan[];
  registrationFields: ClinicField[];
  bookingFields: ClinicField[];
  /** The late-change fee, or null when changes are free. */
  cancellation: { windowHours: number; fee: number } | null;
  facts: { label: string; text: string }[];
}

type Json = Record<string, unknown>;

const object = (value: unknown): Json | null =>
  value && typeof value === "object" && !Array.isArray(value) ? (value as Json) : null;
const objects = (value: unknown): Json[] => (Array.isArray(value) ? value.map(object).filter((v) => v !== null) : []);
const text = (value: unknown): string | null => (typeof value === "string" && value.trim() ? value : null);
const texts = (value: unknown): string[] => (Array.isArray(value) ? value.filter((v) => typeof v === "string") : []);
const number = (value: unknown): number | null => (typeof value === "number" && Number.isFinite(value) ? value : null);

// Defaults as in clinic/world.py.
const DEFAULT_SLOT_MINUTES = 30;
const WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"];
const DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

export function readClinic(data: unknown): ClinicInfo {
  const file = object(data) ?? {};
  const clinic = object(file.clinic) ?? {};
  const fields = (key: string): ClinicField[] =>
    objects(file[key]).map((f) => ({
      name: text(f.name) ?? "(no name)",
      description: text(f.description) ?? "",
      required: f.required === true,
    }));
  const rule = object(file.cancellation);
  const fee = number(rule?.fee);
  return {
    name: text(clinic.name),
    now: text(clinic.now),
    providers: objects(file.providers).map((p) => {
      const id = text(p.id) ?? "";
      return {
        id,
        name: text(p.name) ?? (id || "(no id)"),
        specialty: text(p.specialty),
        slotMinutes: number(p.slot_minutes) ?? DEFAULT_SLOT_MINUTES,
        hours: weeklyHours(p.schedule),
      };
    }),
    types: objects(file.appointment_types).map((t) => {
      const id = text(t.id) ?? "";
      return {
        id,
        name: text(t.name) ?? (id || "(no id)"),
        description: text(t.description) ?? "",
        patients: typeof t.patients === "string" ? t.patients : "any",
        providers: texts(t.providers),
      };
    }),
    plans: objects(file.insurance_plans).map((p) => {
      const id = text(p.id) ?? "";
      return { id, name: text(p.name) ?? (id || "(no id)"), covers: texts(p.covers) };
    }),
    registrationFields: fields("registration_fields"),
    bookingFields: fields("booking_fields"),
    // As in clinic/world.py, a fee of 0 means no fee. A negative one is a problem the loader reports.
    cancellation: fee && fee > 0 ? { windowHours: number(rule?.window_hours) ?? 0, fee } : null,
    facts: Object.entries(object(file.facts) ?? {}).map(([label, value]) => ({
      label,
      text: typeof value === "string" ? value : "",
    })),
  };
}

/** Who may book a type, in words (as `list_appointment_types` says it). */
export function patientsLabel(patients: string): string {
  if (patients === "new") return "New patients only";
  if (patients === "existing") return "Existing patients only";
  if (patients === "any") return "New and existing patients";
  return `Invalid: "${patients}"`;
}

/**
 * A weekly schedule ({mon: ["09:00-12:00"], ...}) as lines of days with the same
 * hours, in weekday order: Mon–Thu 9:00–12:00, 13:00–17:00, then Fri 9:00–12:00.
 */
export function weeklyHours(schedule: unknown): WeeklyHours[] {
  const days = object(schedule) ?? {};
  const groups = new Map<string, { days: number[]; hours: string[] }>();
  WEEKDAYS.forEach((day, i) => {
    const hours = texts(days[day]);
    if (!hours.length) return;
    const key = hours.join(",");
    const group = groups.get(key) ?? { days: [], hours: hours.map(timeRange) };
    group.days.push(i);
    groups.set(key, group);
  });
  return [...groups.values()].map((g) => ({ days: dayRuns(g.days), hours: g.hours }));
}

/** "09:00-12:00" as "9:00–12:00"; anything else as it is. */
function timeRange(range: string): string {
  const match = /^(\d{1,2}):(\d{2})-(\d{1,2}):(\d{2})$/.exec(range.trim());
  if (!match) return range;
  const [, h1, m1, h2, m2] = match;
  return `${Number(h1)}:${m1}–${Number(h2)}:${m2}`;
}

/** Weekday indexes as "Mon–Thu" for runs of three or more, else "Mon, Wed, Fri". */
function dayRuns(days: number[]): string {
  const parts: string[] = [];
  for (let i = 0; i < days.length; ) {
    let j = i;
    while (j + 1 < days.length && days[j + 1] === days[j] + 1) j++;
    if (j - i >= 2) parts.push(`${DAY_NAMES[days[i]]}–${DAY_NAMES[days[j]]}`);
    else for (let k = i; k <= j; k++) parts.push(DAY_NAMES[days[k]]);
    i = j + 1;
  }
  return parts.join(", ");
}
