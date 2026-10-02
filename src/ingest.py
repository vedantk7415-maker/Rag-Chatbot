"""
Phase 2 (part 1): Load and clean the source pages.

Pipeline so far:  Load (5 URLs) -> Clean -> data/raw/<slug>.txt

Chunking, embedding and ChromaDB storage are added in later phases.

Design note
-----------
The 5 Groww pages are Next.js apps. All the facts we need (expense ratio, exit
load, minimum SIP, benchmark, riskometer, ELSS lock-in, ...) are already present
as structured fields inside the page's `__NEXT_DATA__` JSON payload. We read that
payload instead of scraping rendered text, because:

  1. Rendered text is one giant blob mixed with nav menus, fund comparators and
     marketing widgets - it produces noisy chunks with no fact labels.
  2. Structured fields give us exact values, so a fact never gets separated from
     its own label ("Expense ratio" stays next to "1.04%").

Deliberate exclusion (per the brief's "no performance claims" rule):
`stats` (fund returns, category average, rank within category), `holdings` and
`peerComparison` are NEVER ingested. The bot refuses return questions and points
to the official factsheet instead.
"""

from __future__ import annotations

import csv
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

import requests
from bs4 import BeautifulSoup

# --------------------------------------------------------------------------- #
# Paths
# --------------------------------------------------------------------------- #

ROOT = Path(__file__).resolve().parent.parent
SOURCES_CSV = ROOT / "data" / "sources.csv"
RAW_DIR = ROOT / "data" / "raw"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
TIMEOUT = 30


# --------------------------------------------------------------------------- #
# Source list
# --------------------------------------------------------------------------- #


@dataclass
class Source:
    source_type: str  # "scheme" or "guide"
    scheme_name: str
    category: str
    url: str

    @property
    def slug(self) -> str:
        """hdfc-large-cap-fund-direct-growth -> hdfc_large_cap_fund_direct_growth"""
        base = self.url.rstrip("/").rsplit("/", 1)[-1]
        return re.sub(r"[^a-z0-9]+", "_", base.lower()).strip("_")


def read_sources(csv_path: Path = SOURCES_CSV) -> list[Source]:
    """Read the source rows from data/sources.csv."""
    with csv_path.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    if not rows:
        raise ValueError(f"No sources found in {csv_path}")
    schemes = [r for r in rows if r["source_type"].strip() == "scheme"]
    if len(schemes) != 5:
        raise ValueError(f"Expected exactly 5 scheme sources, found {len(schemes)}")
    return [
        Source(
            source_type=r["source_type"].strip(),
            scheme_name=r["scheme_name"].strip(),
            category=r["category"].strip(),
            url=r["url"].strip(),
        )
        for r in rows
    ]


# --------------------------------------------------------------------------- #
# Fetch + extract
# --------------------------------------------------------------------------- #


def fetch_html(url: str, session: requests.Session | None = None) -> str:
    """GET a page with a browser-like User-Agent."""
    session = session or requests.Session()
    resp = session.get(url, headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT)
    resp.raise_for_status()
    # requests defaults to ISO-8859-1 when there is no charset in the header, which
    # mangles the smart quotes on these pages into U+FFFD. These pages are UTF-8.
    try:
        return resp.content.decode("utf-8")
    except UnicodeDecodeError:
        return resp.text


def extract_next_data(html: str) -> dict:
    """
    Pull the fund record out of the page's __NEXT_DATA__ JSON payload.

    Returns data.props.pageProps.mfServerSideData.
    """
    soup = BeautifulSoup(html, "html.parser")
    tag = soup.find("script", id="__NEXT_DATA__")
    if tag is None or not tag.string:
        raise ValueError("__NEXT_DATA__ not found - page structure may have changed")
    payload = json.loads(tag.string)
    record = payload["props"]["pageProps"]["mfServerSideData"]
    if not isinstance(record, dict) or "scheme_name" not in record:
        raise ValueError("Unexpected mfServerSideData shape")
    return record


SMART_CHARS = {
    "\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"',
    "\u2013": "-", "\u2014": "-", "\u2026": "...", "\u00a0": " ",
    "\ufffd": "'",
}

# Page furniture that carries no answering value and only adds noise to the vector.
BOILERPLATE_MARKERS = (
    "You may also want to know",
    "Disclaimer:",
    "Check More AMCs",
    "Download the App",
)


def strip_html(value: str | None) -> str:
    """Flatten an HTML fragment to plain ASCII text."""
    if not value:
        return ""
    text = BeautifulSoup(value, "html.parser").get_text(" ")
    for bad, good in SMART_CHARS.items():
        text = text.replace(bad, good)
    return re.sub(r"\s+", " ", text).strip()


def strip_boilerplate(text: str) -> str:
    """Cut the page's footer / related-links furniture off the end of a section."""
    cut = len(text)
    for marker in BOILERPLATE_MARKERS:
        idx = text.find(marker)
        if idx != -1:
            cut = min(cut, idx)
    return text[:cut].strip()


def extract_blog_data(html: str) -> dict:
    """Pull the article record out of a Groww /blog page's __NEXT_DATA__ payload."""
    soup = BeautifulSoup(html, "html.parser")
    tag = soup.find("script", id="__NEXT_DATA__")
    if tag is None or not tag.string:
        raise ValueError("__NEXT_DATA__ not found on blog page")
    blog = json.loads(tag.string)["props"]["pageProps"].get("blogData")
    if not blog or "content" not in blog:
        raise ValueError("Unexpected blogData shape")
    return blog


def split_html_by_heading(content_html: str) -> list[tuple[str, str]]:
    """
    Split an article body into (section_slug, text) at every h2/h3.

    This keeps each method ("via CAMS", "via your AMC"...) in its own chunk,
    which is exactly the same idea as section-per-chunk on the scheme pages.
    """
    matches = list(
        re.finditer(r"<h([23])[^>]*>(.*?)</h\1>", content_html, re.IGNORECASE | re.DOTALL)
    )
    if not matches:
        return [("body", strip_html(content_html))]

    sections: list[tuple[str, str]] = []
    intro = strip_boilerplate(strip_html(content_html[: matches[0].start()]))
    if intro:
        sections.append(("intro", intro))

    for i, m in enumerate(matches):
        heading = strip_html(m.group(2))
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(content_html)
        body = strip_boilerplate(strip_html(content_html[start:end]))
        slug = re.sub(r"[^a-z0-9]+", "_", heading.lower()).strip("_")[:48]
        sections.append((slug, f"{heading}\n{body}".strip()))
    return sections


# --------------------------------------------------------------------------- #
# Small formatting helpers
# --------------------------------------------------------------------------- #


def rupees(value) -> str:
    """100 -> 'Rs 100'; 39933.3663 -> 'Rs 39,933.37 Cr' style handling by caller."""
    if value in (None, ""):
        return "Not available"
    try:
        return f"Rs {float(value):,.2f}".replace(".00", "")
    except (TypeError, ValueError):
        return str(value)


def fmt_aum(value) -> str:
    if value in (None, ""):
        return "Not available"
    try:
        return f"Rs {float(value):,.2f} Cr"
    except (TypeError, ValueError):
        return str(value)


def fmt_nav(value) -> str:
    """NAV is quoted to 3 decimals on the page but 2 is enough to read."""
    if value in (None, ""):
        return "Not available"
    try:
        return f"Rs {float(value):,.2f}"
    except (TypeError, ValueError):
        return str(value)


def fmt_date(value) -> str:
    """Normalise the several date shapes the payload uses."""
    if not value:
        return "Not available"
    text = str(value)
    for fmt in ("%d-%b-%Y", "%d-%m-%Y", "%Y-%m-%d", "%d %b %Y"):
        try:
            return datetime.strptime(text[:11].strip(), fmt).strftime("%d %b %Y")
        except ValueError:
            continue
    return text


def clean(value) -> str:
    """Collapse whitespace / stray newlines the payload carries (e.g. exit_load)."""
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def fmt_lock_in(lock_in: dict | None) -> str:
    """{'years': 3, 'months': 0, 'days': 0} -> '3 years'."""
    if not lock_in:
        return ""
    parts = []
    for unit, label in (("years", "year"), ("months", "month"), ("days", "day")):
        n = lock_in.get(unit)
        if n:
            parts.append(f"{int(n)} {label}" + ("" if int(n) == 1 else "s"))
    return ", ".join(parts)


# --------------------------------------------------------------------------- #
# Section builder - one readable block per topic
# --------------------------------------------------------------------------- #


def build_sections(src: Source, d: dict) -> list[tuple[str, str]]:
    """
    Turn one fund record into ordered (section_name, text) blocks.

    Each block is a self-contained, labelled fact group. This is the input to
    chunking - the strategy is proposed and approved before chunking is coded.
    """
    scheme = d.get("scheme_name") or src.scheme_name
    category_info = d.get("category_info") or {}
    rta = d.get("rta_details") or {}
    exit_load = clean(d.get("exit_load")) or "Nil"
    # The single `fund_manager` field is often stale on these pages, so we build the
    # list from fund_manager_details instead (matches what the page displays).
    managers = ", ".join(
        clean(m.get("person_name"))
        for m in (d.get("fund_manager_details") or [])
        if m.get("person_name")
    )
    sections: list[tuple[str, str]] = []

    # 1. Overview -------------------------------------------------------- #
    overview = [
        f"Scheme name: {scheme}",
        f"Fund house (AMC): {d.get('fund_house', 'HDFC Mutual Fund')}",
        f"Category: {d.get('sub_category') or src.category}",
        f"Scheme type: {d.get('category')} | Plan: {d.get('plan_type')} | "
        f"Option: {d.get('scheme_type')}",
        f"Launch date: {fmt_date(d.get('launch_date'))}",
        f"Fund manager(s): {managers or 'Not available'}",
        f"ISIN: {d.get('isin') or 'Not available'} | "
        f"Scheme code: {d.get('scheme_code') or 'Not available'}",
        f"Investment objective: {strip_html(d.get('description')) or 'Not available'}",
    ]
    sections.append(("scheme_overview", "\n".join(overview)))

    # 2. Fees ------------------------------------------------------------- #
    fees = [f"Expense ratio of {scheme}: {clean(d.get('expense_ratio')) or 'Not available'}%"]
    if d.get("base_expense_ratio"):
        fees.append(f"Base expense ratio of {scheme}: {d['base_expense_ratio']}%")
    fees.append(f"Exit load of {scheme}: {exit_load}")
    if d.get("stamp_duty"):
        fees.append(f"Stamp duty on investment in {scheme}: {d['stamp_duty']}")
    historic = d.get("historic_exit_loads") or []
    for item in historic:
        if item.get("note"):
            fees.append(
                f"Historic exit load of {scheme} (effective {fmt_date(item['as_on_date'])}): "
                f"{item['note'].strip()}"
            )
    sections.append(("fees", "\n".join(fees)))

    # 3. Minimum investment ---------------------------------------------- #
    minimums = [
        f"Minimum SIP amount for {scheme}: {rupees(d.get('min_sip_investment'))}",
        f"Maximum SIP amount for {scheme}: {rupees(d.get('max_sip_investment'))}",
        f"Minimum first-time lump sum investment in {scheme}: "
        f"{rupees(d.get('min_investment_amount'))}",
        f"Minimum additional investment in {scheme}: "
        f"{rupees(d.get('mini_additional_investment'))}",
        f"Minimum withdrawal amount from {scheme}: {rupees(d.get('min_withdrawal'))}",
        f"SIP allowed in {scheme}: {'Yes' if d.get('sip_allowed') else 'No'} | "
        f"Lump sum allowed: {'Yes' if d.get('lumpsum_allowed') else 'No'}",
    ]
    sections.append(("minimum_investment", "\n".join(minimums)))

    # 4. Lock-in (ELSS only) --------------------------------------------- #
    lock = fmt_lock_in(d.get("lock_in"))
    if lock:
        sections.append(
            (
                "lock_in",
                f"Lock-in period of {scheme}: {lock}. Units of {scheme} cannot be "
                f"redeemed or sold before the lock-in period ends. "
                f"Exit load of {scheme} is {exit_load}.",
            )
        )

    # 5. Benchmark -------------------------------------------------------- #
    sections.append(
        (
            "benchmark",
            f"Benchmark of {scheme}: {d.get('benchmark_name') or 'Not available'} "
            f"({d.get('benchmark') or 'n/a'}). This is the index the scheme is "
            f"measured against.",
        )
    )

    # 6. Riskometer ------------------------------------------------------- #
    sections.append(
        (
            "riskometer",
            f"Riskometer rating of {scheme}: {d.get('nfo_risk') or 'Not available'}. "
            f"Groww rating of {scheme}: {d.get('groww_rating') or 'Not available'} "
            f"out of 5.",
        )
    )

    # 7. Tax -------------------------------------------------------------- #
    tax = category_info.get("tax_impact")
    if tax:
        sections.append(("tax", f"Tax implication for {scheme}: {strip_html(tax)}"))

    # 8. Fund details ----------------------------------------------------- #
    details = [
        f"Assets under management (AUM) of {scheme}: {fmt_aum(d.get('aum'))}",
        f"Latest NAV of {scheme}: {fmt_nav(d.get('nav'))} (as on {fmt_date(d.get('nav_date'))})",
        f"Portfolio turnover ratio of {scheme}: "
        f"{d.get('portfolio_turnover') if d.get('portfolio_turnover') is not None else 'Not available'}",
        f"Custodian of {scheme}: {rta.get('custodian_name') or 'Not available'}",
        f"Registrar and transfer agent (RTA) of {scheme}: "
        f"{rta.get('rta_name') or 'Not available'} "
        f"({rta.get('website') or 'website not available'})",
        f"Official AMC website / Scheme Information Document (SID) for {scheme}: "
        f"{d.get('sid_url') or d.get('amc_info', {}).get('vro_website') or 'Not available'}",
    ]
    sections.append(("fund_details", "\n".join(details)))

    return sections


# --------------------------------------------------------------------------- #
# Write the readable raw file
# --------------------------------------------------------------------------- #


def render_raw_file(src: Source, d: dict, sections: list[tuple[str, str]], fetched: str) -> str:
    """Human-readable cleaned page text, saved to data/raw/<slug>.txt."""
    rule = "=" * 78
    out = [
        rule,
        f"SOURCE      : {src.scheme_name}",
        f"URL         : {src.url}",
        f"CATEGORY    : {src.category}",
        f"AMC        : {d.get('fund_house', 'HDFC Mutual Fund')}",
        f"FETCHED ON  : {fetched}",
        f"SECTIONS    : {len(sections)}",
        rule,
        "",
        "NOTE: Return figures, category averages, rankings, portfolio holdings and",
        "      fund-comparison tables are intentionally NOT included. The brief",
        "      forbids performance claims, so the bot refuses return questions and",
        "      links to the official factsheet instead.",
        "",
    ]
    for name, text in sections:
        out += ["", "-" * 78, f"## {name}", "-" * 78, text]
    out += ["", rule, "END OF FILE", rule, ""]
    return "\n".join(out)


def render_guide_raw_file(src: Source, blog: dict, sections: list[tuple[str, str]], fetched: str) -> str:
    """Human-readable cleaned article text, saved to data/raw/<slug>.txt."""
    rule = "=" * 78
    out = [
        rule,
        f"SOURCE      : {src.scheme_name}",
        f"URL         : {src.url}",
        f"CATEGORY    : {src.category}",
        f"TYPE        : guide (how-to article)",
        f"TITLE       : {blog.get('title', 'Not available')}",
        f"PUBLISHED   : {fmt_date(blog.get('published_at'))}",
        f"UPDATED     : {fmt_date(blog.get('updated_at'))}",
        f"FETCHED ON  : {fetched}",
        f"SECTIONS    : {len(sections)}",
        rule,
        "",
        "NOTE: This is a how-to guide, not a scheme page. It carries no return or",
        "      performance figures, so the no-performance-claims rule is not at risk.",
        "",
    ]
    for name, text in sections:
        out += ["", "-" * 78, f"## {name}", "-" * 78, text]
    out += ["", rule, "END OF FILE", rule, ""]
    return "\n".join(out)


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #

REQUIRED_FIELDS = ("expense_ratio", "exit_load", "min_sip_investment", "benchmark_name")


def load_all(verbose: bool = True) -> list[Path]:
    """
    Fetch + clean every source page, write data/raw/*.txt, return paths written.
    """
    sources = read_sources()
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    fetched = date.today().isoformat()

    with requests.Session() as session:
        for src in sources:
            print(f"[load] {src.scheme_name}")
            try:
                html = fetch_html(src.url, session=session)
                if src.source_type == "guide":
                    data = extract_blog_data(html)
                    sections = split_html_by_heading(data.get("content", ""))
                    rendered = render_guide_raw_file(src, data, sections, fetched)
                else:
                    data = extract_next_data(html)
                    missing = [f for f in REQUIRED_FIELDS if not data.get(f)]
                    if missing:
                        print(f"       WARNING: missing fields {missing}")
                    sections = build_sections(src, data)
                    rendered = render_raw_file(src, data, sections, fetched)
            except Exception as exc:  # noqa: BLE001 - report and continue
                print(f"       FAILED: {exc}")
                continue

            path = RAW_DIR / f"{src.slug}.txt"
            path.write_text(rendered, encoding="utf-8")
            written.append(path)
            print(f"       ok -> {path.relative_to(ROOT)} ({len(sections)} sections)")

    if verbose:
        print(f"\nWrote {len(written)}/{len(sources)} raw files to {RAW_DIR}")
    return written


# --------------------------------------------------------------------------- #
# Chunking  (strategy: docs/chunking_strategy.md)
# --------------------------------------------------------------------------- #

CHUNKS_TXT = ROOT / "data" / "chunks.txt"

# Human-readable label per section, used as the chunk's fact_label.
FACT_LABELS = {
    "scheme_overview": "scheme name, category, launch date, fund manager, objective",
    "fees": "expense ratio, base expense ratio, exit load, stamp duty",
    "minimum_investment": "minimum SIP, maximum SIP, minimum lump sum, minimum withdrawal",
    "lock_in": "lock-in period",
    "benchmark": "benchmark index",
    "riskometer": "riskometer rating",
    "tax": "tax implication on redemption",
    "fund_details": "AUM, NAV, portfolio turnover, custodian, RTA, official AMC link",
}


@dataclass
class Chunk:
    chunk_id: str
    text: str
    metadata: dict


def build_chunk_text(src: Source, section: str, body: str) -> str:
    """
    The string that actually gets embedded.

    Three prefix lines, each earning its place by measurement:
      Scheme/Topic  - disambiguates the 5 schemes. Removing it made
                      "expense ratio of HDFC Small Cap" return the Flexi Cap
                      fees chunk, so it is load-bearing, not decoration.
      Facts         - the fact_label keywords ("expense ratio, exit load,
                      stamp duty"). Adding this line took retrieval from 5/6 to
                      6/6 on the verification set, because the body text alone
                      buries the field name.
      Section       - the section slug, which the LLM can cite.
    """
    if src.source_type == "guide":
        header = f"Topic: {src.scheme_name}"
    else:
        header = f"Scheme: {src.scheme_name} ({src.category})"
    facts = FACT_LABELS.get(section, section.replace("_", " "))
    return f"{header}\nFacts: {facts}\nSection: {section}\n{body}"


# all-MiniLM-L6-v2 truncates at 256 tokens (~1000 chars of this kind of text).
# Anything longer would be silently cut, so long sections are split further.
MAX_CHUNK_CHARS = 900


def split_long(text: str, limit: int = MAX_CHUNK_CHARS) -> list[str]:
    """
    Split an over-long section without cutting a fact in half.

    Prefers 'Step N:' boundaries (the guide articles are step lists), then
    sentences. Order of preference keeps label/value pairs together.
    """
    if len(text) <= limit:
        return [text]

    def pack(pieces: list[str]) -> list[str]:
        out: list[str] = []
        cur = ""
        for piece in pieces:
            if not piece.strip():
                continue
            if cur and len(cur) + len(piece) > limit:
                out.append(cur.strip())
                cur = piece
            else:
                cur += piece
        if cur.strip():
            out.append(cur.strip())
        return out

    # Order matters: 'label: value' lines are the highest-value boundary because a
    # split there can never separate a label from its value.
    for splitter in (r"(?=Step \d+:)", r"(?<=[.!?])\s+", r"(?<=\n)"):
        pieces = re.split(splitter, text)
        packed = pack(pieces)
        if all(len(p) <= limit for p in packed):
            return packed
    return packed  # last resort: still oversized, but as few pieces as possible


def make_chunks(fetched: str | None = None) -> list[Chunk]:
    """
    Turn every section of every source into chunks, one per section.

    Overlap is 0 by design: each section is independently answerable, so no fact
    is ever split across a boundary. See docs/chunking_strategy.md.
    """
    fetched = fetched or date.today().isoformat()
    chunks: list[Chunk] = []

    for src in read_sources():
        path = RAW_DIR / f"{src.slug}.txt"
        if not path.exists():
            raise FileNotFoundError(f"Missing {path}. Run load_all() first.")
        # write_text() translates "\n" to "\r\n" on Windows, so normalise before
        # we run line-anchored regexes over the file.
        text = path.read_text(encoding="utf-8").replace("\r\n", "\n")

        # Re-read the labelled sections straight out of the raw file, so chunking
        # always reflects what is on disk rather than a second network fetch.
        blocks = re.split(r"^-{78}$\n## ", text, flags=re.MULTILINE)
        for block in blocks[1:]:
            name, _, body = block.partition("\n")
            # Drop the closing rule line that follows the "## <name>" header.
            body = re.sub(r"^-{78}\n", "", body, count=1)
            body = re.sub(r"\n?END OF FILE.*$", "", body, flags=re.DOTALL).strip()
            if not body:
                continue
            section = name.strip()
            parts = split_long(body)
            for i, part in enumerate(parts, 1):
                suffix = "" if len(parts) == 1 else f"__p{i}"
                chunks.append(
                    Chunk(
                        chunk_id=f"{src.slug}__{section}{suffix}",
                        text=build_chunk_text(src, section, part),
                        metadata={
                            "chunk_id": f"{src.slug}__{section}{suffix}",
                            "source_type": src.source_type,
                            "scheme_name": src.scheme_name,
                            "scheme_slug": src.slug,
                            "category": src.category,
                            "source_url": src.url,
                            "section": section,
                            "part": f"{i}/{len(parts)}",
                            "fact_label": FACT_LABELS.get(
                                section, section.replace("_", " ")
                            ),
                            "last_updated": fetched,
                            "char_len": len(part),
                        },
                    )
                )
    return chunks


def write_chunks_txt(chunks: list[Chunk]) -> Path:
    """Human-readable dump of every chunk, for review before/after ingestion."""
    rule = "=" * 78
    out = [
        rule,
        "ALL CHUNKS - inspectable dump",
        f"Total chunks : {len(chunks)}",
        f"Strategy     : section-per-chunk, overlap 0 (see docs/chunking_strategy.md)",
        f"Embedding    : sentence-transformers/all-MiniLM-L6-v2 (384-dim)",
        rule,
        "",
    ]
    for i, c in enumerate(chunks, 1):
        out += [
            "",
            "#" * 78,
            f"[{i:02d}] chunk_id   : {c.chunk_id}",
            f"     scheme_name: {c.metadata['scheme_name']}",
            f"     category   : {c.metadata['category']}",
            f"     section    : {c.metadata['section']}",
            f"     fact_label : {c.metadata['fact_label']}",
            f"     source_url : {c.metadata['source_url']}",
            f"     last_updated: {c.metadata['last_updated']}",
            f"     char_len   : {c.metadata['char_len']}",
            "-" * 78,
            "TEXT EMBEDDED:",
            c.text,
            "-" * 78,
        ]
    out += ["", rule, "END OF FILE", rule, ""]
    CHUNKS_TXT.write_text("\n".join(out), encoding="utf-8")
    return CHUNKS_TXT


def run_ingest(rebuild: bool = False) -> list[Chunk]:
    """
    Full load -> chunk -> embed -> store step.

    `rebuild` forces a re-fetch of the pages and a rebuild of the vector store.
    Without it, data/raw files and an already-populated ChromaDB are reused, so a
    second run is fast and never duplicates entries.
    """
    if rebuild or not any(RAW_DIR.glob("*.txt")):
        load_all()
    chunks = make_chunks()
    path = write_chunks_txt(chunks)
    print(f"\n[chunk] {len(chunks)} chunks -> {path.relative_to(ROOT)}")
    by_scheme: dict[str, int] = {}
    for c in chunks:
        by_scheme[c.metadata["scheme_name"]] = by_scheme.get(c.metadata["scheme_name"], 0) + 1
    for name, n in by_scheme.items():
        print(f"         {n:>2}  {name}")

    embed_and_store(chunks, rebuild=rebuild)
    return chunks


# --------------------------------------------------------------------------- #
# Phase 3: Embedding and vector store
# --------------------------------------------------------------------------- #

EMBED_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
EMBED_DIM = 384
CHROMA_DIR = ROOT / "chroma_db"
COLLECTION_NAME = "mf_faq_chunks"
MANIFEST = CHROMA_DIR / "manifest.json"

_model = None  # cached so we load the weights once per process


def get_model():
    """Load and cache the local MiniLM sentence-transformer."""
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer

        _model = SentenceTransformer(EMBED_MODEL)
    return _model


def get_client():
    """Persistent Chroma client. Data survives restarts on disk."""
    import chromadb

    CHROMA_DIR.mkdir(parents=True, exist_ok=True)
    return chromadb.PersistentClient(path=str(CHROMA_DIR))


def get_collection(client, create: bool = True):
    """The single collection, using cosine distance (correct for MiniLM norms)."""
    if create:
        return client.get_or_create_collection(
            name=COLLECTION_NAME, metadata={"hnsw:space": "cosine"}
        )
    try:
        return client.get_collection(name=COLLECTION_NAME)
    except Exception:  # noqa: BLE001 - collection simply absent
        return None


def chunk_signature(chunks: list[Chunk]) -> str:
    """Stable fingerprint of the corpus, so we can detect a changed corpus."""
    import hashlib

    joined = "|".join(c.chunk_id for c in chunks)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:16]


def embed_and_store(chunks: list[Chunk], rebuild: bool = False, batch_size: int = 16) -> int:
    """
    Embed every chunk with MiniLM and upsert it into ChromaDB.

    Skips all work when the stored collection already matches this corpus
    (same chunk ids, same embedding model). Returns the number of vectors stored.
    """
    client = get_client()
    signature = chunk_signature(chunks)

    if rebuild:
        try:
            client.delete_collection(COLLECTION_NAME)
            print("[embed] --rebuild: dropped existing collection")
        except Exception:  # noqa: BLE001 - nothing to delete
            pass
        MANIFEST.unlink(missing_ok=True)

    collection = get_collection(client, create=True)

    # Skip if the store is already in sync with the chunk set.
    if collection.count() == len(chunks):
        try:
            stored = json.loads(MANIFEST.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            stored = {}
        if (
            stored.get("signature") == signature
            and stored.get("embed_model") == EMBED_MODEL
            and stored.get("count") == len(chunks)
        ):
            print(
                f"[embed] already up to date: {collection.count()} vectors in "
                f"{CHROMA_DIR.name}/ (use --rebuild to force)"
            )
            return 0

    print(f"[embed] loading {EMBED_MODEL} (first run downloads ~90MB)...")
    model = get_model()

    print(f"[embed] embedding {len(chunks)} chunks -> {EMBED_DIM}-dim vectors")
    texts = [c.text for c in chunks]
    vectors = model.encode(
        texts,
        batch_size=batch_size,
        convert_to_numpy=True,
        normalize_embeddings=True,
        show_progress_bar=False,
    )

    if vectors.shape[1] != EMBED_DIM:
        raise ValueError(f"Expected {EMBED_DIM}-dim vectors, got {vectors.shape[1]}")

    # Clear-then-add keeps the collection exactly in sync with the chunk list.
    existing = collection.get(limit=collection.count() or 1)
    if existing["ids"]:
        collection.delete(ids=existing["ids"])

    collection.add(
        ids=[c.chunk_id for c in chunks],
        documents=texts,
        metadatas=[c.metadata for c in chunks],
        embeddings=[v.tolist() for v in vectors],
    )

    stored_n = collection.count()
    if stored_n != len(chunks):
        raise RuntimeError(f"Stored {stored_n} vectors but expected {len(chunks)}")

    MANIFEST.write_text(
        json.dumps(
            {
                "count": stored_n,
                "signature": signature,
                "embed_model": EMBED_MODEL,
                "embed_dim": EMBED_DIM,
                "collection": COLLECTION_NAME,
                "built_at": datetime.now().isoformat(timespec="seconds"),
                "last_updated": chunks[0].metadata["last_updated"] if chunks else None,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"[embed] stored {stored_n} vectors in {CHROMA_DIR.name}/ (collection "
          f"'{COLLECTION_NAME}', cosine space)")
    return stored_n


def similarity_probe(
    question: str, top_k: int = 5, scheme_name: str | None = None
) -> list[dict]:
    """
    Quick manual query against the persisted store (used for verification).

    `scheme_name` applies an exact ChromaDB metadata filter. This matters: pure
    embedding similarity confuses "HDFC Large Cap" with "HDFC Small Cap", because
    MiniLM treats those names as semantically close. Scheme disambiguation must be
    done with a metadata filter, not with the vector score. Phase 5's retriever
    does exactly this.
    """
    client = get_client()
    collection = get_collection(client, create=False)
    if collection is None or collection.count() == 0:
        raise RuntimeError("Vector store is empty. Run: python src/ingest.py")
    vector = get_model().encode(
        [question], convert_to_numpy=True, normalize_embeddings=True
    )[0]
    kwargs = {
        "query_embeddings": [vector.tolist()],
        "n_results": top_k,
        "include": ["documents", "metadatas", "distances"],
    }
    if scheme_name:
        kwargs["where"] = {"scheme_name": scheme_name}
    result = collection.query(**kwargs)
    out = []
    for i in range(len(result["ids"][0])):
        out.append(
            {
                "chunk_id": result["ids"][0][i],
                "distance": round(result["distances"][0][i], 4),
                "scheme_name": result["metadatas"][0][i]["scheme_name"],
                "section": result["metadatas"][0][i]["section"],
                "source_url": result["metadatas"][0][i]["source_url"],
                "document": result["documents"][0][i],
            }
        )
    return out


if __name__ == "__main__":
    if "--query" in sys.argv:
        q = sys.argv[sys.argv.index("--query") + 1]
        k = 5
        if "--top-k" in sys.argv:
            k = int(sys.argv[sys.argv.index("--top-k") + 1])
        for i, hit in enumerate(similarity_probe(q, top_k=k), 1):
            print(f"\n[{i}] distance={hit['distance']}  {hit['chunk_id']}")
            print(f"    scheme : {hit['scheme_name']} / {hit['section']}")
            print(f"    source : {hit['source_url']}")
            print(f"    text   : {hit['document'][:220]}")
    else:
        run_ingest(rebuild="--rebuild" in sys.argv)