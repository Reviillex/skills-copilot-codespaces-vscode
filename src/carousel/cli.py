"""Command line: discover -> draft (+check +review) -> edit JSON by hand -> check -> render."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import urllib.error
from importlib import resources
from pathlib import Path

from .checks import check_carousel, has_errors
from .config import Config, load_config
from .pubmed import DESIGN_RANK, Paper, fetch_paper, fetch_papers, search
from .schema import Carousel, Review


def _load(folder: Path) -> tuple[Paper, Carousel]:
    paper = Paper.load(folder / "paper.json")
    carousel = Carousel.model_validate_json((folder / "carousel.json").read_text(encoding="utf-8"))
    return paper, carousel


def _run_checks(folder: Path, cfg: Config) -> bool:
    """Print and save deterministic check results; return True if there are no errors."""
    paper, carousel = _load(folder)
    issues = check_carousel(carousel, paper, cfg.writing)
    lines = [str(i) for i in issues] or ["No issues."]
    (folder / "check.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return not has_errors(issues)


def _warn_if_no_credentials() -> None:
    if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
        print("Note: ANTHROPIC_API_KEY is not set; the call only works if you are logged in with `ant auth login`.")


def _append_usage(folder: Path, step: str, record: dict) -> None:
    path = folder / "usage.json"
    log = json.loads(path.read_text()) if path.exists() else []
    log.append({"step": step, "at": dt.datetime.now().isoformat(timespec="seconds"), **record})
    path.write_text(json.dumps(log, indent=2), encoding="utf-8")


def _review_markdown(review: Review, carousel: Carousel) -> str:
    out = [f"# Review: {review.overall}", "", review.summary, ""]
    for r in review.slides:
        if r.verdict == "supported":
            continue
        headline = carousel.slides[r.slide - 1].headline if 0 < r.slide <= len(carousel.slides) else "?"
        out += [f"## Slide {r.slide}: {r.verdict}", f"- Current: {headline}", f"- Problem: {r.problem}",
                f"- Suggested: {r.suggested_fix}", ""]
    if review.caption_problems:
        out += ["## Caption"] + [f"- {p}" for p in review.caption_problems] + [""]
    if review.omitted_points:
        out += ["## Omitted from the carousel"] + [f"- {p}" for p in review.omitted_points] + [""]
    return "\n".join(out)


# --------------------------------------------------------------------------- commands


def cmd_discover(args: argparse.Namespace, cfg: Config) -> int:
    if args.days:
        cfg.pubmed.days = args.days
    try:
        pmids = search(cfg.pubmed)
        papers = sorted(fetch_papers(pmids, cfg.pubmed), key=lambda p: DESIGN_RANK.get(p.design, 99))
    except urllib.error.URLError as e:
        print(f"PubMed request failed: {e.reason}")
        return 1
    if not papers:
        print(f"No candidates in the last {cfg.pubmed.days} days. Try --days 14 or widen topics in carousel.toml.")
        return 0
    cfg.output_dir.mkdir(parents=True, exist_ok=True)
    out = cfg.output_dir / f"candidates-{dt.date.today():%Y%m%d}.json"
    out.write_text(
        json.dumps([{"pmid": p.pmid, "design": p.design, "journal": p.journal, "title": p.title,
                     "open_access": bool(p.pmcid)} for p in papers], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"{'PMID':<10} {'design':<18} {'OA':<3} {'journal':<24} title")
    for p in papers:
        print(f"{p.pmid:<10} {p.design:<18} {'yes' if p.pmcid else '-':<3} {p.journal[:24]:<24} {p.title[:90]}")
    print(f"\nSaved to {out}. Next: carousel draft <PMID>")
    return 0


def cmd_draft(args: argparse.Namespace, cfg: Config) -> int:
    import anthropic

    from .llm import DraftError, draft_carousel, review_carousel, usage_line

    folder = args.out or cfg.output_dir / f"{dt.date.today():%Y-%m-%d}-pmid{args.pmid}"
    if (folder / "carousel.json").exists() and not args.overwrite:
        print(f"{folder}/carousel.json exists (maybe with your edits). Use --overwrite to redraft.")
        return 1
    _warn_if_no_credentials()
    try:
        paper = fetch_paper(args.pmid, cfg.pubmed, with_full_text=not args.abstract_only)
    except (urllib.error.URLError, LookupError) as e:
        print(f"Could not fetch PMID {args.pmid}: {getattr(e, 'reason', e)}")
        return 1
    folder.mkdir(parents=True, exist_ok=True)
    paper.save(folder / "paper.json")
    scope = "full text" if paper.full_text else "abstract only"
    print(f"Paper: {paper.short_citation} | {paper.design} | {scope}")
    if paper.license:
        print(f"License: {paper.license[:160]}")

    client = anthropic.Anthropic()
    try:
        carousel, usage = draft_carousel(client, cfg, paper)
        (folder / "carousel.json").write_text(carousel.model_dump_json(indent=2), encoding="utf-8")
        _append_usage(folder, "draft", usage)
        print(f"Draft saved. {usage_line(usage)}\n")

        print("Deterministic checks:")
        _run_checks(folder, cfg)

        if not args.no_review:
            review, usage = review_carousel(client, cfg, paper, carousel)
            (folder / "review.json").write_text(review.model_dump_json(indent=2), encoding="utf-8")
            (folder / "review.md").write_text(_review_markdown(review, carousel), encoding="utf-8")
            _append_usage(folder, "review", usage)
            print(f"\nReview: {review.overall}. {review.summary}\n({usage_line(usage)})")
    except DraftError as e:
        print(f"Stopped: {e}")
        return 1
    except anthropic.AuthenticationError:
        print("Anthropic API key missing or invalid. Set ANTHROPIC_API_KEY.")
        return 1

    print(f"\nNext: edit {folder}/carousel.json, then `carousel check {folder}` and `carousel render {folder}`.")
    return 0


def cmd_check(args: argparse.Namespace, cfg: Config) -> int:
    return 0 if _run_checks(args.folder, cfg) else 1


def cmd_review(args: argparse.Namespace, cfg: Config) -> int:
    import anthropic

    from .llm import review_carousel, usage_line

    _warn_if_no_credentials()
    paper, carousel = _load(args.folder)
    review, usage = review_carousel(anthropic.Anthropic(), cfg, paper, carousel)
    (args.folder / "review.json").write_text(review.model_dump_json(indent=2), encoding="utf-8")
    (args.folder / "review.md").write_text(_review_markdown(review, carousel), encoding="utf-8")
    _append_usage(args.folder, "review", usage)
    print(f"Review: {review.overall}. {review.summary}\nDetails: {args.folder / 'review.md'} ({usage_line(usage)})")
    return 0


def cmd_render(args: argparse.Namespace, cfg: Config) -> int:
    from .render import render

    if not _run_checks(args.folder, cfg) and not args.force:
        print("\nRendering blocked by errors above. Fix carousel.json or pass --force.")
        return 1
    paper, carousel = _load(args.folder)
    paths = render(carousel, paper, cfg, args.folder / "slides")
    print(f"\n{len(paths)} slides + caption.txt in {args.folder / 'slides'}")
    return 0


def cmd_sample(args: argparse.Namespace, cfg: Config) -> int:
    """Render the bundled fictional example: no API key or network needed (except web font)."""
    from .render import render

    sample = resources.files("carousel").joinpath("sample")
    paper = Paper(**json.loads(sample.joinpath("paper.json").read_text(encoding="utf-8")))
    carousel = Carousel.model_validate_json(sample.joinpath("carousel.json").read_text(encoding="utf-8"))
    out = cfg.output_dir / "sample"
    paths = render(carousel, paper, cfg, out, sample=True)
    print(f"{len(paths)} slides rendered to {out}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="carousel", description=__doc__)
    parser.add_argument("--config", type=Path, default=None, help="path to carousel.toml")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("discover", help="list recent candidate papers from PubMed")
    p.add_argument("--days", type=int, default=0)
    p.set_defaults(func=cmd_discover)

    p = sub.add_parser("draft", help="fetch a paper and draft, check and review a carousel")
    p.add_argument("pmid")
    p.add_argument("--out", type=Path, default=None)
    p.add_argument("--abstract-only", action="store_true", help="skip PMC full text")
    p.add_argument("--no-review", action="store_true", help="skip the fact-check call")
    p.add_argument("--overwrite", action="store_true")
    p.set_defaults(func=cmd_draft)

    p = sub.add_parser("check", help="re-run deterministic checks after editing carousel.json")
    p.add_argument("folder", type=Path)
    p.set_defaults(func=cmd_check)

    p = sub.add_parser("review", help="re-run the fact-check call")
    p.add_argument("folder", type=Path)
    p.set_defaults(func=cmd_review)

    p = sub.add_parser("render", help="render PNG slides and caption.txt")
    p.add_argument("folder", type=Path)
    p.add_argument("--force", action="store_true", help="render despite check errors")
    p.set_defaults(func=cmd_render)

    p = sub.add_parser("sample", help="render the bundled fictional example")
    p.set_defaults(func=cmd_sample)

    args = parser.parse_args(argv)
    cfg = load_config(args.config)
    return args.func(args, cfg)


if __name__ == "__main__":
    sys.exit(main())
