"""YouTube parsing, Gemini request shape, Claude demand report checks, and the yt-* commands.
All offline: fixtures are synthetic and every client is a stub."""

import datetime as dt
import json
import urllib.error
from types import SimpleNamespace

import pytest

from carousel import cli, youtube as yt
from carousel.config import Config, PubMedConfig, YouTubeConfig
from carousel.insights import check_report, report_markdown, youtube_block
from carousel.pubmed import build_query
from carousel.schema import DemandReport

from .conftest import FIXTURES

YT = FIXTURES / "youtube"
NOW = dt.datetime(2026, 9, 27, tzinfo=dt.timezone.utc)


def load(name):
    return json.loads((YT / name).read_text())


def sample_videos():
    return yt.parse_videos(load("videos.json"))


def sample_comments():
    return yt.parse_comments(load("comments.json"), "vidA")


def sample_report(**overrides):
    data = {
        "summary": "Penonton ingin tahu keamanan keto.",
        "themes": [{"theme": "Keamanan", "why_it_matters": "Banyak ragu.",
                    "evidence": [{"quote": "kalau punya asam urat boleh keto nggak?"}], "video_ids": ["vidA"]}],
        "audience_questions": ["Keto aman untuk asam urat?"],
        "claims_to_verify": ["Keto merusak ginjal"],
        "format_lessons": ["Judul berupa pertanyaan"],
        "ideas": [
            {"title": "Keto dan asam urat", "angle": "Bukti", "track": "health",
             "pubmed_query": "ketogenic diet AND uric acid", "outline": ["a"], "based_on": ["Keamanan"]},
            {"title": "Mitos gym", "angle": "Opini", "track": "freeform", "pubmed_query": "",
             "outline": ["b"], "based_on": ["Keamanan"]},
        ],
        "limitations": ["Satu kueri"],
    }
    data.update(overrides)
    return DemandReport.model_validate(data)


# --------------------------------------------------------------------------- YouTube


def test_parse_videos_and_metrics():
    a, b = sample_videos()
    assert (a.id, a.channel, a.views, a.comments, a.duration_s) == ("vidA", "Kanal Sehat", 100000, 800, 750)
    assert b.comments == 0 and b.duration_s == 3720  # commentCount hidden -> 0
    assert a.views_per_day(NOW) == pytest.approx(10000)  # 10 days old
    assert a.comments_per_1k_views == pytest.approx(8.0)
    assert [v.id for v in yt.rank_by_momentum([b, a], NOW)] == ["vidA", "vidB"]
    assert a.url == "https://www.youtube.com/watch?v=vidA"


def test_parse_comments_drops_authors_and_blanks():
    comments = sample_comments()
    assert [c.text for c in comments] == ["Dok, kalau punya asam urat boleh keto nggak?",
                                          "Aku turun 5 kg tapi rambut rontok, normal?"]
    assert "Private" not in yt.to_json(comments)


def test_parse_duration():
    assert yt.parse_duration("PT45S") == 45
    assert yt.parse_duration("P1DT1H") == 90000
    assert yt.parse_duration("garbage") == 0


def test_search_keeps_only_videos_and_sends_filters(monkeypatch):
    seen = {}

    def fake_get(endpoint, params):
        seen.update(endpoint=endpoint, **params)
        return load("search.json")

    monkeypatch.setattr(yt, "_get", fake_get)
    ids = yt.search_video_ids("diet keto", YouTubeConfig(days=30, max_videos=80), NOW)
    assert ids == ["vidA", "vidB"]
    assert seen["endpoint"] == "search" and seen["order"] == "viewCount"
    assert seen["regionCode"] == "ID" and seen["relevanceLanguage"] == "id"
    assert seen["publishedAfter"] == "2026-08-28T00:00:00Z" and seen["maxResults"] == "50"


def test_comments_disabled_returns_empty(monkeypatch):
    def forbidden(endpoint, params):
        raise urllib.error.HTTPError("u", 403, "commentsDisabled", None, None)

    monkeypatch.setattr(yt, "_get", forbidden)
    assert yt.top_comments("vidA", 100) == []


def test_missing_api_key(monkeypatch):
    monkeypatch.delenv("YOUTUBE_API_KEY", raising=False)
    with pytest.raises(yt.YouTubeError, match="YOUTUBE_API_KEY"):
        yt._get("videos", {})


# --------------------------------------------------------------------------- Gemini

@pytest.fixture
def genai_types():
    return pytest.importorskip("google.genai.types")


class StubModels:
    def __init__(self, response):
        self.response, self.kwargs = response, None

    def generate_content(self, **kwargs):
        self.kwargs = kwargs
        return self.response


def test_summarize_video_request_shape(genai_types):
    from carousel import gemini

    brief = gemini.VideoBrief(summary="s", hook="h", structure=["a"], claims=["c"],
                              questions_answered=["q"], format_notes="f")
    models = StubModels(SimpleNamespace(parsed=brief))
    out = gemini.summarize_video(SimpleNamespace(models=models), "gemini-3.5-flash", "https://www.youtube.com/watch?v=vidA")
    assert out is brief
    kw = models.kwargs
    assert kw["model"] == "gemini-3.5-flash"
    assert kw["contents"].parts[0].file_data.file_uri == "https://www.youtube.com/watch?v=vidA"
    assert kw["config"].response_schema is gemini.VideoBrief
    assert kw["config"].media_resolution == genai_types.MediaResolution.MEDIA_RESOLUTION_LOW


def test_summarize_video_without_parsed_output_raises(genai_types):
    from carousel import gemini

    models = StubModels(SimpleNamespace(parsed=None))
    with pytest.raises(gemini.GeminiError):
        gemini.summarize_video(SimpleNamespace(models=models), "m", "u")


def test_generate_image_writes_file_and_provenance(tmp_path, genai_types):
    from carousel import gemini

    part = SimpleNamespace(inline_data=SimpleNamespace(data=b"\x89PNG fake"))
    response = SimpleNamespace(candidates=[SimpleNamespace(content=SimpleNamespace(parts=[part]))])
    models = StubModels(response)
    out = gemini.generate_image(SimpleNamespace(models=models), "gemini-3.1-flash-image", "peta dota", tmp_path / "fig.png", "21:9")
    assert out.read_bytes() == b"\x89PNG fake"
    assert "AI-generated" in (tmp_path / "fig.txt").read_text()
    assert models.kwargs["config"].response_modalities == ["IMAGE"]
    assert models.kwargs["config"].image_config.aspect_ratio == "21:9"


def test_generate_image_blocked_raises(tmp_path, genai_types):
    from carousel import gemini

    models = StubModels(SimpleNamespace(candidates=[]))
    with pytest.raises(gemini.GeminiError, match="no image"):
        gemini.generate_image(SimpleNamespace(models=models), "m", "p", tmp_path / "x.png")


# --------------------------------------------------------------------------- Claude insights


def test_youtube_block_marks_untrusted_data_and_has_no_authors():
    block = youtube_block(sample_videos(), sample_comments(), {"vidA": {"summary": "s"}}, NOW)
    assert block.startswith("<youtube_data>") and block.endswith("</youtube_data>")
    data = json.loads(block.removeprefix("<youtube_data>").removesuffix("</youtube_data>"))
    assert data["VIDEOS"][0]["views_per_day"] == 10000
    assert "Private" not in block
    assert data["BRIEFS"]["vidA"]["summary"] == "s"


def test_check_report_accepts_real_quotes():
    assert check_report(sample_report(), sample_comments(), {"vidA", "vidB"}) == []


def test_check_report_flags_invented_quote_unknown_video_and_missing_query():
    report = sample_report(themes=[{"theme": "X", "why_it_matters": "", "video_ids": ["vidZ"],
                                    "evidence": [{"quote": "keto bikin ginjal rusak"}]}])
    report.ideas[0].pubmed_query = ""
    messages = [i.message for i in check_report(report, sample_comments(), {"vidA"})]
    assert any("quote not found in comments" in m for m in messages)
    assert any("unknown video id vidZ" in m for m in messages)
    assert any("health idea without pubmed_query" in m for m in messages)


def test_report_markdown_lists_ideas_and_momentum():
    md = report_markdown("diet keto", sample_report(), [], sample_videos(), NOW)
    assert "| 10,000 | 8.0 | 12 |" in md
    assert "ketogenic diet AND uric acid" in md and "carousel yt-idea" in md


def test_build_query_custom_query_replaces_topics_and_journals():
    q = build_query(PubMedConfig(topics=["sleep"], journals=["BMJ"], query="ketogenic diet AND uric acid"))
    assert q.endswith("(ketogenic diet AND uric acid)")
    assert "[ta]" not in q and '"sleep"' not in q and '"meta-analysis"[pt]' in q


# --------------------------------------------------------------------------- commands


def test_yt_scan_end_to_end(tmp_path, monkeypatch, capsys):
    from carousel import gemini, insights

    monkeypatch.setattr(yt, "search_video_ids", lambda q, cfg, now: ["vidA", "vidB"])
    monkeypatch.setattr(yt, "video_details", lambda ids: sample_videos())
    monkeypatch.setattr(yt, "top_comments", lambda vid, n: sample_comments() if vid == "vidA" else [])
    monkeypatch.setattr(gemini, "client", lambda: object())
    brief = gemini.VideoBrief(summary="s", hook="h", structure=[], claims=[], questions_answered=[], format_notes="")
    watched = []
    monkeypatch.setattr(gemini, "summarize_video", lambda c, m, url: watched.append(url) or brief)
    monkeypatch.setattr(insights, "analyze_demand",
                        lambda *a, **k: (sample_report(), {"model": "claude-opus-5", "input_tokens": 1, "output_tokens": 1}))
    monkeypatch.setattr(cli, "_warn_if_no_credentials", lambda: None)

    out = tmp_path / "scan"
    assert cli.main(["yt-scan", "diet keto", "--summaries", "1", "--out", str(out)]) == 0
    assert len(watched) == 1  # --summaries caps Gemini calls
    for name in ("videos.json", "comments.json", "briefs.json", "report.json", "report.md", "usage.json"):
        assert (out / name).exists(), name
    assert "Private" not in (out / "comments.json").read_text()
    assert "1. [health] Keto dan asam urat" in capsys.readouterr().out


def test_yt_scan_survives_missing_gemini(tmp_path, monkeypatch, capsys):
    from carousel import gemini, insights

    monkeypatch.setattr(yt, "search_video_ids", lambda q, cfg, now: ["vidA"])
    monkeypatch.setattr(yt, "video_details", lambda ids: sample_videos()[:1])
    monkeypatch.setattr(yt, "top_comments", lambda vid, n: sample_comments())

    def no_sdk():
        raise gemini.GeminiError("Install the Gemini SDK")

    monkeypatch.setattr(gemini, "client", no_sdk)
    monkeypatch.setattr(insights, "analyze_demand", lambda *a, **k: (sample_report(), {"model": "m", "input_tokens": 1, "output_tokens": 1}))
    monkeypatch.setattr(cli, "_warn_if_no_credentials", lambda: None)
    assert cli.main(["yt-scan", "keto", "--out", str(tmp_path)]) == 0
    assert "continuing without video briefs" in capsys.readouterr().out
    assert json.loads((tmp_path / "briefs.json").read_text()) == {}


def test_yt_idea_health_routes_to_pubmed(tmp_path, monkeypatch):
    (tmp_path / "report.json").write_text(sample_report().model_dump_json())
    seen = {}
    monkeypatch.setattr(cli, "cmd_discover", lambda args, cfg: seen.update(query=args.query, days=args.days) or 0)
    assert cli.main(["yt-idea", str(tmp_path), "1"]) == 0
    assert seen == {"query": "ketogenic diet AND uric acid", "days": 365}


def test_yt_idea_freeform_drafts_and_renders(tmp_path, monkeypatch, capsys):
    from carousel import insights, render
    from carousel.schema import FreeformDraft

    (tmp_path / "report.json").write_text(sample_report().model_dump_json())
    blank = dict(kicker="", lead="", body="", big_number="", callout="", question="", note="")
    draft = FreeformDraft(series="Mitos Gym #1", footer="Edisi 1", caption="c", hashtags=["gym"], slides=[
        {**blank, "kind": "cover", "headline": "Mitos gym"},
        {**blank, "kind": "cta", "headline": "Akhir", "question": "Kamu setuju?"},
    ])
    monkeypatch.setattr(insights, "draft_freeform", lambda *a: (draft, {"model": "m", "input_tokens": 1, "output_tokens": 1}))
    monkeypatch.setattr(render, "render_freeform", lambda spec, d, cfg, out: [out / "slide-01.png"])
    monkeypatch.setattr(cli, "_warn_if_no_credentials", lambda: None)
    assert cli.main(["yt-idea", str(tmp_path), "2"]) == 0
    spec = json.loads((tmp_path / "idea-2" / "carousel.json").read_text())
    assert spec["theme"] == "noir" and spec["series"] == "Mitos Gym #1"
    assert "1 slides in" in capsys.readouterr().out


def test_yt_idea_rejects_bad_number(tmp_path):
    (tmp_path / "report.json").write_text(sample_report().model_dump_json())
    assert cli.main(["yt-idea", str(tmp_path), "9"]) == 1
