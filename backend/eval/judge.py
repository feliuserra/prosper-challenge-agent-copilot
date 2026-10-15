#
# Judge calibration (#27, ADR 0011 point 5): a judge model graded against labels
# drafted by hand from real runs and reviewed by the user (judge-labels.json). Each
# label is one judge request on its transcript, with the rule as the suite writes it.
# A rule under 90% agreement is rewritten or turned into an exact check.
#
# Each label also keeps the verdict the suite's judge gave when the run happened
# (`judge`), so the current judge's agreement on real transcripts costs nothing.
#

import asyncio
import json
from pathlib import Path

from sim.checks import judge_rule
from sim.llm import ChatModel, Usage

LABELS = Path(__file__).parent / "judge-labels.json"
BAR = 0.9


def load(path: Path = LABELS) -> tuple[dict, list[dict]]:
    data = json.loads(path.read_text())
    return data["rules"], data["labels"]


async def grade(rules: dict, labels: list[dict], model: str, chat: ChatModel) -> tuple[list[dict], Usage]:
    """The model's verdict on every label, beside the label."""
    usage = Usage()

    async def one(label: dict) -> dict:
        result = await judge_rule(label["turns"], {"type": "judge", "rule": rules[label["rule"]]}, chat, usage, model=model)
        expected = label["label"] == "pass"
        return {
            "id": label["id"], "rule": label["rule"], "label": label["label"], "pass": result["pass"],
            "agree": result["pass"] == expected, "turn": result["turn"], "reason": result["detail"],
        }

    return list(await asyncio.gather(*(one(label) for label in labels))), usage


def agreement(rows: list[dict]) -> dict[str, tuple[int, int]]:
    """Per rule: (agreeing labels, labels)."""
    out: dict[str, tuple[int, int]] = {}
    for row in rows:
        agree, total = out.get(row["rule"], (0, 0))
        out[row["rule"]] = (agree + row["agree"], total + 1)
    return out


def report(rows: list[dict], model: str, usage: Usage) -> str:
    per_rule = agreement(rows)
    lines = [f"Judge {model} against {len(rows)} reviewed labels\n", "RULE            AGREE   RATE  >= 90%"]
    for rule, (agree, total) in per_rule.items():
        lines.append(f"{rule:15} {agree:2}/{total:<2}  {agree / total:5.0%}  {'yes' if agree / total >= BAR else 'NO'}")
    agree = sum(r["agree"] for r in rows)
    lines.append(f"\nOverall {agree}/{len(rows)}; every rule at 90% or more: {'yes' if passes(rows) else 'no'}")
    for row in rows:
        if not row["agree"]:
            lines.append(f"  {row['id']} {row['rule']}: labelled {row['label']}, judge said {'pass' if row['pass'] else 'fail'}: {row['reason']}")
    cost = usage.cost()
    lines.append(f"Estimated cost ${cost:.3f}" if cost is not None else "Cost unknown (a model has no price in sim/config.py)")
    return "\n".join(lines)


def passes(rows: list[dict]) -> bool:
    return all(agree / total >= BAR for agree, total in agreement(rows).values())
