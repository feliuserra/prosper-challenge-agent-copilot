import { useEffect, useState } from "react";

import { listVoices, type Voice } from "../api";
import { DEFAULT_MODEL, DEFAULT_VOICE_ID, MODELS } from "../agent/options";
import type { Agent } from "../agent/schema";
import { useAgentStore } from "../store/agentStore";
import { ChoiceWithCustom, Field, LiveText } from "./controls";

const store = () => useAgentStore.getState();

// Fetched once per page load: the list only changes when the account's voices do.
let voicesRequest: ReturnType<typeof listVoices> | null = null;

function useVoices() {
  const [state, setState] = useState<{ voices: Voice[]; error?: string } | null>(null);
  useEffect(() => {
    voicesRequest ??= listVoices().catch((error) => ({ voices: [], error: String(error) }));
    void voicesRequest.then(setState);
  }, []);
  return state;
}

/** Shown when nothing is selected: the agent's own settings. */
export function AgentPanel({ agent }: { agent: Agent }) {
  const voices = useVoices();
  // The backend uses these defaults when the agent leaves the fields out.
  const voiceId = agent.voice_id ?? DEFAULT_VOICE_ID;
  const model = agent.model ?? DEFAULT_MODEL;
  const voiceListed = voices?.voices.some((v) => v.id === voiceId);

  const voiceOptions = [...(voices?.voices ?? [])]
    .sort((a, b) => a.name.localeCompare(b.name))
    .map((v) => ({ value: v.id, label: v.category ? `${v.name} (${v.category})` : v.name }));

  return (
    <>
      <h2>Agent</h2>
      <Field label="Name">
        <LiveText label="Agent name" value={agent.name} onChange={(name) => store().updateAgent({ name })} />
      </Field>
      <Field label="Persona" hint="The system prompt for every node, unless a node sets its own role.">
        <LiveText
          label="Persona"
          rows={6}
          value={agent.persona ?? ""}
          onChange={(persona) => store().updateAgent({ persona: persona || undefined })}
        />
      </Field>
      <Field
        label="Voice"
        error={
          voices && voices.voices.length > 0 && !voiceListed
            ? "Not one of your ElevenLabs voices. It may be an old ID that ElevenLabs reroutes, or a typo, which gives a silent bot."
            : null
        }
        hint={
          (voices?.error || agent.voice_id === undefined) && (
            <>
              {voices?.error && (
                <div>
                  Your voices could not be listed, so type a voice ID (ElevenLabs, Voices, "Copy voice ID").{" "}
                  {voices.error}
                </div>
              )}
              {agent.voice_id === undefined && <div>Not set: the backend default is used.</div>}
            </>
          )
        }
      >
        {!voices ? (
          <div className="muted">Loading voices…</div>
        ) : !voices.voices.length ? (
          <LiveText label="Voice ID" value={voiceId} onChange={(voice_id) => store().updateAgent({ voice_id })} />
        ) : (
          <ChoiceWithCustom
            label="Voice"
            value={voiceId}
            options={voiceOptions}
            customLabel="Custom voice ID…"
            onChange={(voice_id) => store().updateAgent({ voice_id })}
          />
        )}
      </Field>
      <Field label="Model" hint={agent.model === undefined ? "Not set: the backend default is used." : undefined}>
        <ChoiceWithCustom
          label="Model"
          value={model}
          options={MODELS.map((m) => ({ value: m, label: m }))}
          customLabel="Custom model…"
          onChange={(value) => store().updateAgent({ model: value })}
        />
      </Field>
      <Field label="Start node" hint="The conversation begins here.">
        <select
          aria-label="Start node"
          value={agent.initial_node}
          onChange={(event) => store().setInitialNode(event.target.value)}
        >
          {/* A start node that does not exist (hand-edited file) still shows. */}
          {!agent.nodes.some((n) => n.name === agent.initial_node) && (
            <option value={agent.initial_node}>{agent.initial_node} (missing)</option>
          )}
          {agent.nodes.map((n) => (
            <option key={n.name} value={n.name}>
              {n.name}
            </option>
          ))}
        </select>
      </Field>
    </>
  );
}
