// Values the side panel offers. Defaults mirror backend/agent_builder/schema.py:
// the backend uses them when the agent leaves the field out.

export const DEFAULT_VOICE_ID = "21m00Tcm4TlvDq8ikWAM";
export const DEFAULT_MODEL = "gpt-4o";

/** OpenAI chat models offered in the model picker. Any other id can be typed in. */
export const MODELS = ["gpt-4o", "gpt-4o-mini", "gpt-4.1", "gpt-4.1-mini"];

/** JSON-schema types the backend accepts for a collected field (validation.py). */
export const FIELD_TYPES = ["string", "number", "integer", "boolean", "array", "object"];

/** Roles offered for a task message. Pipecat Flows passes messages to the LLM as they are. */
export const TASK_ROLES = ["developer", "system"];
