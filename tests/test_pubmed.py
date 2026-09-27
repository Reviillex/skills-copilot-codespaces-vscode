from carousel.config import PubMedConfig
from carousel.pubmed import build_query, classify_design, parse_pmc_body, parse_pubmed_xml

from .conftest import FIXTURES


def test_parse_pubmed_xml():
    cohort, review = parse_pubmed_xml((FIXTURES / "pubmed_efetch.xml").read_bytes())

    assert cohort.pmid == "11111111"
    assert cohort.title == "Coffee intake and atrial fibrillation: a prospective cohort study."
    assert cohort.journal == "JAMA Netw Open"
    assert cohort.year == "2026"
    assert cohort.authors == ["Santoso", "Lee"]
    assert cohort.doi == "10.1001/example.2026.1"
    assert cohort.pmcid == "PMC9999999"
    assert cohort.design == "cohort"
    assert cohort.is_observational
    assert "RESULTS: Among 10,512 participants" in cohort.abstract
    assert cohort.short_citation == "Santoso dkk., JAMA Netw Open 2026"

    assert review.year == "2025"  # from MedlineDate
    assert review.authors == ["Exercise Trialists Group"]
    assert review.design == "meta-analysis"
    assert review.short_citation == "Exercise Trialists Group, BMJ 2025"
    assert review.doi == "" and review.pmcid == ""


def test_parse_pmc_body_keeps_body_only():
    text, license_text = parse_pmc_body((FIXTURES / "pmc_article.xml").read_bytes())
    assert "We followed 10,512 adults" in text
    assert "Coffee intake was self-reported once at baseline." in text
    assert "Abstract text" not in text
    assert "Reference that should be excluded" not in text
    assert "CC-BY" in license_text


def test_parse_pmc_body_without_open_access_body():
    text, license_text = parse_pmc_body(b"<pmc-articleset><article><front/></article></pmc-articleset>")
    assert text == "" and license_text == ""


def test_classify_design():
    assert classify_design(["Randomized Controlled Trial"], "Effect of X") == "rct"
    assert classify_design([], "A randomised trial of walking") == "rct"
    assert classify_design([], "Screen time: a cross-sectional study") == "cross-sectional"
    assert classify_design([], "Some editorial") == "other"


def test_build_query_includes_filters():
    q = build_query(PubMedConfig(topics=["sleep", "coffee"], journals=["BMJ"]))
    assert '"meta-analysis"[pt]' in q
    assert '("sleep"[tiab] OR "coffee"[tiab])' in q
    assert '("BMJ"[ta])' in q
    assert "hasabstract" in q


def test_build_query_without_journal_filter():
    assert "[ta]" not in build_query(PubMedConfig(topics=["sleep"], journals=[]))
