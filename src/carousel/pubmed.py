"""PubMed / PMC access through NCBI E-utilities (search, abstract, open-access full text)."""

from __future__ import annotations

import json
import os
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .config import PubMedConfig

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
TOOL_NAME = "carousel-pipeline"

# Ordered from strongest to weakest design for a single-paper summary.
DESIGN_RANK = {
    "meta-analysis": 1,
    "systematic-review": 2,
    "rct": 3,
    "cohort": 4,
    "case-control": 5,
    "cross-sectional": 6,
    "other": 7,
}
OBSERVATIONAL = {"cohort", "case-control", "cross-sectional"}

DESIGN_LABEL_ID = {
    "meta-analysis": "Meta-analisis",
    "systematic-review": "Tinjauan sistematis",
    "rct": "Uji klinis acak (RCT)",
    "cohort": "Studi kohort",
    "case-control": "Studi kasus-kontrol",
    "cross-sectional": "Studi potong lintang",
    "other": "Studi",
}


@dataclass
class Paper:
    pmid: str
    title: str
    abstract: str
    journal: str
    year: str
    authors: list[str] = field(default_factory=list)
    doi: str = ""
    pmcid: str = ""
    pub_types: list[str] = field(default_factory=list)
    design: str = "other"
    full_text: str = ""
    license: str = ""

    @property
    def is_observational(self) -> bool:
        return self.design in OBSERVATIONAL

    @property
    def short_citation(self) -> str:
        """e.g. 'Nguyen dkk., JAMA Netw Open 2026' (Indonesian 'dkk.' = et al.)."""
        if not self.authors:
            lead = "Anonim"
        elif len(self.authors) == 1:
            lead = self.authors[0]
        else:
            lead = f"{self.authors[0]} dkk."
        return f"{lead}, {self.journal} {self.year}".strip()

    @property
    def full_citation(self) -> str:
        parts = [self.short_citation + ".", self.title.rstrip(".") + "."]
        if self.doi:
            parts.append(f"doi:{self.doi}")
        parts.append(f"PMID {self.pmid}")
        return " ".join(parts)

    def source_text(self) -> str:
        """Exact text the model reads; quote checks run against this same string."""
        sections = [f"TITLE: {self.title}", f"ABSTRACT:\n{self.abstract}"]
        if self.full_text:
            sections.append(f"FULL TEXT:\n{self.full_text}")
        return "\n\n".join(sections)

    def save(self, path: Path) -> None:
        path.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "Paper":
        return cls(**json.loads(path.read_text(encoding="utf-8")))


# --------------------------------------------------------------------------- query


def build_query(cfg: PubMedConfig) -> str:
    """PubMed query: strong designs x daily-life topics x (optional) journal list.

    Newly added records often lack indexer-assigned publication types, so the
    design filter also matches title words.
    """
    design = (
        '("meta-analysis"[pt] OR "systematic review"[pt] OR "randomized controlled trial"[pt]'
        ' OR meta-analysis[ti] OR "systematic review"[ti] OR randomized[ti] OR randomised[ti])'
    )
    clauses = [design, "hasabstract", "english[la]"]
    if cfg.query:
        # Idea-driven search (e.g. from a YouTube demand report): the design filter
        # still applies, the topic list and journal list do not.
        return " AND ".join(clauses + [f"({cfg.query})"])
    if cfg.topics:
        clauses.append("(" + " OR ".join(f'"{t}"[tiab]' for t in cfg.topics) + ")")
    if cfg.journals:
        clauses.append("(" + " OR ".join(f'"{j}"[ta]' for j in cfg.journals) + ")")
    return " AND ".join(clauses)


# --------------------------------------------------------------------------- http


def _get(endpoint: str, params: dict[str, str], email: str) -> bytes:
    params = {**params, "tool": TOOL_NAME}
    if email:
        params["email"] = email
    api_key = os.environ.get("NCBI_API_KEY")
    if api_key:
        params["api_key"] = api_key
    url = f"{EUTILS}/{endpoint}?{urllib.parse.urlencode(params)}"
    with urllib.request.urlopen(url, timeout=30) as resp:
        body = resp.read()
    # NCBI allows 3 requests/s without a key, 10 with one.
    time.sleep(0.12 if api_key else 0.35)
    return body


def search(cfg: PubMedConfig) -> list[str]:
    body = _get(
        "esearch.fcgi",
        {
            "db": "pubmed",
            "term": build_query(cfg),
            "retmode": "json",
            "retmax": str(cfg.max_candidates),
            "datetype": "edat",
            "reldate": str(cfg.days),
            "sort": "relevance",
        },
        cfg.email,
    )
    return json.loads(body)["esearchresult"]["idlist"]


def fetch_papers(pmids: list[str], cfg: PubMedConfig) -> list[Paper]:
    if not pmids:
        return []
    body = _get(
        "efetch.fcgi",
        {"db": "pubmed", "id": ",".join(pmids), "retmode": "xml"},
        cfg.email,
    )
    return parse_pubmed_xml(body)


def fetch_paper(pmid: str, cfg: PubMedConfig, with_full_text: bool = True) -> Paper:
    papers = fetch_papers([pmid], cfg)
    if not papers:
        raise LookupError(f"PMID {pmid} not found on PubMed")
    paper = papers[0]
    if with_full_text and paper.pmcid:
        body = _get(
            "efetch.fcgi",
            {"db": "pmc", "id": paper.pmcid.removeprefix("PMC"), "retmode": "xml"},
            cfg.email,
        )
        paper.full_text, paper.license = parse_pmc_body(body)
    return paper


# --------------------------------------------------------------------------- parsing


def _text(el: ET.Element | None) -> str:
    return " ".join("".join(el.itertext()).split()) if el is not None else ""


def classify_design(pub_types: list[str], title: str) -> str:
    pts = {p.lower() for p in pub_types}
    t = title.lower()
    if "meta-analysis" in pts or "meta-analysis" in t or "meta-analyses" in t:
        return "meta-analysis"
    if "systematic review" in pts or "systematic review" in t:
        return "systematic-review"
    if "randomized controlled trial" in pts or "randomized" in t or "randomised" in t:
        return "rct"
    if "cohort" in t or "prospective" in t or "longitudinal" in t:
        return "cohort"
    if "case-control" in t:
        return "case-control"
    if "cross-sectional" in t:
        return "cross-sectional"
    return "other"


def parse_pubmed_xml(body: bytes) -> list[Paper]:
    root = ET.fromstring(body)
    papers: list[Paper] = []
    for art in root.iter("PubmedArticle"):
        cit = art.find("MedlineCitation")
        article = cit.find("Article")
        title = _text(article.find("ArticleTitle"))

        chunks = []
        for ab in article.findall("Abstract/AbstractText"):
            label = ab.get("Label")
            txt = _text(ab)
            chunks.append(f"{label}: {txt}" if label else txt)
        abstract = "\n".join(chunks)

        journal = _text(article.find("Journal/ISOAbbreviation")) or _text(article.find("Journal/Title"))
        year = _text(article.find("Journal/JournalIssue/PubDate/Year"))
        if not year:
            medline_date = _text(article.find("Journal/JournalIssue/PubDate/MedlineDate"))
            year = medline_date[:4]

        authors = []
        for au in article.findall("AuthorList/Author"):
            last = _text(au.find("LastName")) or _text(au.find("CollectiveName"))
            if last:
                authors.append(last)

        pub_types = [_text(p) for p in article.findall("PublicationTypeList/PublicationType")]

        doi = pmcid = ""
        for aid in art.findall("PubmedData/ArticleIdList/ArticleId"):
            if aid.get("IdType") == "doi":
                doi = _text(aid)
            elif aid.get("IdType") == "pmc":
                pmcid = _text(aid)

        papers.append(
            Paper(
                pmid=_text(cit.find("PMID")),
                title=title,
                abstract=abstract,
                journal=journal,
                year=year,
                authors=authors,
                doi=doi,
                pmcid=pmcid,
                pub_types=pub_types,
                design=classify_design(pub_types, title),
            )
        )
    return papers


def parse_pmc_body(body: bytes) -> tuple[str, str]:
    """Return (body text, license text) from a PMC JATS record.

    Non open-access records come back without <body>; the result is then ("", license).
    """
    root = ET.fromstring(body)
    license_text = _text(root.find(".//permissions/license"))
    body_el = root.find(".//body")
    if body_el is None:
        return "", license_text
    paragraphs = []
    for el in body_el.iter():
        if el.tag in {"title", "p"}:
            txt = _text(el)
            if txt:
                paragraphs.append(txt)
    return "\n".join(paragraphs), license_text
