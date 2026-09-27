"""Render a carousel to 1080x1350 PNGs (Instagram 4:5) with Jinja2 + headless Chromium."""

from __future__ import annotations

import os
import re
from pathlib import Path
from types import SimpleNamespace

from jinja2 import Environment, PackageLoader, select_autoescape
from markupsafe import Markup, escape

from .checks import caption_text
from .config import Config
from .pubmed import Paper
from .schema import Carousel

WIDTH, HEIGHT = 1080, 1350

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


def rich(text: str) -> Markup:
    """Escape, then turn **x** into highlights and '- ' lines into a bullet list."""
    html = str(escape(text))
    html = re.sub(r"\*\*(.+?)\*\*", r'<strong class="hl">\1</strong>', html)
    lines = [ln.strip() for ln in html.splitlines() if ln.strip()]
    if lines and all(ln.startswith("- ") for ln in lines):
        return Markup("<ul>" + "".join(f"<li>{ln[2:]}</li>" for ln in lines) + "</ul>")
    return Markup("".join(f"<p>{ln}</p>" for ln in lines) if len(lines) > 1 else (lines[0] if lines else ""))


def build_html(carousel: Carousel, paper: Paper, cfg: Config, sample: bool = False) -> str:
    env = Environment(loader=PackageLoader("carousel", "templates"), autoescape=select_autoescape(["j2", "html"]))
    env.filters["rich"] = rich
    slides = list(carousel.slides) + [SimpleNamespace(role="reference")]
    return env.get_template("carousel.html.j2").render(
        carousel=carousel,
        paper=paper,
        brand=cfg.brand,
        sapaan=cfg.writing.sapaan,
        slides=slides,
        total=len(slides),
        sample=sample,
    )


def render(carousel: Carousel, paper: Paper, cfg: Config, out_dir: Path, sample: bool = False) -> list[Path]:
    from playwright.sync_api import sync_playwright

    out_dir.mkdir(parents=True, exist_ok=True)
    html = build_html(carousel, paper, cfg, sample=sample)
    (out_dir / "slides.html").write_text(html, encoding="utf-8")
    (out_dir / "caption.txt").write_text(caption_text(carousel, paper) + "\n", encoding="utf-8")

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
            # Offline: the web font never loads; fall back to system sans-serif.
            page.set_content(html, wait_until="load")
        page.evaluate("document.fonts.ready.then(() => true)")
        page.evaluate(FIT_SCRIPT)
        for i, slide in enumerate(page.locator("section.slide").all(), start=1):
            path = out_dir / f"slide-{i:02d}.png"
            slide.screenshot(path=str(path))
            paths.append(path)
        browser.close()
    return paths
