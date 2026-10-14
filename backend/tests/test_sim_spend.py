"""The spend log (#27): the real model client writes it, the runner's cache adds
nothing, and `make spend` adds it up. No model calls: the client gets a fake OpenAI."""

import asyncio
import json
from datetime import date
from types import SimpleNamespace

import httpx
import pytest

import simfakes
from simfakes import TEST, caller, say, verdict
from sim import config, spend
from sim.__main__ import main
from sim.llm import Completion, Models, OpenAIChat, Usage
from sim.runner import run_test


class FakeOpenAI:
    """Stands in for AsyncOpenAI: answers `chat.completions.create` from a scripted
    model, shaped like the SDK's response (cached tokens in `prompt_tokens_details`)."""

    def __init__(self, model, details=True):
        self.model = model
        self.details = details
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    async def create(self, **request):
        c = await self.model.complete(request)
        calls = [SimpleNamespace(id=t.id, function=SimpleNamespace(name=t.name, arguments=t.arguments)) for t in c.tool_calls]
        usage = SimpleNamespace(prompt_tokens=c.input_tokens, completion_tokens=c.output_tokens)
        if self.details:
            usage.prompt_tokens_details = SimpleNamespace(cached_tokens=c.cached_tokens)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=c.text, tool_calls=calls or None))],
            model=c.model,
            usage=usage,
        )


def chat(answers, ledger, source="test", **fake):
    return OpenAIChat(source, client=FakeOpenAI(simfakes.Scripted(*answers), **fake), ledger=ledger)


def entry(day, source, model="gpt-4o-2024-08-06", input=0, cached=0, output=0):
    return {"time": f"{day}T10:00:00+02:00", "source": source, "model": model, "input": input, "cached": cached, "output": output}


# ---- the model client ------------------------------------------------------------------------
def test_every_request_adds_a_line_with_cached_tokens(tmp_path):
    ledger = tmp_path / ".spend" / "ledger.jsonl"
    answer = Completion(text="Hi.", model="gpt-4o-2024-08-06", input_tokens=3000, cached_tokens=2048, output_tokens=12)
    completion = asyncio.run(chat([answer], ledger, source="eval").complete({"model": "gpt-4o", "messages": []}))
    assert completion.cached_tokens == 2048 and completion.input_tokens == 3000
    [line] = spend.load(ledger)
    assert {k: v for k, v in line.items() if k != "time"} == {
        "source": "eval",
        "model": "gpt-4o-2024-08-06",
        "input": 3000,
        "cached": 2048,
        "output": 12,
    }
    assert date.fromisoformat(line["time"][:10]) == date.today()


def test_a_response_without_cache_details_counts_none_cached(tmp_path):
    ledger = tmp_path / "ledger.jsonl"
    answer = Completion(text="Hi.", model="gpt-4o", input_tokens=500, output_tokens=5)
    completion = asyncio.run(chat([answer], ledger, details=False).complete({}))
    assert completion.cached_tokens == 0 and spend.load(ledger)[0]["cached"] == 0


def test_a_failed_request_adds_nothing(tmp_path):
    import openai

    ledger = tmp_path / "ledger.jsonl"
    down = openai.APIConnectionError(request=httpx.Request("POST", "https://api.openai.com/v1/chat/completions"))
    with pytest.raises(Exception, match="APIConnectionError"):
        asyncio.run(chat([down], ledger).complete({}))
    assert not ledger.exists()


def test_no_ledger_logs_nothing(tmp_path):
    asyncio.run(chat([Completion(text="Hi.", model="gpt-4o")], None).complete({}))
    assert list(tmp_path.iterdir()) == []


# ---- the runner (acceptance: a run adds its requests, a cached rerun adds none) ---------------
def test_a_run_logs_its_requests_and_a_cached_rerun_adds_none(example, tmp_path):
    ledger = tmp_path / "ledger.jsonl"
    test = {**TEST, "checks": [{"type": "judge", "rule": "Greets the caller."}]}

    def eval_models(agent=(), caller_=(), judge=()):
        return Models(agent=chat(agent, ledger, "eval"), caller=chat(caller_, ledger, "eval"), judge=chat(judge, ledger, "eval"))

    first = asyncio.run(
        run_test(example, test, eval_models([say("Hello, how can I help?")], [caller("Bye.", hang_up=True)], [verdict(True)]), cache_dir=tmp_path / "cache")
    )
    assert first["status"] == "pass" and not first["cached"]
    lines = spend.load(ledger)
    assert [line["model"] for line in lines] == ["fake-agent", "fake-caller", "fake-judge"]
    assert {line["source"] for line in lines} == {"eval"}

    second = asyncio.run(run_test(example, test, eval_models(), cache_dir=tmp_path / "cache"))
    assert second["cached"] and len(spend.load(ledger)) == 3


# ---- usage and prices ------------------------------------------------------------------------
def test_cached_input_is_priced_at_the_cached_rate():
    # gpt-4o: $2.50 input, $1.25 cached, $10 output per million.
    assert config.cost("gpt-4o-2024-08-06", 10_000, 8_000, 500) == pytest.approx(0.02)
    assert config.cost("gpt-4o-2024-08-06", 10_000, 0, 500) == pytest.approx(0.03)
    assert config.cost("gpt-4.1-mini-2025-04-14", 1_000_000, 1_000_000, 0) == pytest.approx(0.10)
    assert config.cost("claude-something", 1, 0, 1) is None


def test_usage_adds_cached_tokens_and_reads_results_cached_before_the_log():
    usage = Usage()
    usage.add(Completion(text="", model="gpt-4o", input_tokens=10_000, cached_tokens=8_000, output_tokens=500))
    usage.merge({"gpt-4o": {"requests": 1, "input": 10_000, "output": 500}})  # no "cached" key
    assert usage.data["gpt-4o"] == {"requests": 2, "input": 20_000, "cached": 8_000, "output": 1_000}
    assert usage.cost() == pytest.approx(0.05)
    assert Usage({"gpt-4o": {"requests": 1, "input": 5, "output": 1}}).data["gpt-4o"]["cached"] == 0


# ---- make spend ------------------------------------------------------------------------------
def test_totals_by_day_and_source_since_a_date():
    entries = [
        entry("2026-10-14", "test", input=1_000_000),  # $2.50
        entry("2026-10-15", "eval", input=1_000_000, cached=1_000_000),  # $1.25
        entry("2026-10-15", "eval", output=100_000),  # $1.00
        entry("2026-10-15", "test", model="mystery-model", input=999),
    ]
    t = spend.totals(entries)
    assert t["first_day"] == "2026-10-14"
    assert list(t["rows"]) == [("2026-10-14", "test"), ("2026-10-15", "eval"), ("2026-10-15", "test")]
    assert t["rows"][("2026-10-15", "eval")]["usd"] == pytest.approx(2.25)
    assert t["rows"][("2026-10-15", "eval")]["requests"] == 2
    assert t["by_source"]["test"]["usd"] == pytest.approx(2.50) and t["by_source"]["test"]["requests"] == 2
    assert t["total"]["usd"] == pytest.approx(4.75) and t["unpriced"] == ["mystery-model"]

    since = spend.totals(entries, date(2026, 10, 15))
    assert since["total"]["usd"] == pytest.approx(2.25) and since["first_day"] == "2026-10-14"


def test_the_report_says_what_it_is(tmp_path):
    path = tmp_path / "ledger.jsonl"
    entries = [entry("2026-10-14", "test", input=1_000_000), entry("2026-10-15", "eval", output=100_000)]
    text = spend.report(entries, date(2026, 10, 1), path)
    assert "list prices" in text and "starts on 2026-10-14" in text and "dashboards" in text
    assert "2026-10-15  eval" in text and "Total since 2026-10-01: $3.50 (2 requests)" in text
    assert "No model requests logged yet" in spend.report([], None, path)
    assert "No requests since 2026-11-01" in spend.report(entries, date(2026, 11, 1), path)


def test_load_skips_a_line_cut_short(tmp_path):
    path = tmp_path / "ledger.jsonl"
    path.write_text(json.dumps(entry("2026-10-15", "eval")) + "\n" + '{"time": "2026-10-15T1' + "\n")
    assert len(spend.load(path)) == 1
    assert spend.load(tmp_path / "missing.jsonl") == []


def test_the_spend_command(tmp_path, monkeypatch, capsys):
    path = tmp_path / "ledger.jsonl"
    path.write_text("".join(json.dumps(e) + "\n" for e in [entry("2026-10-14", "test", input=1_000_000), entry("2026-10-15", "eval", input=1_000_000)]))
    monkeypatch.setattr(config, "SPEND_LEDGER", path)
    assert main(["spend", "--since", "2026-10-15"]) == 0
    out = capsys.readouterr().out
    assert "Total since 2026-10-15: $2.50 (1 request)" in out and "2026-10-14  test" not in out
