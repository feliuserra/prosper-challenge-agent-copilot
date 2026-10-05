import { describe, expect, it } from "vitest";
import type { BotOutputData } from "@pipecat-ai/client-js";

import { addBotOutput, addUserTranscript, parseTransition, turnText, type Turn } from "./transcript";

const user = (turns: Turn[], text: string, final = true) => addUserTranscript(turns, { text, final });
const texts = (turns: Turn[]) => turns.map((t) => `${t.role}: ${turnText(t)}`);

// A sentence queued for speech, then its spoken progress (the 2.0 protocol).
const queued = (id: number, text: string): BotOutputData => ({
  text,
  aggregated_by: "sentence",
  segment_id: id,
  will_be_spoken: true,
  spoken_status: "new",
  spoken_progress: { accumulated_text: "", remaining_text: text },
});
const spoken = (id: number, text: string, said: string): BotOutputData => ({
  text,
  aggregated_by: "sentence",
  segment_id: id,
  will_be_spoken: true,
  spoken_status: said === text ? "completed" : "in-progress",
  spoken_progress: { accumulated_text: said, remaining_text: text.slice(said.length) },
});

describe("addUserTranscript", () => {
  it("replaces the partial and joins finals in one turn", () => {
    let turns = user([], "I want", false);
    expect(texts(turns)).toEqual(["user: I want"]);
    turns = user(turns, "I want to book");
    turns = user(turns, "an appointment", false);
    expect(texts(turns)).toEqual(["user: I want to book an appointment"]);
    expect(turns[0]).toMatchObject({ text: "I want to book", partial: "an appointment" });
    turns = user(turns, "an appointment.");
    expect(turns).toEqual([{ role: "user", text: "I want to book an appointment.", partial: "" }]);
  });

  it("starts a new turn after the bot", () => {
    let turns = user([], "Hi");
    turns = addBotOutput(turns, spoken(1, "Hello!", "Hello!"));
    turns = user(turns, "Book please");
    expect(texts(turns)).toEqual(["user: Hi", "bot: Hello!", "user: Book please"]);
  });
});

describe("addBotOutput", () => {
  it("shows only the spoken part of each sentence", () => {
    let turns = addBotOutput([], queued(1, "Hello there."));
    expect(texts(turns)).toEqual(["bot: "]);
    turns = addBotOutput(turns, spoken(1, "Hello there.", "Hello"));
    expect(texts(turns)).toEqual(["bot: Hello"]);
    turns = addBotOutput(turns, queued(2, "How can I help?"));
    turns = addBotOutput(turns, spoken(1, "Hello there.", "Hello there."));
    turns = addBotOutput(turns, spoken(2, "How can I help?", "How can I help?"));
    expect(texts(turns)).toEqual(["bot: Hello there. How can I help?"]);
  });

  it("keeps a sentence cut off by the user where it stopped", () => {
    let turns = addBotOutput([], spoken(1, "Your appointment is on Monday.", "Your appointment"));
    turns = user(turns, "Wait");
    turns = addBotOutput(turns, queued(2, "Sure."));
    expect(texts(turns)).toEqual(["bot: Your appointment", "user: Wait", "bot: "]);
  });

  it("updates a sentence in an earlier turn after the user talked over it", () => {
    let turns = addBotOutput([], spoken(1, "One moment please.", "One"));
    turns = user(turns, "Okay", false);
    turns = addBotOutput(turns, spoken(1, "One moment please.", "One moment"));
    expect(texts(turns)).toEqual(["bot: One moment", "user: Okay"]);
  });

  it("uses the whole text for output that is not spoken", () => {
    const turns = addBotOutput([], { text: "(thinking)", aggregated_by: "sentence", will_be_spoken: false });
    expect(texts(turns)).toEqual(["bot: (thinking)"]);
  });

  it("ignores word and token messages", () => {
    const turns = addBotOutput([], { text: "Hello", aggregated_by: "word", segment_id: 3 });
    expect(turns).toEqual([]);
  });
});

describe("parseTransition", () => {
  it("reads the edge handler's message", () => {
    const data = { type: "transition", from: "greeting", function: "choose_intent", to: "details", args: { intent: "book" } };
    expect(parseTransition(data)).toEqual({
      role: "transition",
      from: "greeting",
      function: "choose_intent",
      to: "details",
      args: { intent: "book" },
    });
  });

  it("ignores other server messages and tolerates missing args", () => {
    expect(parseTransition({ type: "something-else" })).toBeNull();
    expect(parseTransition({ type: "transition", from: "a" })).toBeNull();
    expect(parseTransition("transition")).toBeNull();
    expect(parseTransition({ type: "transition", from: "a", function: "f", to: "b" })?.args).toEqual({});
  });

  it("starts a new user turn after a transition", () => {
    let turns: Turn[] = addUserTranscript([], { text: "Book, please.", final: true });
    turns = [...turns, parseTransition({ type: "transition", from: "a", function: "f", to: "b", args: {} })!];
    turns = addUserTranscript(turns, { text: "Tuesday", final: true });
    expect(turns.map((t) => t.role)).toEqual(["user", "transition", "user"]);
    expect(turnText(turns[1])).toBe("f -> b");
  });
});
