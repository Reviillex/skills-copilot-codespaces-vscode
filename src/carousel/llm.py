"""Claude calls: draft a carousel from a paper, then review it as an independent fact-checker."""

from __future__ import annotations

import json
from importlib import resources
from typing import Any, TypeVar

import anthropic
from pydantic import BaseModel

from .config import Config
from .pubmed import DESIGN_LABEL_ID, Paper
from .schema import Carousel, Review

T = TypeVar("T", bound=BaseModel)

# USD per 1M tokens (input, output), for the cost line printed after each call.
PRICES = {
    "claude-opus-5": (5.00, 25.00),
    "claude-opus-5-5": (4.00, 20.00),
    "claude-sonnet-5": (2.00, 10.00),
    "claude-haiku-4-5": (1.00, 5.00),
}
# Server-side fallback: if a safety classifier declines the request (possible on
# medical topics), the API re-runs it on Anthropic's recommended fallback model.
FALLBACK_BETA = "server-side-fallback-2026-07-01"
MAX_TOKENS = 16000


class DraftError(RuntimeError):
    pass


def _prompt(name: str, **values: Any) -> str:
    text = resources.files("carousel").joinpath("prompts", name).read_text(encoding="utf-8")
    for key, value in values.items():
        text = text.replace("{" + key + "}", str(value))
    return text


def _paper_block(paper: Paper) -> str:
    meta = {
        "pmid": paper.pmid,
        "journal": paper.journal,
        "year": paper.year,
        "design": DESIGN_LABEL_ID.get(paper.design, paper.design),
        "publication_types": paper.pub_types,
        "source_scope": "full text" if paper.full_text else "abstract only",
    }
    return (
        f"<paper_metadata>\n{json.dumps(meta, ensure_ascii=False, indent=2)}\n</paper_metadata>\n\n"
        f"<source_text>\n{paper.source_text()}\n</source_text>"
    )


def _usage(response: Any) -> dict[str, Any]:
    u = response.usage
    record = {"model": response.model, "input_tokens": u.input_tokens, "output_tokens": u.output_tokens}
    # response.model names the model that actually answered (differs after a fallback).
    if response.model in PRICES:
        pin, pout = PRICES[response.model]
        record["cost_usd"] = round(u.input_tokens * pin / 1e6 + u.output_tokens * pout / 1e6, 4)
    return record


def _call(client: anthropic.Anthropic, cfg: Config, system: str, user: str, output: type[T]) -> tuple[T, dict]:
    response = client.beta.messages.parse(
        model=cfg.model.name,
        max_tokens=MAX_TOKENS,
        system=system,
        messages=[{"role": "user", "content": user}],
        thinking={"type": "adaptive"},
        output_config={"effort": cfg.model.effort},
        output_format=output,
        betas=[FALLBACK_BETA],
        fallbacks="default",
    )
    if response.stop_reason == "refusal":
        details = response.stop_details
        category = getattr(details, "category", None) if details else None
        raise DraftError(f"Request declined (category: {category}). Try another paper or edit the prompt.")
    if response.stop_reason == "max_tokens":
        raise DraftError(f"Output hit max_tokens={MAX_TOKENS}; the draft is incomplete.")
    parsed = response.parsed_output
    if parsed is None:
        raise DraftError("Model returned no parsable output.")
    return parsed, _usage(response)


def draft_carousel(client: anthropic.Anthropic, cfg: Config, paper: Paper) -> tuple[Carousel, dict]:
    w = cfg.writing
    system = _prompt(
        "draft_system.md",
        sapaan=w.sapaan,
        min_slides=w.min_slides,
        max_slides=w.max_slides,
        max_headline_words=w.max_headline_words,
        max_body_words=w.max_body_words,
        max_hashtags=w.max_hashtags,
    )
    user = _paper_block(paper) + "\n\nDraft the carousel for this paper."
    return _call(client, cfg, system, user, Carousel)


def review_carousel(client: anthropic.Anthropic, cfg: Config, paper: Paper, carousel: Carousel) -> tuple[Review, dict]:
    system = _prompt("review_system.md")
    # The drafter's quotes are left out on purpose: the reviewer checks the
    # Indonesian text against the whole source, not against the drafter's picks.
    slides = [
        {"slide": i, **{k: v for k, v in s.model_dump().items() if k != "evidence"}}
        for i, s in enumerate(carousel.slides, start=1)
    ]
    draft = {"evidence_label": carousel.evidence_label, "slides": slides, "caption": carousel.caption}
    user = (
        _paper_block(paper)
        + f"\n\n<carousel_draft>\n{json.dumps(draft, ensure_ascii=False, indent=2)}\n</carousel_draft>"
        + "\n\nReview this draft against the source."
    )
    return _call(client, cfg, system, user, Review)


def usage_line(record: dict) -> str:
    cost = f", ~${record['cost_usd']:.3f}" if "cost_usd" in record else ""
    return f"{record['model']}: {record['input_tokens']:,} in / {record['output_tokens']:,} out{cost}"
