// Naming rules shared by the store operations.

// What the LLM APIs accept as a tool name (same rule as the backend validator).
export const FUNCTION_NAME_RE = /^[a-zA-Z0-9_-]{1,64}$/;
const MAX_FUNCTION_NAME = 64;

/** Turn any text into a valid function name: invalid characters become "_". */
export function sanitizeFunctionName(text: string): string {
  const name = text.replace(/[^a-zA-Z0-9_-]+/g, "_").replace(/^_+|_+$/g, "");
  return (name || "go").slice(0, MAX_FUNCTION_NAME);
}

/** `base`, or `base_2`, `base_3`, ... whichever is not taken. Stays within 64 chars. */
export function uniqueName(base: string, taken: Iterable<string>, maxLength = Infinity): string {
  const used = new Set(taken);
  if (!used.has(base)) return base;
  for (let i = 2; ; i++) {
    const suffix = `_${i}`;
    const name = base.slice(0, maxLength - suffix.length) + suffix;
    if (!used.has(name)) return name;
  }
}

/** Placeholder function name for a new edge: go_to_<target>, unique within the node. */
export function placeholderFunctionName(target: string, taken: Iterable<string>): string {
  return uniqueName(sanitizeFunctionName(`go_to_${target}`), taken, MAX_FUNCTION_NAME);
}

/** File id for a new agent: a lowercase slug the backend accepts, unique among `taken`. */
export function agentIdFor(name: string, taken: Iterable<string>): string {
  const slug =
    name
      .toLowerCase()
      .replace(/[^a-z0-9_-]+/g, "-")
      .replace(/^[-_]+|-+$/g, "")
      .slice(0, 60) || "agent";
  return uniqueName(slug, taken, 64);
}

/** Why `draft` cannot be the new name of node `current`, or null if it can (as renameNode checks). */
export function nodeNameError(nodeNames: string[], current: string, draft: string): string | null {
  const name = draft.trim();
  if (!name) return "Node name cannot be empty.";
  if (name !== current && nodeNames.includes(name)) return `A node called '${name}' already exists.`;
  return null;
}

/** Why `draft` cannot be the function name of an edge, or null if it can. */
export function functionNameError(siblingFunctions: string[], current: string, draft: string): string | null {
  if (!FUNCTION_NAME_RE.test(draft)) return "Use 1 to 64 letters, digits, '_' or '-' (no spaces).";
  if (draft !== current && siblingFunctions.includes(draft)) {
    return `'${draft}' is already used by another edge of this node.`;
  }
  return null;
}
