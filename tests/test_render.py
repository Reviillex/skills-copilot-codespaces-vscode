import os
import struct

import pytest

from carousel.config import Config
from carousel.render import build_freeform_html, build_paper_html, figure_markup, render, render_freeform, rich, themes
from carousel.schema import FreeformCarousel


def test_rich_escapes_and_highlights():
    assert str(rich("a **b** <c>")) == 'a <strong class="hl">b</strong> &lt;c&gt;'


def test_rich_bullets_and_paragraphs():
    assert str(rich("- satu\n- **dua**")) == '<ul><li>satu</li><li><strong class="hl">dua</strong></li></ul>'
    assert str(rich("baris satu\nbaris dua")) == "<p>baris satu</p><p>baris dua</p>"
    assert str(rich("")) == ""


def test_build_paper_html_adds_reference_slide(sample_carousel, sample_paper):
    html = build_paper_html(sample_carousel, sample_paper, Config())
    assert html.count('<section class="slide') == len(sample_carousel.slides) + 1
    assert "slide--reference" in html
    assert "PMID 00000000" in html
    assert "CONTOH FIKTIF" not in html
    assert "CONTOH FIKTIF" in build_paper_html(sample_carousel, sample_paper, Config(), sample=True)


def test_every_theme_defines_every_component_token():
    """base.css may only read tokens that each theme defines."""
    import re
    from importlib import resources

    folder = resources.files("carousel").joinpath("templates")
    used = set(re.findall(r"var\((--[\w-]+)", folder.joinpath("base.css").read_text()))
    optional = {"--content-justify", "--end-text-align", "--figure-height"}  # have fallbacks in base.css
    assert set(themes()) >= {"clinical", "noir"}
    for theme in themes():
        css = folder.joinpath("themes", f"{theme}.css").read_text()
        defined = set(re.findall(r"^\s*(--[\w-]+):", css, re.M))
        assert not (used - defined - optional), f"{theme} is missing {sorted(used - defined - optional)}"


def test_base_css_has_no_raw_colors_outside_sample_badge():
    import re
    from importlib import resources

    css = resources.files("carousel").joinpath("templates", "base.css").read_text()
    css = re.sub(r"\.sample \{[^}]*\}", "", css).replace("body { background: #777; }", "")
    assert not re.search(r"#[0-9a-fA-F]{3,6}\b", css)


def test_unknown_theme_is_rejected(sample_carousel, sample_paper):
    with pytest.raises(ValueError, match="Unknown theme"):
        build_paper_html(sample_carousel, sample_paper, Config(), theme="neon")


def test_freeform_html_inlines_svg_figure(tmp_path):
    (tmp_path / "fig.svg").write_text('<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg"><path class="fig-line"/></svg>')
    spec = FreeformCarousel(series="Seri #1", slides=[
        {"kind": "cover", "headline": "Judul **penting**"},
        {"kind": "text", "headline": "Isi", "body": "Teks", "figure": "fig.svg"},
        {"kind": "cta", "headline": "Akhir", "question": "Pendapatmu?", "note": "Simpan"},
    ])
    html = build_freeform_html(spec, tmp_path, Config())
    assert '<path class="fig-line"/>' in html and "<?xml" not in html
    assert "Seri #1" in html and "--coral-500" in html  # noir tokens
    assert html.count('<section class="slide') == 3


def test_figure_markup_rejects_unknown_type(tmp_path):
    (tmp_path / "fig.gif").write_bytes(b"GIF89a")
    with pytest.raises(ValueError, match="Unsupported figure"):
        figure_markup(tmp_path / "fig.gif")


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


@pytest.mark.skipif(not _launchable(), reason="Chromium not available (run `playwright install chromium`)")
def test_render_freeform_example(tmp_path):
    from pathlib import Path

    spec_path = Path(__file__).parent.parent / "examples" / "dota-mekanik" / "carousel.json"
    spec = FreeformCarousel.model_validate_json(spec_path.read_text(encoding="utf-8"))
    paths = render_freeform(spec, spec_path.parent, Config(), tmp_path)
    assert len(paths) == len(spec.slides)
    for p in paths:
        assert struct.unpack(">II", p.read_bytes()[16:24]) == (1080, 1350)
