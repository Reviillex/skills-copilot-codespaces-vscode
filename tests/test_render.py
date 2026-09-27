import os
import struct

import pytest

from carousel.config import Config
from carousel.render import build_html, render, rich


def test_rich_escapes_and_highlights():
    assert str(rich("a **b** <c>")) == 'a <strong class="hl">b</strong> &lt;c&gt;'


def test_rich_bullets_and_paragraphs():
    assert str(rich("- satu\n- **dua**")) == '<ul><li>satu</li><li><strong class="hl">dua</strong></li></ul>'
    assert str(rich("baris satu\nbaris dua")) == "<p>baris satu</p><p>baris dua</p>"
    assert str(rich("")) == ""


def test_build_html_adds_reference_slide(sample_carousel, sample_paper):
    html = build_html(sample_carousel, sample_paper, Config())
    assert html.count('<section class="slide') == len(sample_carousel.slides) + 1
    assert "role-reference" in html
    assert "PMID 00000000" in html
    assert "CONTOH FIKTIF" not in html
    assert "CONTOH FIKTIF" in build_html(sample_carousel, sample_paper, Config(), sample=True)


def _launchable() -> bool:
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            kwargs = {"executable_path": os.environ["CAROUSEL_CHROMIUM"]} if os.environ.get("CAROUSEL_CHROMIUM") else {}
            pw.chromium.launch(**kwargs).close()
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _launchable(), reason="Chromium not available (run `playwright install chromium`)")
def test_render_png_size(sample_carousel, sample_paper, tmp_path):
    paths = render(sample_carousel, sample_paper, Config(), tmp_path)
    assert len(paths) == len(sample_carousel.slides) + 1
    for p in paths:
        width, height = struct.unpack(">II", p.read_bytes()[16:24])
        assert (width, height) == (1080, 1350)
    caption = (tmp_path / "caption.txt").read_text(encoding="utf-8")
    assert "Sumber:" in caption and "#edukasikesehatan" in caption
