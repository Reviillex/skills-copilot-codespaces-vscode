# Carousel pipeline

Turns one PubMed paper into an Instagram carousel (1080 × 1350 PNG slides + caption) in Bahasa Indonesia, for a general audience. Built for two posts a week, with a doctor reviewing every draft before it is published.

This is a pipeline that runs fixed steps in order, not an autonomous agent. Every step is fixed except the drafting, and nothing is posted automatically.

```
discover ──► draft ──► check ──► review ──► (you edit carousel.json) ──► check ──► render ──► post manually
 PubMed      Claude    rules      Claude                                  rules     Chromium
```

## What protects accuracy

| Guard | How | Cost |
|---|---|---|
| Citation cannot be invented | The reference slide and caption citation are built from PubMed metadata by code, never by the model | Free |
| Quotes must be real | Every slide carries English quotes that must appear verbatim in the source text (`checks.py`) | Free |
| Numbers must be sourced | Every number on a slide must appear in that slide's quotes; Indonesian `0,75` / `5.320` formats are matched to English `0.75` / `5,320` | Free |
| Mandatory structure | Hook first, takeaway last, at least one caveat slide | Free |
| Causal wording | "menyebabkan", "mencegah", "terbukti" flagged for cohort / case-control / cross-sectional designs | Free |
| Independent fact-check | A second Claude call reviews the Indonesian text against the whole source without seeing the drafter's quotes | ~$0.10 to 0.20 |
| You | `render` refuses to run while any check error remains | Your time |

Errors block rendering; warnings are for you to judge.

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'
playwright install chromium
export ANTHROPIC_API_KEY=...   # API billing is separate from a Claude.ai subscription
export NCBI_API_KEY=...        # optional; raises the PubMed rate limit
```

Edit `carousel.toml`: your Instagram handle, theme, contact email for NCBI, topics and journals.
Themes load their fonts from Google Fonts. For offline rendering, install the theme's fonts on your computer ([Plus Jakarta Sans](https://fonts.google.com/specimen/Plus+Jakarta+Sans) for `clinical`; [Montserrat](https://fonts.google.com/specimen/Montserrat) and [Inter](https://fonts.google.com/specimen/Inter) for `noir`); otherwise a system sans-serif is used.

Try the template without an API key: `carousel sample` renders a clearly labelled fictional example to `output/sample/`.

## Weekly routine (2 posts)

```bash
carousel discover                  # ranked list: meta-analysis > systematic review > RCT > observational
carousel draft 12345678            # fetch paper (PMC full text if open access), draft, check, fact-check
#   read output/<date>-pmid12345678/review.md and check.txt, edit carousel.json
carousel check output/<date>-pmid12345678
carousel render output/<date>-pmid12345678
#   post slides/*.png and slides/caption.txt on Instagram
```

Other commands: `carousel review <folder>` re-runs the fact-check after large edits; `carousel draft <pmid> --abstract-only` skips the full text; `carousel render <folder> --force` renders despite errors (not recommended).

### Output folder

| File | Contents |
|---|---|
| `paper.json` | Metadata and the exact source text the model saw |
| `carousel.json` | The draft; edit this by hand |
| `check.txt` | Deterministic check results |
| `review.md`, `review.json` | Fact-check verdict per slide, suggested fixes, omitted points |
| `usage.json` | Tokens and estimated cost per call |
| `slides/slide-NN.png`, `slides/caption.txt` | What you post |

## Themes and free-form carousels

Two themes ship: `clinical` (light, the default for health posts) and `noir` (dark editorial, derived from the "Kenapa Aku Suka" Dota 2 series). Switch per run with `carousel render <folder> --theme noir`, or set `[brand] theme` in `carousel.toml`.

For posts without a paper (opinion, hobby series), write the slides as JSON and render them with the same themes:

```bash
carousel freeform examples/dota-mekanik/carousel.json   # -> output/dota-mekanik/
```

Free-form carousels skip the evidence checks but still get style warnings (length, mixed pronouns). Tokens, color rules, slide kinds, figure classes and a pre-posting checklist are in [design/README.md](design/README.md).

## YouTube demand research (Claude + Gemini)

Finds what Indonesian viewers watch and ask about, then feeds ideas into the two pipelines above.

```
yt-scan "query" ──► YouTube Data API: most-viewed recent videos, stats, top comments (author names dropped)
                ──► Gemini: watches the top N videos by URL (summary, hook, structure, claims)
                ──► Claude: demand report (themes with verbatim comment quotes, questions, claims to verify, ideas)
yt-idea <folder> <n>
   health idea   ──► carousel discover --query "<PubMed terms>" ──► draft ──► check ──► render
   freeform idea ──► Claude drafts FreeformCarousel JSON ──► noir render
imagine "prompt" ──► Gemini image for a freeform slide figure
```

```bash
pip install -e '.[gemini]'
export YOUTUBE_API_KEY=...   # Google Cloud console, YouTube Data API v3
export GEMINI_API_KEY=...    # Google AI Studio
carousel yt-scan "diet keto" --days 30 --summaries 3
carousel yt-idea output/yt/<date>-diet-keto 2
carousel imagine "minimal isometric Dota 2 style map, dark" --out examples/<topic>/map.png --aspect 21:9
```

Why two models: Claude cannot watch a video or generate an image; Gemini does both. Claude does the reading, checking and writing, so the existing guards stay in one place.

Guards:
- Momentum is views per day, not total views, so a new video is not buried by an old one. Comments per 1,000 views measures engagement.
- Every quote in a demand theme must match a real comment verbatim; cited video ids must be in the sample (`report.md` lists failures).
- Comments and video briefs are treated as untrusted data: the prompt tells Claude never to follow instructions inside them.
- Commenter names never reach disk or a model.
- Claims from videos or comments land in "claims to verify", never in a carousel. Health ideas go through PubMed and the evidence checks; freeform drafts are told to avoid medical claims.
- `imagine` writes a `.txt` next to each image with the prompt and a reminder to use Instagram's AI label. Do not use it for clinical or anatomical visuals.

Limits: only public videos; YouTube gives no search-volume data, so demand is inferred from views and comments of videos that already exist; commenters are a vocal minority. Search costs 100 of the default 10,000 daily YouTube quota units; Gemini video input is billed per second of video, so `--summaries` caps how many videos it watches.

## Cost

Default model: Claude Opus 5 ($5 / $25 per million input / output tokens). A full-text paper costs roughly $0.30 to 0.60 for draft + review, about $3 to 5 a month at 8 to 9 carousels. `usage.json` records the real figure. The request opts into server-side refusal fallback (`fallbacks: "default"`), so a false-positive safety decline on a medical topic is retried on Anthropic's recommended fallback model instead of failing.

## Known limits

- Summaries built from an abstract only miss limitations reported in the full text; the draft flags this in `editor_notes`.
- The PubMed filter matches designs by publication type and title words; newly indexed records are sometimes misclassified. Check the design before drafting.
- A single study rarely justifies behaviour change on its own. Prefer meta-analyses and RCTs; treat observational findings as associations.
- Only text is used. Do not reuse figures from a paper unless its license (printed by `draft`) allows it.

## Development

```bash
python -m pytest -q        # offline; the render test is skipped if Chromium is not installed
```

Set `CAROUSEL_CHROMIUM=/path/to/chrome` to render with a specific Chromium binary.
