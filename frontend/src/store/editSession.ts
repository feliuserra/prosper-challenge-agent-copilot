import { useEffect, useRef } from "react";

import { useAgentStore } from "./agentStore";

// One undo step per editing session: typing in one field until it loses focus.
// Text fields write to the store on every keystroke (so the canvas and a test
// call always see the current text), which would otherwise be one history
// entry per keystroke. As with drags (canvas/changes.ts), the session's first
// write is recorded, so its "before" is the agent before the session, and
// history is paused after it until the session ends.

const history = () => useAgentStore.temporal.getState();

let session: object | null = null;
let paused = false;

export function beginEdit(owner: object) {
  endEdit(session);
  session = owner;
  paused = false;
}

/** Call after each write the session made. */
export function edited(owner: object) {
  if (session !== owner || paused || !history().isTracking) return;
  history().pause();
  paused = true;
}

/** Ends `owner`'s session. Resumes history only if this session paused it. */
export function endEdit(owner: object | null) {
  if (!owner || session !== owner) return;
  if (paused) history().resume();
  session = null;
  paused = false;
}

/** Focus and blur handlers for a field, plus `edited()` to call after each write. */
export function useEditSession() {
  const owner = useRef({}).current;
  // A field can unmount while focused (e.g. the selection changes).
  useEffect(() => () => endEdit(owner), [owner]);
  return {
    onFocus: () => beginEdit(owner),
    onBlur: () => endEdit(owner),
    edited: () => edited(owner),
  };
}
