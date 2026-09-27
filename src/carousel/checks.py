"""Deterministic checks: free, instant, and run again after every manual edit.

Errors block rendering; warnings are for the reviewing doctor to judge.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from .config import WritingConfig
from .pubmed import Paper
from .schema import Carousel

NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)*")
HIGHLIGHT_RE = re.compile(r"\*\*(.+?)\*\*")

# Causal wording that an observational design cannot support.
CAUSAL_WORDS = ["menyebabkan", "penyebab", "mencegah", "menyembuhkan", "membuktikan", "terbukti"]
# Overclaiming wording that no single study supports.
ABSOLUTE_WORDS = ["pasti", "selalu", "dijamin", "100% aman", "obat ajaib"]


@dataclass
class Issue:
    level: str  # "error" | "warning"
    where: str
    message: str

    def __str__(self) -> str:
        return f"[{self.level.upper()}] {self.where}: {self.message}"


# --------------------------------------------------------------------------- helpers


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).lower()
    for ch in "‐‑‒–—−":
        text = text.replace(ch, "-")
    text = text.replace("‘", "'").replace("’", "'").replace("“", '"').replace("”", '"')
    return " ".join(text.split())


def quote_in_source(quote: str, source: str) -> bool:
    """True if every ellipsis-separated fragment of ``quote`` occurs verbatim in ``source``."""
    fragments = [f.strip(" .,;:") for f in re.split(r"\.\.\.|…", normalize(quote))]
    fragments = [f for f in fragments if f]
    return bool(fragments) and all(f in source for f in fragments)


def _dec(s: str) -> Decimal | None:
    try:
        return Decimal(s).normalize()
    except InvalidOperation:
        return None


def number_values(token: str) -> set[Decimal]:
    """All plausible values of a numeric token under Indonesian and English conventions.

    Indonesian writes 5.320 (thousands) and 0,75 (decimal); English sources write
    5,320 and 0.75. "5.320" is therefore read as both 5320 and 5.32.
    """
    values: set[Decimal] = set()
    has_dot, has_comma = "." in token, "," in token
    if not has_dot and not has_comma:
        values.add(_dec(token))
    elif has_dot and has_comma:
        last = max(token.rfind("."), token.rfind(","))
        integer = re.sub(r"[.,]", "", token[:last])
        values.add(_dec(f"{integer}.{token[last + 1:]}"))
    else:
        sep = "." if has_dot else ","
        groups = token.split(sep)
        if len(groups) == 2:
            values.add(_dec(f"{groups[0]}.{groups[1]}"))  # decimal reading
        if all(len(g) == 3 for g in groups[1:]):
            values.add(_dec("".join(groups)))  # thousands reading
    return {v for v in values if v is not None}


def numbers_in(text: str) -> list[str]:
    return NUMBER_RE.findall(text)


def word_count(text: str) -> int:
    return len(HIGHLIGHT_RE.sub(r"\1", text).split())


# --------------------------------------------------------------------------- checks


def check_carousel(carousel: Carousel, paper: Paper, writing: WritingConfig) -> list[Issue]:
    issues: list[Issue] = []
    source = normalize(paper.source_text())
    source_values: set[Decimal] = set()
    for tok in numbers_in(paper.source_text()) + [paper.year]:
        source_values |= number_values(tok)

    slides = carousel.slides
    n = len(slides)
    if not writing.min_slides <= n <= writing.max_slides:
        issues.append(
            Issue("error", "carousel", f"{n} content slides; expected {writing.min_slides} to {writing.max_slides}")
        )
    if slides and slides[0].role != "hook":
        issues.append(Issue("error", "slide 1", "first slide must be the hook"))
    if slides and slides[-1].role != "takeaway":
        issues.append(Issue("error", f"slide {n}", "last content slide must be the takeaway"))
    if not any(s.role == "caveat" for s in slides):
        issues.append(Issue("error", "carousel", "no caveat slide; every carousel states the study's limits"))

    for i, s in enumerate(slides, start=1):
        where = f"slide {i} ({s.role})"
        hw, bw = word_count(s.headline), word_count(s.body)
        if hw > writing.max_headline_words:
            issues.append(Issue("warning", where, f"headline has {hw} words (max {writing.max_headline_words})"))
        if bw > writing.max_body_words:
            issues.append(Issue("warning", where, f"body has {bw} words (max {writing.max_body_words})"))
        if s.role == "number" and not s.big_number.strip():
            issues.append(Issue("error", where, "number slide without big_number"))

        if not s.evidence:
            issues.append(Issue("error", where, "no supporting quote"))
        for q in s.evidence:
            if not quote_in_source(q.quote, source):
                issues.append(Issue("error", where, f"quote not found verbatim in source: \"{q.quote[:90]}\""))

        slide_values: set[Decimal] = set()
        for q in s.evidence:
            for tok in numbers_in(q.quote):
                slide_values |= number_values(tok)
        for tok in numbers_in(" ".join([s.headline, s.body, s.big_number])):
            vals = number_values(tok)
            if vals & slide_values:
                continue
            if vals & source_values:
                issues.append(Issue("warning", where, f"number {tok} is in the source but not in this slide's quotes"))
            else:
                issues.append(Issue("error", where, f"number {tok} does not appear anywhere in the source"))

        text = normalize(f"{s.headline} {s.body}")
        if paper.is_observational:
            for w in CAUSAL_WORDS:
                if re.search(rf"\b{w}\b", text):
                    issues.append(Issue("warning", where, f"causal word '{w}' in an observational study"))
        for w in ABSOLUTE_WORDS:
            if re.search(rf"\b{re.escape(w)}\b", text):
                issues.append(Issue("warning", where, f"overclaiming word '{w}'"))

    for tok in numbers_in(carousel.caption):
        if not number_values(tok) & source_values:
            issues.append(Issue("warning", "caption", f"number {tok} does not appear anywhere in the source"))
    caption_len = len(caption_text(carousel, paper))
    if caption_len > 2200:
        issues.append(Issue("error", "caption", f"{caption_len} characters; Instagram allows 2,200"))
    if len(carousel.hashtags) > writing.max_hashtags:
        issues.append(Issue("warning", "hashtags", f"{len(carousel.hashtags)} hashtags (max {writing.max_hashtags})"))

    return issues


def caption_text(carousel: Carousel, paper: Paper) -> str:
    tags = " ".join("#" + t.lstrip("#").replace(" ", "") for t in carousel.hashtags)
    return f"{carousel.caption.strip()}\n\nSumber: {paper.full_citation}\n\n{tags}".strip()


def has_errors(issues: list[Issue]) -> bool:
    return any(i.level == "error" for i in issues)
