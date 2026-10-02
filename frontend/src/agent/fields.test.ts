import { describe, expect, it } from "vitest";

import {
  addField,
  fieldNameError,
  fieldsOf,
  parseAction,
  parseFieldsJson,
  removeField,
  renameField,
  setRequired,
  updateFieldSpec,
} from "./fields";
import type { Edge } from "./schema";

// Like the example's record_details, plus an enum the table does not show.
const edge: Edge = {
  function: "record_details",
  description: "",
  target: "offer_times",
  properties: {
    full_name: { type: "string", description: "Caller's full name." },
    reason: { type: "string", enum: ["checkup", "other"] },
  },
  required: ["full_name", "reason"],
};

const apply = (e: Edge, patch: Partial<Edge>): Edge => {
  const next: Record<string, unknown> = { ...e, ...patch };
  for (const [k, v] of Object.entries(patch)) if (v === undefined) delete next[k];
  return next as Edge;
};

describe("collected fields", () => {
  it("lists fields in order with their spec and required flag", () => {
    expect(fieldsOf(edge).map((f) => [f.name, f.required])).toEqual([
      ["full_name", true],
      ["reason", true],
    ]);
  });

  it("renames in place and in required, keeping other spec keys", () => {
    const next = apply(edge, renameField(edge, "reason", " visit_reason "));
    expect(Object.keys(next.properties!)).toEqual(["full_name", "visit_reason"]);
    expect(next.properties!.visit_reason).toEqual({ type: "string", enum: ["checkup", "other"] });
    expect(next.required).toEqual(["full_name", "visit_reason"]);
  });

  it("rejects empty and duplicate field names", () => {
    expect(fieldNameError(edge, "reason", " ")).toMatch(/empty/);
    expect(fieldNameError(edge, "reason", "full_name")).toMatch(/already/);
    expect(fieldNameError(edge, "reason", "reason")).toBeNull();
  });

  it("changes spec keys and removes them with undefined", () => {
    const next = apply(edge, updateFieldSpec(edge, "reason", { type: "integer", enum: undefined }));
    expect(next.properties!.reason).toEqual({ type: "integer" });
    expect(next.properties!.full_name).toBe(edge.properties!.full_name);
  });

  it("toggles required without reordering the others", () => {
    const off = apply(edge, setRequired(edge, "full_name", false));
    expect(off.required).toEqual(["reason"]);
    expect(apply(off, setRequired(off, "full_name", true)).required).toEqual(["reason", "full_name"]);
  });

  it("adds a uniquely named string field, and removing the last one drops the keys", () => {
    const bare: Edge = { function: "go", description: "", target: "x" };
    const one = apply(bare, addField(bare));
    expect(one.properties).toEqual({ field: { type: "string" } });
    expect(Object.keys(apply(one, addField(one)).properties!)).toEqual(["field", "field_2"]);
    const none = apply(one, removeField(one, "field"));
    expect("properties" in none || "required" in none).toBe(false);
  });

  it("removing a field also takes it out of required", () => {
    expect(apply(edge, removeField(edge, "full_name")).required).toEqual(["reason"]);
  });
});

describe("parseFieldsJson", () => {
  it("accepts properties and required", () => {
    const parsed = parseFieldsJson('{"properties": {"slot": {"type": "string"}}, "required": ["slot"]}');
    expect(parsed).toEqual({ ok: true, value: { properties: { slot: { type: "string" } }, required: ["slot"] } });
  });

  it.each([
    ["{", /Not valid JSON/],
    ["[]", /Expected an object/],
    ['{"properties": [], "required": []}', /'properties' must be an object/],
    ['{"properties": {"a": "string"}}', /Field 'a' must be an object/],
    ['{"required": "a"}', /'required' must be a list/],
    ['{"properties": {}, "extra": 1}', /not 'extra'/],
  ])("rejects %s", (text, message) => {
    const parsed = parseFieldsJson(text);
    expect(parsed.ok).toBe(false);
    if (!parsed.ok) expect(parsed.error).toMatch(message);
  });
});

describe("parseAction", () => {
  it("accepts an object with a type and keeps its other keys", () => {
    expect(parseAction('{"type": "function", "handler": "x"}')).toEqual({
      ok: true,
      value: { type: "function", handler: "x" },
    });
  });

  it.each(["nope", "[1]", "{}", '{"type": ""}', '{"type": 3}'])("rejects %s", (text) => {
    expect(parseAction(text).ok).toBe(false);
  });
});
