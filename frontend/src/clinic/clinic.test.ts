import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

import { patientsLabel, readClinic, weeklyHours } from "./clinic";

const read = (path: string) => JSON.parse(readFileSync(new URL(path, import.meta.url), "utf8"));
const riverside = read("../../../backend/clinic/clinics/riverside.json");
const plain = read("../../../backend/tests/fixtures/clinic-plain.json");

describe("readClinic", () => {
  it("reads Riverside's configuration", () => {
    const info = readClinic(riverside);
    expect(info.name).toBe("Riverside Family Clinic");
    expect(info.now).toBe("2026-10-12T08:30");
    expect(info.providers.map((p) => [p.id, p.name, p.slotMinutes])).toEqual([
      ["dr-patel", "Dr. Priya Patel", 30],
      ["dr-okafor", "Dr. Daniel Okafor", 30],
      ["np-kim", "Grace Kim", 20],
    ]);
    expect(info.types.map((t) => [t.id, t.patients, t.providers])).toEqual([
      ["checkup", "any", ["dr-patel", "dr-okafor"]],
      ["new_patient", "new", ["dr-patel"]],
      ["sick_visit", "any", ["dr-patel", "dr-okafor", "np-kim"]],
      ["follow_up", "existing", ["dr-patel", "dr-okafor"]],
      ["vaccination", "any", ["np-kim"]],
    ]);
    expect(info.plans.map((p) => [p.name, p.covers.length])).toEqual([
      ["Blue Shield PPO", 5],
      ["Aetna HMO", 3],
      ["Medicare", 4],
    ]);
    expect(info.registrationFields).toEqual([
      { name: "insurance_plan", description: expect.stringContaining("insurance plan"), required: true },
    ]);
    expect(info.bookingFields.map((f) => f.name)).toEqual(["interpreter"]);
    expect(info.cancellation).toEqual({ windowHours: 24, fee: 50 });
    expect(info.facts.map((f) => f.label)).toEqual(["address", "hours", "parking", "phone"]);
  });

  it("reads a clinic without configuration as empty lists and no fee", () => {
    const info = readClinic(plain);
    expect(info.providers).toHaveLength(3);
    expect(info).toMatchObject({
      types: [],
      plans: [],
      registrationFields: [],
      bookingFields: [],
      cancellation: null,
      facts: [],
    });
  });

  it("takes a broken file without throwing, keeping what it can show", () => {
    const info = readClinic({
      clinic: "Riverside",
      providers: [{ id: "dr-a", schedule: "weekdays" }, "dr-b", { name: "No Id" }],
      appointment_types: [{ id: "checkup", patients: "kids", providers: "dr-a" }, null],
      insurance_plans: [{ id: "aetna", covers: ["checkup", 3] }],
      booking_fields: [{ name: "pharmacy", required: "yes" }],
      cancellation: { window_hours: "a day", fee: -5 },
      facts: { parking: "", phone: 5550100 },
    });
    expect(info.name).toBeNull();
    expect(info.providers.map((p) => [p.id, p.name, p.hours])).toEqual([
      ["dr-a", "dr-a", []],
      ["", "No Id", []],
    ]);
    expect(info.types).toEqual([{ id: "checkup", name: "checkup", description: "", patients: "kids", providers: [] }]);
    expect(info.plans).toEqual([{ id: "aetna", name: "aetna", covers: ["checkup"] }]);
    expect(info.bookingFields).toEqual([{ name: "pharmacy", description: "", required: false }]);
    expect(info.cancellation).toBeNull();
    expect(info.facts).toEqual([
      { label: "parking", text: "" },
      { label: "phone", text: "" },
    ]);
    expect(readClinic(null).providers).toEqual([]);
    expect(readClinic([1, 2]).types).toEqual([]);
  });

  it("treats a fee of 0 as no fee, as the tools do", () => {
    expect(readClinic({ cancellation: { window_hours: 24, fee: 0 } }).cancellation).toBeNull();
  });
});

describe("weeklyHours", () => {
  it("groups days with the same hours, in weekday order", () => {
    const [patel, okafor, kim] = readClinic(riverside).providers;
    expect(patel.hours).toEqual([
      { days: "Mon–Thu", hours: ["9:00–12:00", "13:00–17:00"] },
      { days: "Fri", hours: ["9:00–12:00"] },
    ]);
    expect(okafor.hours).toEqual([{ days: "Mon, Wed, Fri", hours: ["8:00–12:00"] }]);
    expect(kim.hours).toEqual([{ days: "Tue, Thu", hours: ["12:00–18:00"] }]);
  });

  it("names runs of three days or more with a dash, shorter runs one by one", () => {
    const same = ["10:00-14:00"];
    expect(weeklyHours({ mon: same, tue: same, thu: same, fri: same, sat: same })).toEqual([
      { days: "Mon, Tue, Thu–Sat", hours: ["10:00–14:00"] },
    ]);
  });

  it("skips days without hours and keeps a range it cannot read as it is", () => {
    expect(weeklyHours({ mon: [], sun: ["mornings"] })).toEqual([{ days: "Sun", hours: ["mornings"] }]);
    expect(weeklyHours(undefined)).toEqual([]);
  });
});

it("says who may book a type", () => {
  expect(["new", "existing", "any", "kids"].map(patientsLabel)).toEqual([
    "New patients only",
    "Existing patients only",
    "New and existing patients",
    'Invalid: "kids"',
  ]);
});
