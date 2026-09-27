"""Claude over YouTube data: demand report -> ideas -> freeform draft or PubMed query.

Division of labour: YouTube Data API supplies numbers and comments, Gemini
watches the videos, Claude reads everything together, checks its own quotes
against the comments, and writes carousels in the existing pipeline's formats.
"""

from __future__ import annotations

import datetime as dt
import json
from typing import Any

import anthropic

from .checks import Issue, normalize, quote_in_source
from .config import Config
from .llm import _call, _prompt
from .schema import ContentIdea, DemandReport, FreeformDraft
from .youtube import Comment, Video


def youtube_block(videos: list[Video], comments: list[Comment], briefs: dict[str, dict], now: dt.datetime) -> str:
    rows = [
        {"id": v.id, "title": v.title, "channel": v.channel, "views": v.views,
         "views_per_day": round(v.views_per_day(now)), "comments_per_1k_views": round(v.comments_per_1k_views, 1),
         "minutes": round(v.duration_s / 60, 1)}
        for v in videos
    ]
    by_video: dict[str, list[dict]] = {}
    for c in comments:
        by_video.setdefault(c.video_id, []).append({"likes": c.likes, "text": c.text})
    data = {"VIDEOS": rows, "COMMENTS": by_video, "BRIEFS": briefs}
    return f"<youtube_data>\n{json.dumps(data, ensure_ascii=False, indent=1)}\n</youtube_data>"


def analyze_demand(client: anthropic.Anthropic, cfg: Config, query: str, videos: list[Video],
                   comments: list[Comment], briefs: dict[str, dict],
                   now: dt.datetime | None = None) -> tuple[DemandReport, dict]:
    now = now or dt.datetime.now(dt.timezone.utc)
    user = youtube_block(videos, comments, briefs, now) + f"\n\nSearch query: {query}\nWrite the demand report."
    return _call(client, cfg, _prompt("demand_system.md"), user, DemandReport)


def check_report(report: DemandReport, comments: list[Comment], video_ids: set[str]) -> list[Issue]:
    """Every evidence quote must be a real comment; every cited video must be in the sample."""
    corpus = normalize("\n".join(c.text for c in comments))
    issues = []
    for t in report.themes:
        for q in t.evidence:
            if not quote_in_source(q.quote, corpus):
                issues.append(Issue("error", f"theme '{t.theme}'", f"quote not found in comments: \"{q.quote[:80]}\""))
        for vid in t.video_ids:
            if vid not in video_ids:
                issues.append(Issue("error", f"theme '{t.theme}'", f"unknown video id {vid}"))
    for i, idea in enumerate(report.ideas, start=1):
        if idea.track == "health" and not idea.pubmed_query.strip():
            issues.append(Issue("error", f"idea {i}", "health idea without pubmed_query"))
    return issues


def report_markdown(query: str, report: DemandReport, issues: list[Issue], videos: list[Video], now: dt.datetime) -> str:
    out = [f"# YouTube demand: {query}", "", report.summary, ""]
    if issues:
        out += ["## Check results"] + [f"- {i}" for i in issues] + [""]
    out += ["## Top videos by momentum", "", "| views/day | comments/1k | min | title |", "|---:|---:|---:|---|"]
    out += [f"| {v.views_per_day(now):,.0f} | {v.comments_per_1k_views:.1f} | {v.duration_s / 60:.0f} | [{v.title}]({v.url}) |"
            for v in videos[:10]]
    out += ["", "## Demand themes"]
    for t in report.themes:
        out += [f"### {t.theme}", t.why_it_matters] + [f"> {q.quote}" for q in t.evidence] + [""]
    for title, items in (("Audience questions", report.audience_questions),
                         ("Claims to verify before use", report.claims_to_verify),
                         ("Format lessons", report.format_lessons),
                         ("Limitations", report.limitations)):
        out += [f"## {title}"] + [f"- {x}" for x in items] + [""]
    out += ["## Ideas"]
    for i, idea in enumerate(report.ideas, start=1):
        extra = f" | PubMed: `{idea.pubmed_query}`" if idea.track == "health" else ""
        out += [f"{i}. **{idea.title}** ({idea.track}{extra})", f"   {idea.angle}"] + [f"   - {b}" for b in idea.outline]
    out += ["", "Next: `carousel yt-idea <this folder> <idea number>`"]
    return "\n".join(out) + "\n"


def draft_freeform(client: anthropic.Anthropic, cfg: Config, idea: ContentIdea, report: DemandReport) -> tuple[FreeformDraft, dict]:
    w = cfg.writing
    system = _prompt("freeform_system.md", sapaan=w.freeform_sapaan,
                     max_headline_words=w.max_headline_words, max_body_words=w.max_body_words)
    context: dict[str, Any] = {
        "idea": idea.model_dump(),
        "themes": [t.model_dump() for t in report.themes if t.theme in idea.based_on],
        "audience_questions": report.audience_questions,
        "format_lessons": report.format_lessons,
    }
    user = f"<idea_context>\n{json.dumps(context, ensure_ascii=False, indent=1)}\n</idea_context>\n\nDraft the carousel."
    return _call(client, cfg, system, user, FreeformDraft)
