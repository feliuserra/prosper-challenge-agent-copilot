import { uniqueName } from "./names";
import type { Action, Edge } from "./schema";
import type { EdgePatch } from "../store/agentStore";

// Collected fields of an edge: the JSON-schema `properties` the LLM fills in when
// it takes the transition, plus `required`. These helpers return an EdgePatch for
// updateEdge. Each field's spec keeps keys the table does not show (e.g. `enum`).

export type FieldSpec = Record<string, unknown>;
export type Field = { name: string; spec: FieldSpec; required: boolean };
export type Parsed<T> = { ok: true; value: T } | { ok: false; error: string };

const isObject = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);

export function fieldsOf(edge: Edge): Field[] {
  const required = new Set(edge.required ?? []);
  return Object.entries(edge.properties ?? {}).map(([name, spec]) => ({
    name,
    spec: isObject(spec) ? spec : {},
    required: required.has(name),
  }));
}

/** The patch for a new set of properties; empty ones remove the keys from the edge. */
function patch(properties: Record<string, unknown>, required: string[]): EdgePatch {
  return {
    properties: Object.keys(properties).length ? properties : undefined,
    required: required.length ? required : undefined,
  };
}

export function addField(edge: Edge): EdgePatch {
  const properties = edge.properties ?? {};
  const name = uniqueName("field", Object.keys(properties));
  return patch({ ...properties, [name]: { type: "string" } }, edge.required ?? []);
}

export function removeField(edge: Edge, name: string): EdgePatch {
  const { [name]: _removed, ...properties } = edge.properties ?? {};
  return patch(
    properties,
    (edge.required ?? []).filter((r) => r !== name),
  );
}

/** Why `draft` cannot be the new name of field `current`, or null if it can. */
export function fieldNameError(edge: Edge, current: string, draft: string): string | null {
  const name = draft.trim();
  if (!name) return "Field name cannot be empty.";
  if (name !== current && name in (edge.properties ?? {})) return `There is already a field '${name}'.`;
  return null;
}

/** Rename a field in place (its position is kept) and in `required`. */
export function renameField(edge: Edge, current: string, draft: string): EdgePatch {
  const next = draft.trim();
  const properties = Object.fromEntries(
    Object.entries(edge.properties ?? {}).map(([name, spec]) => [name === current ? next : name, spec]),
  );
  return patch(
    properties,
    (edge.required ?? []).map((r) => (r === current ? next : r)),
  );
}

/** Change keys of one field's spec; `undefined` removes a key. */
export function updateFieldSpec(edge: Edge, name: string, change: FieldSpec): EdgePatch {
  const spec: FieldSpec = { ...fieldsOf(edge).find((f) => f.name === name)?.spec, ...change };
  for (const [key, value] of Object.entries(change)) if (value === undefined) delete spec[key];
  return patch({ ...edge.properties, [name]: spec }, edge.required ?? []);
}

/** Add `name` to `required` (at the end) or take it out; the rest keep their order. */
export function setRequired(edge: Edge, name: string, required: boolean): EdgePatch {
  const others = (edge.required ?? []).filter((r) => r !== name);
  return patch(edge.properties ?? {}, required ? [...others, name] : others);
}

/** What the "Edit as JSON" box shows for an edge's collected fields. */
export function fieldsJson(edge: Edge): { properties: Record<string, unknown>; required: string[] } {
  return { properties: edge.properties ?? {}, required: edge.required ?? [] };
}

/**
 * Parse the "Edit as JSON" box. Checks only the shape the editor relies on;
 * whether each field's `type` is valid is the backend validator's job (ADR 0004).
 */
export function parseFieldsJson(text: string): Parsed<EdgePatch> {
  let data: unknown;
  try {
    data = JSON.parse(text);
  } catch (error) {
    return { ok: false, error: `Not valid JSON: ${(error as Error).message}` };
  }
  if (!isObject(data)) return { ok: false, error: "Expected an object with 'properties' and 'required'." };
  const extra = Object.keys(data).filter((k) => k !== "properties" && k !== "required");
  if (extra.length) return { ok: false, error: `Only 'properties' and 'required' can be set here, not '${extra[0]}'.` };
  const properties = data.properties ?? {};
  if (!isObject(properties)) return { ok: false, error: "'properties' must be an object." };
  const notObject = Object.entries(properties).find(([, spec]) => !isObject(spec));
  if (notObject) return { ok: false, error: `Field '${notObject[0]}' must be an object, e.g. {"type": "string"}.` };
  const required = data.required ?? [];
  if (!Array.isArray(required) || !required.every((r) => typeof r === "string")) {
    return { ok: false, error: "'required' must be a list of field names." };
  }
  return { ok: true, value: patch(properties, required) };
}

/** Parse one action typed as JSON: an object with a non-empty string `type`. */
export function parseAction(text: string): Parsed<Action> {
  let data: unknown;
  try {
    data = JSON.parse(text);
  } catch (error) {
    return { ok: false, error: `Not valid JSON: ${(error as Error).message}` };
  }
  if (!isObject(data)) return { ok: false, error: "An action must be a JSON object." };
  if (typeof data.type !== "string" || !data.type.trim()) {
    return { ok: false, error: 'An action needs a "type", e.g. {"type": "end_conversation"}.' };
  }
  return { ok: true, value: data };
}
