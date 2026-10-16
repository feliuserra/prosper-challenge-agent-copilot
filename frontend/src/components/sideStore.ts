import { create } from "zustand";

// Which tab of the right-hand column is open (#31), in a module of its own so stores can
// open a tab (the Calls tab from the inbox, #32) without importing the column.

export type SideTab = "copilot" | "calls" | "call";

export const useSideStore = create<{ tab: SideTab | null }>(() => ({ tab: "copilot" }));

/** Open the column on a tab, or close it with null. */
export const setSideTab = (tab: SideTab | null) => useSideStore.setState({ tab });
