import { useEffect, useId, useState, type ReactNode } from "react";

import type { Parsed } from "../agent/fields";
import { useEditSession } from "../store/editSession";

// Form controls for the side panel. Text is written to the store as it is typed
// (one undo step per focused field, see editSession.ts). Names are identifiers,
// so they are written only when the field is left, and only if valid. JSON is
// written only when it parses.

export function Field(props: { label: string; hint?: ReactNode; error?: string | null; children: ReactNode }) {
  return (
    <div className="field">
      <div className="field-label">{props.label}</div>
      {props.children}
      {props.error && <div className="field-error">{props.error}</div>}
      {props.hint && <div className="hint">{props.hint}</div>}
    </div>
  );
}

type TextProps = {
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  rows?: number;
  label?: string;
};

/** A text input (or textarea with `rows`) that writes on every keystroke. */
export function LiveText({ value, onChange, placeholder, rows, label }: TextProps) {
  const session = useEditSession();
  const props = {
    value,
    placeholder,
    "aria-label": label,
    onFocus: session.onFocus,
    onBlur: session.onBlur,
    onChange: (event: { target: { value: string } }) => {
      onChange(event.target.value);
      session.edited();
    },
  };
  return rows ? <textarea rows={rows} {...props} /> : <input type="text" {...props} />;
}

type NameProps = {
  value: string;
  /** Why a draft is not acceptable, or null. Shown while typing. */
  check: (draft: string) => string | null;
  /** Write the draft; called on blur or Enter when it is valid and changed. */
  commit: (draft: string) => void;
  label?: string;
  className?: string;
};

/**
 * An identifier: shows problems while typing, writes on blur or Enter, and goes
 * back to the stored value if the draft is invalid. Escape cancels.
 */
export function NameInput({ value, check, commit, label, className }: NameProps) {
  const [draft, setDraft] = useState(value);
  const [focused, setFocused] = useState(false);
  // Follow the store (undo, a rename elsewhere) unless the user is typing.
  useEffect(() => {
    if (!focused) setDraft(value);
  }, [value, focused]);
  const error = draft === value ? null : check(draft);

  return (
    <>
      <input
        type="text"
        className={error ? `${className ?? ""} invalid` : className}
        value={draft}
        aria-label={label}
        aria-invalid={!!error}
        onFocus={() => setFocused(true)}
        onChange={(event) => setDraft(event.target.value)}
        onBlur={() => {
          setFocused(false);
          if (draft !== value && !check(draft)) commit(draft);
          else setDraft(value);
        }}
        onKeyDown={(event) => {
          if (event.key === "Enter") event.currentTarget.blur();
          if (event.key === "Escape") {
            setDraft(value);
            // Blur after the reset has rendered, so the blur sees the stored value.
            const input = event.currentTarget;
            requestAnimationFrame(() => input.blur());
          }
        }}
      />
      {error && <div className="field-error">{error}</div>}
    </>
  );
}

type JsonProps<T> = {
  value: unknown;
  parse: (text: string) => Parsed<T>;
  onValid: (value: T) => void;
  rows?: number;
  label?: string;
};

/**
 * Raw JSON. Valid text is written as it is typed; invalid text shows the parse
 * error and is never written, so the store keeps the last valid value.
 */
export function JsonField<T>({ value, parse, onValid, rows = 6, label }: JsonProps<T>) {
  const pretty = JSON.stringify(value, null, 2);
  const [text, setText] = useState(pretty);
  const [error, setError] = useState("");
  const [focused, setFocused] = useState(false);
  const session = useEditSession();
  const id = useId();
  // While focused the text is the user's; otherwise follow the store, except
  // that a draft with an error is kept until it is fixed or the value changes.
  useEffect(() => {
    if (focused) return;
    setText(pretty);
    setError("");
  }, [pretty]);

  return (
    <>
      <textarea
        id={id}
        className={error ? "json invalid" : "json"}
        rows={rows}
        value={text}
        aria-label={label}
        aria-invalid={!!error}
        spellCheck={false}
        onFocus={() => {
          setFocused(true);
          session.onFocus();
        }}
        onBlur={() => {
          setFocused(false);
          session.onBlur();
          if (!error) setText(pretty);
        }}
        onChange={(event) => {
          setText(event.target.value);
          const parsed = parse(event.target.value);
          if (!parsed.ok) return setError(parsed.error);
          setError("");
          onValid(parsed.value);
          session.edited();
        }}
      />
      {error && <div className="field-error">Not saved: {error}</div>}
    </>
  );
}

const CUSTOM = "__custom__";

type ChoiceProps = {
  value: string;
  options: { value: string; label: string }[];
  onChange: (value: string) => void;
  customLabel: string;
  label?: string;
};

/** A dropdown of known values plus "Custom…", which shows a text input. */
export function ChoiceWithCustom({ value, options, onChange, customLabel, label }: ChoiceProps) {
  const known = options.some((o) => o.value === value);
  const [custom, setCustom] = useState(!known);
  // Values outside the list (typed, or from the file) always show the text input.
  useEffect(() => {
    if (!known) setCustom(true);
  }, [known]);

  return (
    <>
      <select
        value={custom ? CUSTOM : value}
        aria-label={label}
        onChange={(event) => {
          if (event.target.value === CUSTOM) return setCustom(true);
          setCustom(false);
          onChange(event.target.value);
        }}
      >
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
        <option value={CUSTOM}>{customLabel}</option>
      </select>
      {custom && <LiveText value={value} onChange={onChange} label={`${label ?? ""} (custom)`} />}
    </>
  );
}
