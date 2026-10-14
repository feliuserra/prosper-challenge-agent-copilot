# Models on the company OpenAI key (#26)

Checked on 2026-10-12, before pinning the text runner's models (ADR 0010). The list comes from `GET /v1/models`; the limits come from the `x-ratelimit-limit-*` headers of one tiny completion per model, timed from this machine.

## What the key offers

148 models. The chat models: `gpt-3.5-turbo`, `gpt-4`, `gpt-4-turbo`, `gpt-4o` (2024-05-13, 2024-08-06, 2024-11-20), `gpt-4o-mini`, `gpt-4.1`, `gpt-4.1-mini`, `gpt-4.1-nano`, the `gpt-5` family up to `gpt-5.5` (with `-mini`, `-nano`, `-pro` and `-chat-latest` variants, dated), `gpt-6-*` previews, and the `o1`, `o3`, `o4-mini` reasoning models.

| Model asked for | Version that answered | Requests / min | Tokens / min | One short reply |
| --- | --- | --- | --- | --- |
| `gpt-4o` | `gpt-4o-2024-08-06` | 10,000 | 30M | 1.9 s |
| `gpt-4o-mini` | `gpt-4o-mini-2024-07-18` | 30,000 | 150M | 0.6 s |
| `gpt-4.1` | `gpt-4.1-2025-04-14` | 100,000 | 200M | 1.3 s |
| `gpt-4.1-mini` | `gpt-4.1-mini-2025-04-14` | 30,000 | 150M | 0.5 s |
| `gpt-4.1-nano` | `gpt-4.1-nano-2025-04-14` | 30,000 | 150M | 0.5 s |
| `gpt-5.4-mini` (reasoning off) | `gpt-5.4-mini-2026-03-17` | 30,000 | 180M | 0.6 s |
| `gpt-5.4-nano` (reasoning off) | `gpt-5.4-nano-2026-03-17` | 30,000 | 180M | 0.5 s |
| `gpt-5-mini` (minimal reasoning) | `gpt-5-mini-2025-08-07` | 30,000 | 180M | 0.6 s |

The limits are far above what a test suite needs (a 20-test suite is a few hundred requests), so the runner's cap of 16 requests in flight is for politeness, and rate-limit errors should only come from outages.

## What the runner uses (`backend/sim/config.py`)

- **Agent:** the agent's own `model` with no other parameters, exactly as `bot.py` sends it (OpenAI's defaults, so temperature 1). The example agent says `gpt-4o`, an alias that answered as `gpt-4o-2024-08-06` today. Every agent turn records the version that answered (`model` in the turn), so a silent alias move shows up in results. To pin the agent, put a dated version in the agent JSON; the live bot then uses it too.
- **Caller:** `gpt-4.1-mini-2025-04-14`. Small, fast, no reasoning tokens, and supports strict JSON output. The caller makes about half the requests of a call, so its latency adds directly to a test's time.
- **Judge:** `gpt-4.1-2025-04-14`, provisional. #27 calibrates the judge against about 30 hand labels and keeps the cheapest model that reaches 90% agreement (ADR 0011).

## Cost of a run

The first real run of the 3 example tests (`backend/sim/examples/scheduler-tests.json`) against the example agent: 3 of 3 passed in 24 s, about $0.22 at list prices (41 `gpt-4o` agent requests, 80k tokens in; 17 caller and 2 judge requests). Almost all of the cost is the agent model reading the history each turn. Prices are in `sim/config.py` (`PRICES`), so the CLI's estimate ignores cached-input discounts and is an upper bound.
