"""Render slides to 1080x1350 PNGs (Instagram 4:5) with Jinja2 + headless Chromium.

Two inputs share one template and one token-based theme system:
- health carousels (Carousel + Paper), converted to RenderSlide by ``slides_from_paper``;
- free-form carousels (FreeformCarousel), written directly as RenderSlide.
"""

from __future__ import annotations

import base64
import os
import re
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

from jinja2 import Environment, PackageLoader, select_autoescape
from markupsafe import Markup, escape

from .checks import caption_text
from .config import Config
from .pubmed import Paper
from .schema import Carousel, FreeformCarousel, RenderSlide

WIDTH, HEIGHT = 1080, 1350
DISCLAIMER = (
    "Konten ini untuk edukasi, bukan pengganti konsultasi dengan dokter. "
    "Hasil satu penelitian belum tentu berlaku untuk setiap orang."
)
IMAGE_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}

# Shrinks .fit text on any slide whose content overflows, down to 60% of the base size.
FIT_SCRIPT = """
() => {
  for (const content of document.querySelectorAll('.content')) {
    const els = [...content.querySelectorAll('.fit')];
    const base = els.map(e => parseFloat(getComputedStyle(e).fontSize));
    let scale = 1;
    while (content.scrollHeight > content.clientHeight && scale > 0.6) {
      scale -= 0.04;
      els.forEach((e, i) => { e.style.fontSize = (base[i] * scale) + 'px'; });
    }
  }
}
"""


@dataclass
class Deck:
    tag: str  # top-left label: topic tag or series name
    handle: str
    foot: str  # footer-left text from slide 2 on: citation or series footer
    sample: bool = False


def themes() -> list[str]:
    folder = resources.files("carousel").joinpath("templates", "themes")
    return sorted(p.name.removesuffix(".css") for p in folder.iterdir() if p.name.endswith(".css"))


def _theme_css(theme: str) -> str:
    if theme not in themes():
        raise ValueError(f"Unknown theme '{theme}'. Available: {', '.join(themes())}")
    return resources.files("carousel").joinpath("templates", "themes", f"{theme}.css").read_text(encoding="utf-8")


def rich(text: str) -> Markup:
    """Escape, then turn **x** into highlights and '- ' lines into a bullet list."""
    html = str(escape(text))
    html = re.sub(r"\*\*(.+?)\*\*", r'<strong class="hl">\1</strong>', html)
    lines = [ln.strip() for ln in html.splitlines() if ln.strip()]
    if lines and all(ln.startswith("- ") for ln in lines):
        return Markup("<ul>" + "".join(f"<li>{ln[2:]}</li>" for ln in lines) + "</ul>")
    return Markup("".join(f"<p>{ln}</p>" for ln in lines) if len(lines) > 1 else (lines[0] if lines else ""))


def figure_markup(path: Path) -> Markup:
    """Inline an SVG (so it can use the theme's .fig-* classes) or embed a bitmap."""
    suffix = path.suffix.lower()
    if suffix == ".svg":
        svg = path.read_text(encoding="utf-8")
        return Markup(re.sub(r"<\?xml[^>]*\?>", "", svg).strip())
    if suffix in IMAGE_TYPES:
        data = base64.b64encode(path.read_bytes()).decode()
        return Markup(f'<img alt="" src="data:{IMAGE_TYPES[suffix]};base64,{data}">')
    raise ValueError(f"Unsupported figure type: {path.name} (use .svg, .png, .jpg or .webp)")


def build_html(slides: list[RenderSlide], deck: Deck, theme: str) -> str:
    env = Environment(loader=PackageLoader("carousel", "templates"), autoescape=select_autoescape(["j2", "html"]))
    env.filters["rich"] = rich
    base_css = resources.files("carousel").joinpath("templates", "base.css").read_text(encoding="utf-8")
    return env.get_template("carousel.html.j2").render(
        slides=slides, deck=deck, theme_css=Markup(_theme_css(theme)), base_css=Markup(base_css)
    )


# --------------------------------------------------------------------------- inputs


def slides_from_paper(carousel: Carousel, paper: Paper, cfg: Config) -> list[RenderSlide]:
    out: list[RenderSlide] = []
    for s in carousel.slides:
        if s.role == "hook":
            out.append(RenderSlide(kind="cover", kicker=carousel.evidence_label, headline=s.headline, lead=s.body))
        elif s.role == "number":
            out.append(RenderSlide(kind="number", big_number=s.big_number, headline=s.headline, body=s.body))
        elif s.role == "caveat":
            out.append(RenderSlide(kind="caveat", kicker="Catatan penting", headline=s.headline, body=s.body))
        elif s.role == "takeaway":
            out.append(RenderSlide(kind="text", kicker=f"Apa artinya untuk {cfg.writing.sapaan}?",
                                   headline=s.headline, body=s.body))
        else:
            out.append(RenderSlide(kind="text", headline=s.headline, body=s.body))
    out.append(RenderSlide(kind="reference", kicker="Sumber", lead=paper.full_citation,
                           note=DISCLAIMER, headline=cfg.brand.author))
    return out


def build_paper_html(carousel: Carousel, paper: Paper, cfg: Config, theme: str | None = None,
                     sample: bool = False) -> str:
    deck = Deck(tag=carousel.topic_tag, handle=cfg.brand.handle, foot=paper.short_citation, sample=sample)
    return build_html(slides_from_paper(carousel, paper, cfg), deck, theme or cfg.brand.theme)


def build_freeform_html(spec: FreeformCarousel, spec_dir: Path, cfg: Config, theme: str | None = None) -> str:
    slides = [
        s.model_copy(update={"figure": figure_markup(spec_dir / s.figure)}) if s.figure else s
        for s in spec.slides
    ]
    deck = Deck(tag=spec.series, handle=cfg.brand.handle, foot=spec.footer)
    return build_html(slides, deck, theme or spec.theme)


# --------------------------------------------------------------------------- output


def screenshot(html: str, out_dir: Path) -> list[Path]:
    from playwright.sync_api import sync_playwright

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "slides.html").write_text(html, encoding="utf-8")
    for old in out_dir.glob("slide-*.png"):
        old.unlink()

    launch_args = {}
    if os.environ.get("CAROUSEL_CHROMIUM"):
        launch_args["executable_path"] = os.environ["CAROUSEL_CHROMIUM"]

    paths: list[Path] = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(**launch_args)
        page = browser.new_page(viewport={"width": WIDTH, "height": HEIGHT}, device_scale_factor=1)
        try:
            page.set_content(html, wait_until="networkidle", timeout=20000)
        except Exception:
            # Offline: web fonts never load; system fallbacks from the theme are used.
            page.set_content(html, wait_until="load")
        page.evaluate("document.fonts.ready.then(() => true)")
        page.evaluate(FIT_SCRIPT)
        for i, slide in enumerate(page.locator("section.slide").all(), start=1):
            path = out_dir / f"slide-{i:02d}.png"
            slide.screenshot(path=str(path))
            paths.append(path)
        browser.close()
    return paths


def render(carousel: Carousel, paper: Paper, cfg: Config, out_dir: Path, sample: bool = False,
           theme: str | None = None) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "caption.txt").write_text(caption_text(carousel, paper) + "\n", encoding="utf-8")
    return screenshot(build_paper_html(carousel, paper, cfg, theme=theme, sample=sample), out_dir)


def render_freeform(spec: FreeformCarousel, spec_dir: Path, cfg: Config, out_dir: Path,
                    theme: str | None = None) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    if spec.caption:
        tags = " ".join("#" + t.lstrip("#").replace(" ", "") for t in spec.hashtags)
        (out_dir / "caption.txt").write_text(f"{spec.caption.strip()}\n\n{tags}".strip() + "\n", encoding="utf-8")
    return screenshot(build_freeform_html(spec, spec_dir, cfg, theme=theme), out_dir)
