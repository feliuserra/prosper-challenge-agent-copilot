#
# The spend log (#27). The company keys cannot read usage or billing
# (docs/notes/models.md), so we keep our own estimate: the model client (llm.py)
# appends one line per request it makes to backend/.spend/ledger.jsonl (gitignored),
# and `make spend` adds the lines up at list prices (config.PRICES).
#
# A line: time (local, with its offset), source, model (the dated version that
# answered), input (the whole prompt, cached tokens included, as the API counts
# them), cached and output tokens. Sources: `test` (python -m sim run), `eval`
# (make eval), `replay`, `copilot` (#29 on); #28 adds `call` for live calls.
#
# A result served from the runner's cache makes no request, so it adds nothing. A
# request that failed adds nothing either: OpenAI does not bill those. Spend before
# the log started (2026-10-15) is not in it, and billed amounts are only in
# Prosper's OpenAI and ElevenLabs dashboards.
#

import json
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

from . import config


def log(path: Path, source: str, completion) -> None:
    """Append one request to the log. One short line per write, so lines from
    concurrent processes do not interleave."""
    entry = {
        "time": datetime.now().astimezone().isoformat(timespec="seconds"),
        "source": source,
        "model": completion.model or "unknown",
        "input": completion.input_tokens,
        "cached": completion.cached_tokens,
        "output": completion.output_tokens,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(entry) + "\n")


def load(path: Path) -> list[dict]:
    """Every line of the log, skipping any that is not a JSON object (a line cut short
    by a crash)."""
    if not path.is_file():
        return []
    entries = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(entry, dict) and isinstance(entry.get("time"), str):
            entries.append(entry)
    return entries


def totals(entries: list[dict], since: date | None = None) -> dict:
    """Requests, tokens and estimated USD per (day, source), per source and overall,
    from `since` on. Tokens of models with no price are counted but not priced, and
    listed in `unpriced`."""
    rows: dict[tuple[str, str], dict] = defaultdict(_empty)
    unpriced: set[str] = set()
    for entry in entries:
        day = entry["time"][:10]
        if since and day < since.isoformat():
            continue
        row = rows[(day, entry.get("source", "unknown"))]
        tokens = [entry.get(key, 0) for key in ("input", "cached", "output")]
        usd = config.cost(entry.get("model", "unknown"), *tokens)
        if usd is None:
            unpriced.add(entry.get("model", "unknown"))
        row["requests"] += 1
        for key, n in zip(("input", "cached", "output"), tokens):
            row[key] += n
        row["usd"] += usd or 0.0

    by_source: dict[str, dict] = defaultdict(_empty)
    total = _empty()
    for (_, source), row in rows.items():
        for key in total:
            by_source[source][key] += row[key]
            total[key] += row[key]
    return {
        "first_day": min((e["time"][:10] for e in entries), default=None),
        "rows": dict(sorted(rows.items())),
        "by_source": dict(sorted(by_source.items())),
        "total": total,
        "unpriced": sorted(unpriced),
    }


def report(entries: list[dict], since: date | None = None, path: Path = config.SPEND_LEDGER) -> str:
    """What `make spend` prints."""
    if not entries:
        return f"No model requests logged yet ({path})."
    t = totals(entries, since)
    lines = [
        f"Estimated model spend at list prices (sim/config.py), from the spend log ({path}).",
        f"The log starts on {t['first_day']}: earlier requests are not in it. "
        "Billed amounts are only in Prosper's OpenAI and ElevenLabs dashboards.",
        "",
    ]
    if not t["rows"]:
        return "\n".join(lines + [f"No requests since {since}."])

    table = [("DAY", "SOURCE", "REQUESTS", "INPUT", "CACHED", "OUTPUT", "USD")]
    table += [(day, source, *_cells(row)) for (day, source), row in t["rows"].items()]
    widths = [max(len(row[i]) for row in table) for i in range(len(table[0]))]
    right = {2, 3, 4, 5, 6}  # numbers line up on the right
    for row in table:
        lines.append("  ".join(c.rjust(w) if i in right else c.ljust(w) for i, (c, w) in enumerate(zip(row, widths))).rstrip())

    lines += ["", "By source:"]
    name_width = max(len(s) for s in t["by_source"])
    lines += [f"  {source.ljust(name_width)}  {_usd(row['usd'])}  ({_requests(row['requests'])})" for source, row in t["by_source"].items()]
    lines += ["", f"Total {f'since {since}' if since else 'in the log'}: {_usd(t['total']['usd'])} ({_requests(t['total']['requests'])})"]
    if t["unpriced"]:
        lines.append(f"Not priced (no entry in sim/config.py PRICES), so missing from the dollars: {', '.join(t['unpriced'])}")
    return "\n".join(lines)


def _empty() -> dict:
    return {"requests": 0, "input": 0, "cached": 0, "output": 0, "usd": 0.0}


def _cells(row: dict) -> tuple[str, ...]:
    return (f"{row['requests']:,}", f"{row['input']:,}", f"{row['cached']:,}", f"{row['output']:,}", _usd(row["usd"]))


def _requests(n: int) -> str:
    return f"{n:,} request{'' if n == 1 else 's'}"


def _usd(amount: float) -> str:
    return f"${amount:,.2f}" if amount >= 0.01 or amount == 0 else f"${amount:.4f}"
