import { z } from "zod";

// Mirrors backend/agent_builder/schema.py. Every object is loose, so keys the
// editor does not model survive a load/save round trip (ADR 0002). No defaults
// either: filling in a missing field would change the file on save. The
// backend validator (ADR 0004) is the authority on what can run; this only
// checks the shape the editor relies on.

// Opaque to the editor: passed to Pipecat Flows as they are.
export const Action = z.record(z.string(), z.unknown());

export const TaskMessage = z.looseObject({
  role: z.string(),
  content: z.string(),
});

export const Edge = z.looseObject({
  function: z.string(),
  description: z.string(),
  target: z.string(),
  properties: z.record(z.string(), z.unknown()).optional(),
  required: z.array(z.string()).optional(),
});

export const Position = z.looseObject({ x: z.number(), y: z.number() });

export const Node = z.looseObject({
  name: z.string(),
  task_messages: z.array(TaskMessage).optional(),
  role_message: z.string().nullable().optional(),
  edges: z.array(Edge).optional(),
  pre_actions: z.array(Action).optional(),
  post_actions: z.array(Action).optional(),
  end: z.boolean().optional(),
  // Editor-only canvas position; the backend ignores it.
  ui: Position.optional(),
});

export const Agent = z.looseObject({
  name: z.string(),
  initial_node: z.string(),
  nodes: z.array(Node),
  persona: z.string().optional(),
  voice_id: z.string().optional(),
  model: z.string().optional(),
});

export type Action = z.infer<typeof Action>;
export type TaskMessage = z.infer<typeof TaskMessage>;
export type Edge = z.infer<typeof Edge>;
export type Position = z.infer<typeof Position>;
export type Node = z.infer<typeof Node>;
export type Agent = z.infer<typeof Agent>;
