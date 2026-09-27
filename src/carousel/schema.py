"""Structured-output schemas for the draft and review calls.

Length limits live in the prompt and in checks.py, not as schema constraints:
a hard constraint that the model misses would fail parsing and throw away the
whole draft, while a lint warning keeps the draft editable.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

SlideRole = Literal["hook", "context", "finding", "number", "caveat", "takeaway"]


class Evidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    quote: str = Field(
        description="Verbatim English sentence or phrase copied character-for-character from the SOURCE TEXT."
    )


class Slide(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: SlideRole
    headline: str = Field(description="Indonesian headline. Use **double asterisks** to highlight 1 to 3 words.")
    body: str = Field(
        description='Indonesian body text, "" if none. Lines starting with "- " render as a bullet list.'
    )
    big_number: str = Field(
        description='Only for role "number": the key figure as written in Indonesian, e.g. "25%". Otherwise "".'
    )
    evidence: list[Evidence] = Field(description="1 to 3 verbatim quotes that support every claim on this slide.")


class Carousel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    topic_tag: str = Field(description="2 to 4 word Indonesian topic tag shown on the cover, e.g. 'Tidur & Jantung'.")
    evidence_label: str = Field(
        description="Indonesian study summary for the cover badge, e.g. 'Meta-analisis 24 RCT, 5.320 peserta'."
    )
    slides: list[Slide]
    caption: str = Field(description="Instagram caption in Indonesian, without hashtags.")
    hashtags: list[str] = Field(description="Hashtags without the # sign.")
    editor_notes: list[str] = Field(
        description="Notes for the doctor reviewing this draft (English or Indonesian). Not published."
    )


Verdict = Literal["supported", "overstated", "unsupported", "translation-error", "missing-context"]


class SlideReview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slide: int = Field(description="1-based slide number.")
    verdict: Verdict
    problem: str = Field(description='What is wrong, "" if supported.')
    suggested_fix: str = Field(description='Corrected Indonesian text, "" if supported.')


class Review(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slides: list[SlideReview]
    caption_problems: list[str]
    omitted_points: list[str] = Field(
        description="Important findings, harms or limitations in the source that the carousel leaves out."
    )
    overall: Literal["ready", "needs-edits", "reject"]
    summary: str


# --------------------------------------------------------------------------- rendering

SlideKind = Literal["cover", "text", "number", "caveat", "cta", "reference"]


class RenderSlide(BaseModel):
    """One slide as the template sees it. Health carousels are converted into
    these; free-form carousels (opinion, hobby series) are written in this
    shape directly. "reference" is produced by code only, for the source slide."""

    model_config = ConfigDict(extra="forbid")

    kind: SlideKind
    kicker: str = ""
    headline: str = ""
    lead: str = ""
    body: str = ""
    big_number: str = ""
    callout: str = ""
    figure: str = ""
    question: str = ""
    note: str = ""


class FreeformCarousel(BaseModel):
    """A carousel written by hand (no paper, no evidence checks)."""

    model_config = ConfigDict(extra="forbid")

    series: str = ""
    theme: str = "noir"
    footer: str = ""
    caption: str = ""
    hashtags: list[str] = Field(default_factory=list)
    slides: list[RenderSlide]


# --------------------------------------------------------------------------- YouTube insights


class CommentQuote(BaseModel):
    model_config = ConfigDict(extra="forbid")

    quote: str = Field(description="Comment text copied character-for-character from the COMMENTS data.")


class DemandTheme(BaseModel):
    model_config = ConfigDict(extra="forbid")

    theme: str
    why_it_matters: str
    evidence: list[CommentQuote] = Field(description="2 to 4 verbatim comments showing this demand.")
    video_ids: list[str]


class ContentIdea(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    angle: str = Field(description="What this carousel adds that the existing videos do not.")
    track: Literal["health", "freeform"] = Field(
        description="health = needs a paper (PubMed pipeline); freeform = opinion/hobby, no medical claims."
    )
    pubmed_query: str = Field(description='English PubMed terms for health ideas, e.g. "intermittent fasting" AND weight; "" for freeform.')
    outline: list[str] = Field(description="5 to 8 slide beats.")
    based_on: list[str] = Field(description="Theme names this idea answers.")


class DemandReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str
    themes: list[DemandTheme]
    audience_questions: list[str]
    claims_to_verify: list[str] = Field(description="Factual claims from videos or comments that need a source before use.")
    format_lessons: list[str] = Field(description="What high-momentum videos do in hook, length and structure.")
    ideas: list[ContentIdea]
    limitations: list[str]


DraftKind = Literal["cover", "text", "number", "caveat", "cta"]


class DraftSlide(BaseModel):
    """RenderSlide without defaults, for structured output. figure is filled in by hand later."""

    model_config = ConfigDict(extra="forbid")

    kind: DraftKind
    kicker: str
    headline: str
    lead: str
    body: str
    big_number: str
    callout: str
    question: str
    note: str


class FreeformDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    series: str
    footer: str
    caption: str
    hashtags: list[str]
    slides: list[DraftSlide]

    def to_carousel(self, theme: str = "noir") -> FreeformCarousel:
        return FreeformCarousel(
            series=self.series, theme=theme, footer=self.footer, caption=self.caption,
            hashtags=self.hashtags, slides=[RenderSlide(**s.model_dump()) for s in self.slides],
        )
