from decimal import Decimal

from carousel.checks import check_carousel, has_errors, number_values, quote_in_source, normalize
from carousel.config import WritingConfig
from carousel.schema import Evidence

W = WritingConfig()


def messages(issues, level):
    return [i.message for i in issues if i.level == level]


def test_sample_passes(sample_carousel, sample_paper):
    assert check_carousel(sample_carousel, sample_paper, W) == []


def test_number_values_handles_both_conventions():
    assert number_values("0,75") == {Decimal("0.75")}
    assert number_values("0.75") == {Decimal("0.75")}
    assert number_values("5.320") == {Decimal("5.32"), Decimal("5320")}
    assert number_values("5,320") == {Decimal("5.32"), Decimal("5320")}
    assert number_values("1.234.567") == {Decimal("1234567")}
    assert number_values("1.234,5") == {Decimal("1234.5")}
    assert Decimal("100") in number_values("100")


def test_quote_matching_is_verbatim_but_whitespace_and_dash_tolerant():
    source = normalize("Walking improved sleep  quality (mean difference −1.8 points).")
    assert quote_in_source("walking improved sleep quality", source)
    assert quote_in_source("mean difference -1.8 points", source)
    assert quote_in_source("Walking improved ... -1.8 points", source)
    assert not quote_in_source("Walking greatly improved sleep quality", source)
    assert not quote_in_source("...", source)


def test_paraphrased_quote_is_an_error(sample_carousel, sample_paper):
    sample_carousel.slides[2].evidence = [Evidence(quote="People fell asleep 9 minutes faster.")]
    issues = check_carousel(sample_carousel, sample_paper, W)
    assert has_errors(issues)
    assert any("not found verbatim" in m for m in messages(issues, "error"))


def test_invented_number_is_an_error(sample_carousel, sample_paper):
    sample_carousel.slides[3].headline = "Skor tidur membaik **25%**"
    issues = check_carousel(sample_carousel, sample_paper, W)
    assert any("number 25 does not appear" in m for m in messages(issues, "error"))


def test_number_from_elsewhere_in_source_is_a_warning(sample_carousel, sample_paper):
    # 1.480 is in the source, but not in the number slide's own quote.
    sample_carousel.slides[2].body = "Hasil dari 1.480 peserta."
    issues = check_carousel(sample_carousel, sample_paper, W)
    assert not has_errors(issues)
    assert any("1.480 is in the source but not in this slide" in m for m in messages(issues, "warning"))


def test_structure_errors(sample_carousel, sample_paper):
    sample_carousel.slides = [s for s in sample_carousel.slides if s.role != "caveat"]
    sample_carousel.slides.reverse()
    errors = messages(check_carousel(sample_carousel, sample_paper, W), "error")
    assert any("no caveat slide" in m for m in errors)
    assert any("first slide must be the hook" in m for m in errors)
    assert any("last content slide must be the takeaway" in m for m in errors)
    assert any("content slides; expected" in m for m in errors)


def test_causal_wording_flagged_only_for_observational(sample_carousel, sample_paper):
    sample_carousel.slides[3].body = "Jalan kaki mencegah insomnia."
    assert not any("causal word" in m for m in messages(check_carousel(sample_carousel, sample_paper, W), "warning"))

    sample_paper.design = "cohort"
    warnings = messages(check_carousel(sample_carousel, sample_paper, W), "warning")
    assert any("causal word 'mencegah'" in m for m in warnings)


def test_overclaim_words_use_word_boundaries(sample_carousel, sample_paper):
    sample_carousel.slides[3].body = "Pastikan tidur cukup."  # 'pastikan' is not 'pasti'
    assert not any("overclaiming" in m for m in messages(check_carousel(sample_carousel, sample_paper, W), "warning"))
    sample_carousel.slides[3].body = "Hasilnya pasti sama untuk semua orang."
    assert any("overclaiming word 'pasti'" in m for m in messages(check_carousel(sample_carousel, sample_paper, W), "warning"))


def test_length_limits_are_warnings(sample_carousel, sample_paper):
    sample_carousel.slides[1].body = " ".join(["kata"] * 60)
    issues = check_carousel(sample_carousel, sample_paper, W)
    assert any("body has 60 words" in m for m in messages(issues, "warning"))
