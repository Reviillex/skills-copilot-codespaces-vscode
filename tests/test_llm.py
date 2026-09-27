"""Control flow of the Claude calls, with a stub client (no network, no API key)."""

from types import SimpleNamespace

import pytest

from carousel import llm
from carousel.config import Config


class StubMessages:
    def __init__(self, response):
        self.response = response
        self.kwargs = None

    def parse(self, **kwargs):
        self.kwargs = kwargs
        return self.response


def stub_client(response):
    messages = StubMessages(response)
    return SimpleNamespace(beta=SimpleNamespace(messages=messages)), messages


def response(stop_reason="end_turn", parsed=None, model="claude-opus-5"):
    return SimpleNamespace(
        stop_reason=stop_reason,
        stop_details=SimpleNamespace(category="bio") if stop_reason == "refusal" else None,
        parsed_output=parsed,
        model=model,
        usage=SimpleNamespace(input_tokens=20_000, output_tokens=4_000),
    )


def test_draft_request_shape_and_usage(sample_paper, sample_carousel):
    client, messages = stub_client(response(parsed=sample_carousel))
    carousel, usage = llm.draft_carousel(client, Config(), sample_paper)

    assert carousel is sample_carousel
    kw = messages.kwargs
    assert kw["model"] == "claude-opus-5"
    assert kw["fallbacks"] == "default"
    assert kw["betas"] == [llm.FALLBACK_BETA]
    assert kw["thinking"] == {"type": "adaptive"}
    assert kw["output_format"] is llm.Carousel
    assert "{sapaan}" not in kw["system"] and '"Anda"' in kw["system"]
    assert "<source_text>" in kw["messages"][0]["content"]
    # 20k * $5/M + 4k * $25/M
    assert usage["cost_usd"] == pytest.approx(0.2)


def test_review_hides_drafter_quotes(sample_paper, sample_carousel):
    client, messages = stub_client(response(parsed=object()))
    llm.review_carousel(client, Config(), sample_paper, sample_carousel)
    draft_part = messages.kwargs["messages"][0]["content"].split("<carousel_draft>")[1]
    assert "\"evidence\":" not in draft_part
    assert "quote" not in draft_part


@pytest.mark.parametrize("stop_reason, text", [("refusal", "declined"), ("max_tokens", "max_tokens")])
def test_bad_stop_reasons_raise(sample_paper, stop_reason, text):
    client, _ = stub_client(response(stop_reason=stop_reason))
    with pytest.raises(llm.DraftError, match=text):
        llm.draft_carousel(client, Config(), sample_paper)


def test_missing_parsed_output_raises(sample_paper):
    client, _ = stub_client(response(parsed=None))
    with pytest.raises(llm.DraftError, match="no parsable output"):
        llm.draft_carousel(client, Config(), sample_paper)


def test_fallback_model_priced_by_served_model(sample_paper, sample_carousel):
    client, _ = stub_client(response(parsed=sample_carousel, model="claude-opus-4-8"))
    _, usage = llm.draft_carousel(client, Config(), sample_paper)
    assert usage["model"] == "claude-opus-4-8"
    assert "cost_usd" not in usage
