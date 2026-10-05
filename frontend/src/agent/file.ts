import { Agent } from "./schema";

// Agent JSON files for import and export. The file is the agent exactly as the
// editor holds it, `ui` positions included (the backend ignores them).

export type ParsedFile = { ok: true; agent: Agent } | { ok: false; error: string };

/** Read an imported file. Checks only the shape the editor needs, like opening a saved agent. */
export function parseAgentFile(text: string): ParsedFile {
  let data: unknown;
  try {
    data = JSON.parse(text);
  } catch (error) {
    return { ok: false, error: `not valid JSON (${(error as Error).message})` };
  }
  const parsed = Agent.safeParse(data);
  if (!parsed.success) {
    const issue = parsed.error.issues[0];
    const where = issue?.path.length ? `${issue.path.join(".")}: ` : "";
    return { ok: false, error: `not an agent (${where}${issue?.message})` };
  }
  // The original object, as api.getAgent does, so its key order is kept.
  return { ok: true, agent: data as Agent };
}

/** The text of an exported file: indented like the files the backend writes. */
export const agentFileText = (agent: Agent) => `${JSON.stringify(agent, null, 2)}\n`;
