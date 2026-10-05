import { Agent } from "./agent/schema";

// Client for the agents API on the runner (backend/composer_api.py), reached
// through the Vite proxy.

export interface ValidationIssue {
  message: string;
  node: string | null;
  edge: string | null;
}

export interface AgentSummary {
  id: string;
  name: string | null;
}

async function request(path: string, init?: RequestInit): Promise<Response> {
  const res = await fetch(`/composer${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!res.ok && res.status !== 422) {
    throw new Error(`${init?.method ?? "GET"} /composer${path} failed: ${res.status} ${await res.text()}`);
  }
  return res;
}

export async function listAgents(): Promise<AgentSummary[]> {
  return (await (await request("/agents")).json()).agents;
}

/** Load an agent. Throws if the file does not have the shape the editor needs. */
export async function getAgent(id: string): Promise<Agent> {
  const data = await (await request(`/agents/${id}`)).json();
  const parsed = Agent.safeParse(data);
  if (!parsed.success) {
    throw new Error(`Agent '${id}' cannot be opened: ${parsed.error.issues[0]?.message}`);
  }
  // Keep the original object: it is what the parse checked, and its key order is
  // the file's, so saving it back produces the same JSON.
  return data as Agent;
}

/** Save an agent. Returns the validation errors when the backend rejects it (422). */
export async function saveAgent(id: string, agent: Agent): Promise<ValidationIssue[]> {
  const res = await request(`/agents/${id}`, { method: "PUT", body: JSON.stringify(agent) });
  return res.status === 422 ? (await res.json()).errors : [];
}

export async function validateAgent(agent: Agent): Promise<ValidationIssue[]> {
  return (await (await request("/validate", { method: "POST", body: JSON.stringify(agent) })).json()).errors;
}

export interface Voice {
  id: string;
  name: string;
  category: string | null;
}

/** The ElevenLabs account's voices, or an error saying why they could not be listed. */
export async function listVoices(): Promise<{ voices: Voice[]; error?: string }> {
  return (await request("/voices")).json();
}

export interface Health {
  ok: boolean;
  /** Names of the required keys missing from the backend's environment (never values). */
  missing_keys: string[];
}

/** Whether the backend has the keys a call needs. */
export async function getHealth(): Promise<Health> {
  return (await request("/health")).json();
}
