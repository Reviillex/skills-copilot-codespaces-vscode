# Carousel design system

Every carousel, health or hobby, renders through one template (`src/carousel/templates/carousel.html.j2`), one component stylesheet (`base.css`) and one theme file. The template and components never contain colors or font names. A theme file supplies them as tokens, so a new look means a new theme file, not a new template.

`reference/dota-mekanik-v1/` holds the original "Kenapa Aku Suka #1" slides (1, 2, 3, 4 and 10 of 10) that the `noir` theme was derived from. `examples/dota-mekanik/carousel.json` is the same copy rebuilt in this system.

## Tokens

Theme files live in `src/carousel/templates/themes/<name>.css` and have three layers:

| Layer | Example | Rule |
|---|---|---|
| Primitive | `--coral-500: #FF5A5F` | Raw values. Only the semantic layer reads them. |
| Semantic | `--color-emphasis: var(--coral-500)` | What a color means. |
| Component | `--callout-fg: var(--color-emphasis)` | What a component uses. `base.css` reads only this layer. |

`tests/test_render.py` fails if `base.css` reads a token that some theme does not define, or if `base.css` contains a raw hex color.

## Color meaning (noir)

One meaning per accent, applied the same way on every slide:

- **Coral (`--color-emphasis`)**: the word or fact that carries the stakes. Headline highlights (`**...**`), callouts, danger markers in figures, bullets.
- **Amber (`--color-signal`)**: orientation and action. Kicker pill, eyebrow labels, progress bar, the call-to-action question, "safe" or "goal" markers in figures.
- Everything else is grayscale. If a slide needs a third color, the slide is doing too much.

## Type scale (noir)

| Role | Font | Size / line height | Notes |
|---|---|---|---|
| Cover headline | Montserrat 900 | 88 / 1.0 | Uppercase, 4 lines maximum |
| Slide headline | Montserrat 800 | 68 / 1.08 | 3 lines maximum |
| Lead (context) | Inter 400 | 42 / 1.45 | Muted gray, always above the body |
| Body (the point) | Inter 500 | 50 / 1.38 | Primary white |
| Callout | Inter 600 | 34 / 1.35 | One sentence |
| CTA question | Inter 700 | 60 / 1.3 | Amber |
| Labels | Inter 700 | 24 to 28, tracked 0.08 to 0.12em | Uppercase |

The headline-to-body ratio stays near 1.4. Below about 1.2 the eye cannot tell which line to read first. When text overflows, the renderer shrinks it (down to 60%) rather than cutting it; if a slide shrinks, cut words instead of accepting the smaller text.

## Layout

- 1080 × 1350 (4:5). 80 px safe margin on all four sides.
- Top row on every slide: series name left, handle right. Screenshots of a single slide still carry credit.
- Footer on every slide, same position: context text left, progress bar + `n/N` right. The cover's footer says "Geser untuk lanjut".
- Content slides anchor the headline at the same height, so the eye does not hunt for it while swiping. The cover and the closing slide are centered.
- No fake buttons. A static image cannot be tapped; button-styled labels compete with the real call to action.

## Slide kinds

A free-form carousel is a JSON file in the `FreeformCarousel` shape (`src/carousel/schema.py`):

| `kind` | Fields used |
|---|---|
| `cover` | `kicker` (pill), `headline`, `lead` |
| `text` | `kicker` (optional eyebrow; without it a coral marker bar shows), `headline`, `lead`, `body`, `callout`, `figure` |
| `number` | `big_number`, `headline`, `body` |
| `caveat` | `kicker`, `headline`, `body` |
| `cta` | `headline`, `question`, `note` (save prompt) |

Top-level fields: `series`, `theme`, `footer`, `caption`, `hashtags`, `slides`.

## Figures

`figure` points to an SVG, PNG, JPG or WebP file next to the JSON. SVGs are inlined, so they can use theme classes and restyle with the theme:

| Class | Use |
|---|---|
| `fig-line` | Terrain, axes, structure |
| `fig-route` | Dotted path (routes, movement) |
| `fig-danger` | Dotted coral line (attack, risk) |
| `fig-dot`, `fig-dot-signal`, `fig-dot-danger` | Points |
| `fig-label`, `fig-label-signal`, `fig-label-danger` | Labels (26 to 28 px; smaller is unreadable on a phone) |
| `fig-box-danger` | Box behind a coral label |

Figures render 280 px tall at full width. Keep labels clear of lines, and use only labels that mean something: decorative coordinates or fake data read as noise.

## New carousel in a series

```bash
cp -r examples/dota-mekanik examples/<next-topic>
# edit examples/<next-topic>/carousel.json
carousel freeform examples/<next-topic>/carousel.json
```

The command prints style warnings (headline length, text length, mixed pronouns) and never blocks. Slides land in `output/<next-topic>/`.

## Checklist before posting

1. The cover names the subject or shows it. A curiosity gap only works on people who already follow you.
2. One idea per slide. If the headline promises vision and the body talks about the courier, split the slide.
3. One voice: pick `aku`/`kamu` or `gue`/`lo` for the whole series (the checker flags mixing).
4. Every factual claim is true for the current patch or source. Opinion is fine; a false fact costs credibility on the health posts too.
5. The closing question asks about the carousel's own topic, so comments continue the argument.
