"""Tests for the LLM adapter layer.

`violation_pack/llm.py` was previously covered by nothing at all, and the
failure it was hiding is worth recording here verbatim because it produced an
error message that named neither the cause nor the fix:

    Error executing tool enrich_violation_tool: model did not return valid
    JSON: Expecting value: line 1 column 1 (char 0)
    --- raw ---

DeepSeek's `deepseek-flash` is a reasoning model: its `reasoning_content` is
billed against the SAME `max_tokens` allowance as the answer. Against the real
CL-030 enrichment payload it spent all 8000 tokens thinking and returned
`content: ""` with `finish_reason: "length"` and HTTP 200 -- so the pipeline
reached `json.loads("")`.

Everything here is a pure function exercised with a fake `send` callable. No
network, no `httpx`, no event loop.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from violation_pack.llm import (
    DEFAULT_MAX_TOKENS,
    MAX_TOKENS_CEILING,
    Completion,
    LLMError,
    _anthropic_completion,
    _budget_error,
    _env_positive_int,
    _escalated,
    _json_within_budget,
    _openai_completion,
    _parse_json,
    _strip_code_fence,
    build_client,
    default_max_tokens,
)


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------

def reply(content: str, **kw) -> Completion:
    """A Completion with sensible defaults for the fields under test."""
    fields = {
        "finish_reason": "stop",
        "reasoning_chars": 0,
        "reasoning_tokens": None,
        "completion_tokens": None,
    }
    fields.update(kw)
    return Completion(content=content, **fields)


def reasoning_exhausted(reasoning_chars: int = 30_180, budget: int = 8000) -> Completion:
    """The exact shape DeepSeek returned for the failing nexus stage: HTTP 200,
    no content, all of the budget spent on reasoning."""
    return reply(
        "",
        finish_reason="length",
        reasoning_chars=reasoning_chars,
        reasoning_tokens=budget,
        completion_tokens=budget,
    )


class Recorder:
    """A `send` callable that records budgets and replays canned replies."""

    def __init__(self, *replies: Completion | Exception):
        self._replies = list(replies)
        self.budgets: list[int] = []

    def __call__(self, budget: int) -> Completion:
        self.budgets.append(budget)
        if not self._replies:
            raise AssertionError(f"send() called more than expected at budget={budget}")
        nxt = self._replies.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt


# ---------------------------------------------------------------------------
# Fences and parsing
# ---------------------------------------------------------------------------

def test_strip_code_fence_removes_json_fence():
    assert _strip_code_fence('```json\n{"a": 1}\n```') == '{"a": 1}'


def test_strip_code_fence_removes_bare_fence():
    assert _strip_code_fence('```\n{"a": 1}\n```') == '{"a": 1}'


def test_strip_code_fence_leaves_unfenced_text_alone():
    assert _strip_code_fence('  {"a": 1}  ') == '{"a": 1}'


def test_strip_code_fence_tolerates_an_unterminated_fence():
    """A truncated reply can lose its closing fence; keep the JSON and let the
    parser produce the real complaint."""
    assert _strip_code_fence('```json\n{"a": 1}') == '{"a": 1}'


def test_parse_json_accepts_a_fenced_object():
    assert _parse_json('```json\n{"a": 1}\n```') == {"a": 1}


def test_parse_json_rejects_non_object_json():
    with pytest.raises(LLMError) as excinfo:
        _parse_json("[1, 2, 3]")
    assert "non-object JSON" in str(excinfo.value)
    assert "list" in str(excinfo.value)


def test_parse_json_error_includes_the_raw_text_for_diagnosis():
    with pytest.raises(LLMError) as excinfo:
        _parse_json('{"a": ')
    message = str(excinfo.value)
    assert "did not return valid JSON" in message
    assert '{"a": ' in message


def test_parse_json_on_empty_text_reproduces_the_reported_symptom():
    """This is the message the user saw. It is still correct for a genuinely
    empty response -- the fix is to identify *why* it was empty, upstream."""
    with pytest.raises(LLMError) as excinfo:
        _parse_json("")
    assert "Expecting value: line 1 column 1 (char 0)" in str(excinfo.value)


# ---------------------------------------------------------------------------
# Completion
# ---------------------------------------------------------------------------

def test_completion_blank_treats_whitespace_as_empty():
    assert reply("").blank
    assert reply("   \n\t ").blank
    assert not reply("{}").blank


def test_completion_truncated_covers_both_provider_vocabularies():
    assert reply("x", finish_reason="length").truncated          # OpenAI-compatible
    assert reply("x", finish_reason="max_tokens").truncated      # Anthropic
    assert reply("x", finish_reason="max_output_tokens").truncated


def test_completion_truncated_is_false_for_a_clean_stop():
    assert not reply("{}", finish_reason="stop").truncated
    assert not reply("{}", finish_reason=None).truncated
    assert not reply("{}", finish_reason="content_filter").truncated


def test_completion_must_be_read_only_after_construction():
    """Frozen: a diagnostic built from a Completion must not be able to deny
    what the provider actually returned."""
    with pytest.raises(Exception):
        reasoning_exhausted().content = "{}"


# ---------------------------------------------------------------------------
# Budget arithmetic
# ---------------------------------------------------------------------------

def test_escalated_multiplies_the_budget():
    assert _escalated(1000) == 4000
    assert _escalated(DEFAULT_MAX_TOKENS) == 64000


def test_escalated_is_capped_at_the_ceiling():
    assert _escalated(MAX_TOKENS_CEILING) is None
    assert _escalated(MAX_TOKENS_CEILING // 2) == MAX_TOKENS_CEILING
    assert _escalated(MAX_TOKENS_CEILING - 1) == MAX_TOKENS_CEILING


def test_escalated_returns_none_when_there_is_no_headroom():
    """At or above the ceiling the retry would be a no-op or a shrinking
    budget, so the caller must be told there is room to retry at all."""
    assert _escalated(MAX_TOKENS_CEILING + 1) is None
    assert _escalated(1_000_000) is None


def test_escalated_rejects_a_zero_budget_rather_than_looping():
    assert _escalated(0) is None


# ---------------------------------------------------------------------------
# Env reading
# ---------------------------------------------------------------------------

def test_env_positive_int_falls_back_when_unset(monkeypatch):
    monkeypatch.delenv("VR_TEST_TOKENS", raising=False)
    assert _env_positive_int("VR_TEST_TOKENS", 7) == 7


@pytest.mark.parametrize("raw", ["", "0", "-1", "abc", "1.5", " 0 "])
def test_env_positive_int_falls_back_for_unusable_values(monkeypatch, raw):
    monkeypatch.setenv("VR_TEST_TOKENS", raw)
    assert _env_positive_int("VR_TEST_TOKENS", 7) == 7


def test_env_positive_int_honours_a_real_value(monkeypatch):
    monkeypatch.setenv("VR_TEST_TOKENS", "32000")
    assert _env_positive_int("VR_TEST_TOKENS", 7) == 32000


def test_default_max_tokens_reads_the_env_per_call(monkeypatch):
    """`.env` is loaded by `Settings.from_env()` *after* this module imports,
    so a value captured at import time would be permanently stale."""
    monkeypatch.setenv("LLM_MAX_TOKENS", "24000")
    assert default_max_tokens() == 24000
    monkeypatch.setenv("LLM_MAX_TOKENS", "1234")
    assert default_max_tokens() == 1234


def test_default_max_tokens_falls_back_when_unset(monkeypatch):
    monkeypatch.delenv("LLM_MAX_TOKENS", raising=False)
    assert default_max_tokens() == DEFAULT_MAX_TOKENS


# ---------------------------------------------------------------------------
# Provider payload readers
# ---------------------------------------------------------------------------

def test_openai_completion_reads_content_and_finish_reason():
    got = _openai_completion({
        "choices": [{"message": {"content": '{"a": 1}'}, "finish_reason": "stop"}],
        "usage": {"completion_tokens": 42},
    })
    assert got.content == '{"a": 1}'
    assert got.finish_reason == "stop"
    assert got.completion_tokens == 42
    assert got.reasoning_chars == 0
    assert got.reasoning_tokens is None


def test_openai_completion_reads_the_reasoning_diagnostics():
    """These two numbers are the whole diagnosis of the reported bug."""
    got = _openai_completion({
        "choices": [{"message": {"content": "", "reasoning_content": "x" * 30}, "finish_reason": "length"}],
        "usage": {
            "completion_tokens": 8000,
            "completion_tokens_details": {"reasoning_tokens": 8000},
        },
    })
    assert got.blank
    assert got.truncated
    assert got.reasoning_chars == 30
    assert got.reasoning_tokens == 8000
    assert got.completion_tokens == 8000


def test_openai_completion_coerces_null_content_to_empty_string():
    """DeepSeek sends `content: null` (not "") on a reasoning-exhausted reply.
    A `None` leaking out would crash the parser instead of diagnosing it."""
    got = _openai_completion({
        "choices": [{"message": {"content": None, "reasoning_content": "x"}, "finish_reason": "length"}],
    })
    assert got.content == ""
    assert got.blank


def test_openai_completion_coerces_a_structured_content_block():
    """Some OpenAI-compatible gateways return content as a list of parts."""
    got = _openai_completion({"choices": [{"message": {"content": [{"type": "text", "text": "{}"}]}}]})
    assert got.content == ""
    assert got.blank


def test_openai_completion_tolerates_a_missing_message_and_usage():
    got = _openai_completion({"choices": [{"finish_reason": "stop"}]})
    assert got.content == ""
    assert got.completion_tokens is None


def test_anthropic_completion_joins_text_blocks_and_ignores_others():
    got = _anthropic_completion({
        "content": [
            {"type": "thinking", "thinking": "..."},
            {"type": "text", "text": '{"a": '},
            {"type": "text", "text": "1}"},
        ],
        "stop_reason": "end_turn",
        "usage": {"output_tokens": 17},
    })
    assert got.content == '{"a": 1}'
    assert got.finish_reason == "end_turn"
    assert got.completion_tokens == 17
    assert got.reasoning_chars == 0
    assert not got.truncated


def test_anthropic_completion_reports_max_tokens_as_truncated():
    got = _anthropic_completion({"content": [], "stop_reason": "max_tokens", "usage": {}})
    assert got.blank
    assert got.truncated


def test_anthropic_completion_tolerates_an_empty_content_list():
    got = _anthropic_completion({"content": []})
    assert got.blank
    assert got.completion_tokens is None


# ---------------------------------------------------------------------------
# _json_within_budget
# ---------------------------------------------------------------------------

def test_json_within_budget_returns_the_parsed_object_on_the_first_try():
    send = Recorder(reply('{"a": 1}'))
    assert _json_within_budget(label="deepseek/flash", budget=8000, send=send) == {"a": 1}
    assert send.budgets == [8000]


def test_json_within_budget_keeps_the_configured_budget():
    """The caller's budget is the FIRST attempt, not a hint to escalate."""
    send = Recorder(reply('{"a": 1}'))
    _json_within_budget(label="x", budget=12345, send=send)
    assert send.budgets == [12345]


def test_json_within_budget_retries_once_when_the_reply_is_blank():
    """The reported failure: a blank reply at 8000 is a budget failure, and it
    is recoverable, so the retry must happen."""
    send = Recorder(reasoning_exhausted(), reply('{"entries": []}'))
    assert _json_within_budget(label="nexus", budget=8000, send=send) == {"entries": []}
    assert send.budgets == [8000, 32000]


def test_json_within_budget_retries_once_when_the_reply_was_cut_off():
    """A mid-string truncation (`Unterminated string ... char 2461`) is the
    other face of the same budget problem."""
    send = Recorder(
        reply('{"entries": [{"a": "unterminated', finish_reason="length"),
        reply('{"entries": []}'),
    )
    assert _json_within_budget(label="segments", budget=8000, send=send) == {"entries": []}
    assert send.budgets == [8000, 32000]


def test_json_within_budget_does_not_retry_a_complete_but_garbled_reply():
    """Guards the cost of the fix: a reply that finished cleanly cannot be
    fixed by more tokens, so it must not be paid for twice."""
    send = Recorder(reply("not json at all", finish_reason="stop"))
    with pytest.raises(LLMError) as excinfo:
        _json_within_budget(label="x", budget=8000, send=send)
    assert send.budgets == [8000]
    assert "did not return valid JSON" in str(excinfo.value)


def test_json_within_budget_does_not_retry_a_valid_json_non_object():
    send = Recorder(reply("[1, 2]", finish_reason="stop"))
    with pytest.raises(LLMError):
        _json_within_budget(label="x", budget=8000, send=send)
    assert send.budgets == [8000]


def test_json_within_budget_reports_an_unretryable_blank_reply():
    """Above the ceiling there is no room to retry, and the error must say so
    rather than looking like a plain parse failure."""
    send = Recorder(reasoning_exhausted(reasoning_chars=70_000, budget=MAX_TOKENS_CEILING))
    with pytest.raises(LLMError) as excinfo:
        _json_within_budget(label="nexus", budget=MAX_TOKENS_CEILING, send=send)
    message = str(excinfo.value)
    assert send.budgets == [MAX_TOKENS_CEILING]
    assert "no content" in message
    assert str(MAX_TOKENS_CEILING) in message
    assert "ceiling" in message


def test_json_within_budget_names_reasoning_as_the_cause_of_a_blank_reply():
    """The single most valuable line in the error: without it, a blank 200
    looks like a malformed-JSON bug in the parser."""
    send = Recorder(reasoning_exhausted(), reasoning_exhausted(budget=32000))
    with pytest.raises(LLMError) as excinfo:
        _json_within_budget(label="deepseek/deepseek-flash", budget=8000, send=send)
    message = str(excinfo.value)
    assert "reasoning_content shares the max_tokens allowance" in message
    assert "never started the JSON" in message


def test_json_within_budget_error_names_the_provider_and_model():
    send = Recorder(reasoning_exhausted(), reasoning_exhausted(budget=32000))
    with pytest.raises(LLMError) as excinfo:
        _json_within_budget(label="deepseek/deepseek-flash", budget=8000, send=send)
    assert "deepseek/deepseek-flash" in str(excinfo.value)


def test_json_within_budget_error_reports_the_token_counts():
    """Run at the ceiling so there is exactly one attempt and the counts in
    the message can only describe it."""
    send = Recorder(reasoning_exhausted(reasoning_chars=60_000, budget=MAX_TOKENS_CEILING))
    with pytest.raises(LLMError) as excinfo:
        _json_within_budget(label="x", budget=MAX_TOKENS_CEILING, send=send)
    message = str(excinfo.value)
    assert "finish_reason='length'" in message
    assert "reasoning_chars=60000" in message
    assert f"completion_tokens={MAX_TOKENS_CEILING}" in message
    assert f"reasoning_tokens={MAX_TOKENS_CEILING}" in message
    assert f"max_tokens={MAX_TOKENS_CEILING}" in message


def test_json_within_budget_does_not_claim_reasoning_when_there_is_none():
    """A blank reply from a non-reasoning provider must not be blamed on
    reasoning, or the hint becomes noise the operator learns to ignore."""
    send = Recorder(reply("", finish_reason="length"), reply("", finish_reason="length"))
    with pytest.raises(LLMError) as excinfo:
        _json_within_budget(label="ollama/qwen", budget=8000, send=send)
    assert "never started the JSON" not in str(excinfo.value)


def test_json_within_budget_says_the_prompt_is_the_limit_after_a_failed_retry():
    send = Recorder(reasoning_exhausted(), reasoning_exhausted(budget=32000))
    with pytest.raises(LLMError) as excinfo:
        _json_within_budget(label="x", budget=8000, send=send)
    message = str(excinfo.value)
    assert send.budgets == [8000, 32000]
    assert "32000" in message
    assert "the prompt itself is the likely limit" in message


def test_json_within_budget_reports_the_second_reply_not_the_first():
    """The escalation error must describe the attempt that actually failed
    last, otherwise the token counts contradict the budget in the message."""
    send = Recorder(
        reasoning_exhausted(),
        reasoning_exhausted(reasoning_chars=36_721, budget=32000),
    )
    with pytest.raises(LLMError) as excinfo:
        _json_within_budget(label="x", budget=8000, send=send)
    message = str(excinfo.value)
    assert "reasoning_chars=36721" in message
    assert "max_tokens=32000" in message


def test_json_within_budget_surfaces_a_refused_escalation():
    """A hard per-model ceiling turns the bigger budget into a 400. The report
    must name the refusal instead of blaming the parser a second time."""
    send = Recorder(
        reasoning_exhausted(),
        LLMError('Provider returned 400: max_tokens (32000) exceeds model limit'),
    )
    with pytest.raises(LLMError) as excinfo:
        _json_within_budget(label="x", budget=8000, send=send)
    message = str(excinfo.value)
    assert "was refused" in message
    assert "exceeds model limit" in message
    # The first attempt's diagnosis survives: it is the more useful one.
    assert "reasoning_chars=30180" in message
    # ...and it is not misreported as "we retried and it failed the same way".
    assert "the prompt itself is the likely limit" not in message


def test_json_within_budget_retry_is_capped_by_the_ceiling():
    send = Recorder(reasoning_exhausted(budget=MAX_TOKENS_CEILING // 2),
                    reply('{"ok": true}'))
    assert _json_within_budget(label="x", budget=MAX_TOKENS_CEILING // 2, send=send) == {"ok": True}
    assert send.budgets == [MAX_TOKENS_CEILING // 2, MAX_TOKENS_CEILING]


def test_json_within_budget_preserves_the_cause_for_debugging():
    """The underlying `json.loads` complaint is still appended: the diagnostic
    augments it, it does not replace it."""
    send = Recorder(reasoning_exhausted(), reasoning_exhausted(budget=32000))
    with pytest.raises(LLMError) as excinfo:
        _json_within_budget(label="x", budget=8000, send=send)
    assert "Expecting value: line 1 column 1 (char 0)" in str(excinfo.value)


def test_json_within_budget_calls_send_exactly_twice_on_a_recoverable_failure():
    """No retry loops: a third attempt would double the cost of a broken
    prompt without changing the outcome."""
    send = Recorder(reasoning_exhausted(), reasoning_exhausted(budget=32000))
    with pytest.raises(LLMError):
        _json_within_budget(label="x", budget=8000, send=send)
    assert len(send.budgets) == 2


# ---------------------------------------------------------------------------
# _budget_error directly
# ---------------------------------------------------------------------------

def test_budget_error_distinguishes_blank_from_truncated():
    args = dict(escalation=None, refusal=None, retried=False, cause=None)
    blank = _budget_error("x", reasoning_exhausted(), 8000, **args)
    cut = _budget_error("x", reply('{"a":', finish_reason="length"), 8000, **args)
    assert "no content" in str(blank)
    assert "cut off before the JSON was complete" in str(cut)


def test_budget_error_omits_absent_facts():
    """Facts that are unknown (None) are dropped rather than rendered as
    `reasoning_tokens=None`, which would read like a measured zero."""
    err = _budget_error(
        "x", reasoning_exhausted(), 8000,
        escalation=None, refusal=None, retried=False, cause=None,
    )
    assert "completion_tokens=None" not in str(err)
    assert "reasoning_tokens=None" not in str(err)
    assert "max_tokens=8000" in str(err)


def test_budget_error_prompts_for_the_fix_when_a_retry_exists():
    err = _budget_error(
        "x", reasoning_exhausted(), 8000,
        escalation=32000, refusal=None, retried=False, cause=None,
    )
    assert "raise LLM_MAX_TOKENS" in str(err)


# ---------------------------------------------------------------------------
# build_client wiring
# ---------------------------------------------------------------------------

def test_build_client_forwards_the_output_budget():
    """`LLM_MAX_TOKENS` was inert before this: `Settings.llm_max_tokens` had no
    consumer, and the enrichment path's hardcoded 8000 always won."""
    client = build_client(
        provider="deepseek", model="deepseek-flash", api_key="k", max_tokens=20000,
    )
    assert client.max_tokens == 20000


def test_build_client_leaves_the_budget_unset_when_not_given(monkeypatch):
    """Unset must stay None so the client falls back to the env at request
    time, not at construction time."""
    monkeypatch.delenv("LLM_MAX_TOKENS", raising=False)
    client = build_client(provider="deepseek", model="deepseek-flash", api_key="k")
    assert client.max_tokens is None


def test_build_client_forwards_the_budget_to_the_anthropic_adapter():
    client = build_client(
        provider="anthropic", model="claude-3-5-sonnet-latest", api_key="k", max_tokens=12345,
    )
    assert client.max_tokens == 12345
    assert "anthropic" in type(client).__name__.lower()


@pytest.mark.parametrize("provider", ["deepseek", "openai", "openrouter", "ollama"])
def test_build_client_forwards_the_budget_to_openai_compatible_adapters(provider):
    client = build_client(provider=provider, api_key="k", max_tokens=999)
    assert client.max_tokens == 999


def test_build_client_default_provider_is_openrouter(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    client = build_client(api_key="k")
    assert client.provider == "openrouter"
    assert client.model == "anthropic/claude-3.5-sonnet"
    assert json.loads(json.dumps(client.base_url)) == "https://openrouter.ai/api/v1"


def test_settings_forwards_the_budget_to_the_client(monkeypatch):
    """The end-to-end wiring that was missing: Settings -> build_client."""
    from violation_pack.config import Settings

    monkeypatch.setenv("LLM_PROVIDER", "deepseek")
    monkeypatch.setenv("LLM_API_KEY", "k")
    monkeypatch.setenv("LLM_MAX_TOKENS", "31000")
    settings = Settings.from_env()
    assert settings.llm_max_tokens == 31000
    assert settings.llm_client().max_tokens == 31000


def test_settings_max_tokens_default_is_roomy_enough_for_a_reasoner(monkeypatch):
    """The default must leave space for the answer after the model thinks.
    8000 did not: the live nexus stage spent all of it on reasoning."""
    from violation_pack.config import Settings

    monkeypatch.delenv("LLM_MAX_TOKENS", raising=False)
    settings = Settings.from_env()
    assert settings.llm_max_tokens == DEFAULT_MAX_TOKENS
    assert settings.llm_max_tokens >= 16000


def test_advertised_defaults_do_not_drift_from_the_code():
    """Three surfaces advertise the same number: the code default, the
    installer's example, and the UI spec. They had already drifted apart (the
    example still said 8000 after the code moved), which is how an operator
    ends up copying a value that reproduces the original bug."""
    root = Path(__file__).resolve().parent.parent

    example = (root / ".env.example").read_text(encoding="utf-8")
    advertised = [
        line.split("=", 1)[1].strip()
        for line in example.splitlines()
        if line.startswith("LLM_MAX_TOKENS=")
    ]
    assert advertised == [str(DEFAULT_MAX_TOKENS)], example

    spec = (root / "docs" / "ui_structural_skeleton.md").read_text(encoding="utf-8")
    assert f"| `LLM_MAX_TOKENS` | `{DEFAULT_MAX_TOKENS}` |" in spec


# Deliberately NOT tested: reading `.env.example` through `config.load_dotenv`
# to prove the advertised value is loadable. That call writes every key in the
# file straight into `os.environ` -- measured: 33 keys, 22 of them empty
# strings, including `LLM_PROVIDER`, `LLM_MODEL` and `LLM_BASE_URL` -- and
# `monkeypatch` only records the keys it touched itself, so the other 32 leak
# into every later test in the session. The claim it would add is also implied
# by the assertion above: `int("16000") == DEFAULT_MAX_TOKENS` cannot be false
# while `advertised == [str(DEFAULT_MAX_TOKENS)]` holds. Delete, don't cover.
