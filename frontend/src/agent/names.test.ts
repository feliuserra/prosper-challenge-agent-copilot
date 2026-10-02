import { describe, expect, it } from "vitest";

import { agentIdFor, FUNCTION_NAME_RE, placeholderFunctionName, sanitizeFunctionName } from "./names";

describe("placeholderFunctionName", () => {
  it("is go_to_<target>", () => {
    expect(placeholderFunctionName("confirm", [])).toBe("go_to_confirm");
  });

  it("sanitises targets that are not valid function names", () => {
    expect(placeholderFunctionName("Offer times!", [])).toBe("go_to_Offer_times");
    expect(placeholderFunctionName("día 2", [])).toBe("go_to_d_a_2");
  });

  it("suffixes _2, _3, ... when the name is taken in the node", () => {
    expect(placeholderFunctionName("confirm", ["go_to_confirm"])).toBe("go_to_confirm_2");
    expect(placeholderFunctionName("confirm", ["go_to_confirm", "go_to_confirm_2"])).toBe("go_to_confirm_3");
  });

  it("stays within 64 characters, suffix included", () => {
    const target = "x".repeat(100);
    const first = placeholderFunctionName(target, []);
    const second = placeholderFunctionName(target, [first]);
    expect(first).toHaveLength(64);
    expect(second).toHaveLength(64);
    expect(second.endsWith("_2")).toBe(true);
    expect(FUNCTION_NAME_RE.test(second)).toBe(true);
  });
});

describe("sanitizeFunctionName", () => {
  it("never returns an empty or invalid name", () => {
    for (const text of ["", "!!!", "  ", "a b", "ñ"]) {
      expect(FUNCTION_NAME_RE.test(sanitizeFunctionName(text))).toBe(true);
    }
  });
});

describe("agentIdFor", () => {
  it("slugs the name and avoids taken ids", () => {
    expect(agentIdFor("My Clinic Agent", [])).toBe("my-clinic-agent");
    expect(agentIdFor("My Clinic Agent", ["my-clinic-agent"])).toBe("my-clinic-agent_2");
    expect(agentIdFor("!!!", [])).toBe("agent");
  });

  it("matches the backend id pattern", () => {
    expect(agentIdFor("  -Weird__Name-- ", [])).toMatch(/^[a-z0-9][a-z0-9_-]{0,63}$/);
  });
});
