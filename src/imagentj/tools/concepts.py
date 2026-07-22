"""concepts.py — on-demand retrieval over the FIXED concept library.

A third, language-agnostic tier of learned knowledge (alongside the pitfalls and
recipes in ``learned_memory.py``): strategic **WHEN / DO / WHY / AVOID** heuristics
for *planning* image-analysis workflows — the "why and when" of choosing an approach,
distilled from authoritative sources (bioimagebook, review papers, the image.sc
forum) and vetted in human review.

Unlike pitfalls/recipes this tier is deliberately different in two ways:
  * **Fixed** — it is NOT auto-curated by the Librarian; the library only changes when
    a human promotes a reviewed candidate from ``concepts/_pending.md`` into
    ``concepts/library.md``.
  * **Not auto-injected** — there is no always-on CORE floor for concepts. Entries are
    pulled ON DEMAND via the ``recall_concepts`` tool, exactly like the documentation
    RAG is pulled via ``rag_retrieve_docs``.

Retrieval mirrors ``learned_memory.recall``: IDF-weighted token overlap (a BM25-lite)
over each entry's body plus its ``modality:``/``task:``/``kw:`` tags, so rare,
distinctive terms dominate and the ranking stays specific as the library grows. No LLM
call is involved — it is fast and deterministic.
"""
import os
import re
import math
from typing import List

from langchain.tools import tool

# Same writable root convention as learned_memory (ships in the image under
# /app/data/learned; overridable via LEARNED_ROOT for tests/other deployments).
ROOT = os.environ.get("LEARNED_ROOT", "/app/data/learned")
CONCEPTS_DIR = os.path.join(ROOT, "concepts")
LIBRARY_PATH = os.path.join(CONCEPTS_DIR, "library.md")

CONCEPT_K = 6          # max concepts returned per call

# Structural/filler words stripped before matching (mirrors learned_memory._STOP, plus
# the WHEN/DO/WHY/AVOID scaffold words that appear in every entry and carry no signal).
_STOP = {
    "the", "and", "for", "with", "from", "this", "that", "image", "images",
    "script", "data", "use", "via", "into", "run", "all", "new", "get", "set",
    "help", "please", "using", "make", "create", "want", "need", "would", "like",
    "file", "files", "generate", "write", "code", "you", "can", "are", "not",
    "when", "why", "avoid", "src", "your", "one", "per", "its", "them", "these",
}

# An entry block = its <!--c:...--> header comment plus its body, up to the next
# header or end-of-file. Section headings / prose between entries are ignored.
_BLOCK_RE = re.compile(r"<!--c:[^>]*-->.*?(?=\n<!--c:|\Z)", re.S)


def _read(path: str) -> str:
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


def _tokens(*parts: str) -> set:
    """Lowercase set of ≥3-char alphanumeric words, stopwords removed — the unit of
    matching (identical in spirit to learned_memory._tokens)."""
    text = " ".join(p for p in parts if p)
    return {t.lower() for t in re.findall(r"[A-Za-z][A-Za-z0-9_]{2,}", text)} - _STOP


def _blocks() -> List[str]:
    return _BLOCK_RE.findall(_read(LIBRARY_PATH))


def _body(block: str) -> str:
    """The human-readable part: everything after the metadata comment (the
    WHEN/DO/WHY/AVOID/SRC lines)."""
    return block.split("-->", 1)[1].strip("\n")


def _tags(block: str) -> set:
    """The header's searchable tags: kw: aliases plus the modality:/task: values."""
    out = set()
    m = re.search(r"\bkw:([^>]*?)-->", block)
    if m:
        out |= {k.strip().lower() for k in m.group(1).split(",")} - {""}
    for field in ("modality", "task"):
        m = re.search(rf"\b{field}:(\S+)", block)
        if m:
            out |= _tokens(m.group(1).replace("-", " "))
    return out


def _match_tokens(block: str) -> set:
    """Everything an entry can match on: its body tokens PLUS its header tags."""
    return _tokens(_body(block)) | _tags(block)


def _scored(query_tokens: set, blocks: List[str]) -> List[str]:
    """Rank by IDF-weighted token overlap (BM25-lite): a matched token is worth
    log(1 + N/df), so rare/distinctive terms dominate and ubiquitous ones stop crowding
    results as the library grows. Mirrors learned_memory._scored."""
    toks = [_match_tokens(b) for b in blocks]
    n = len(blocks)
    df: dict = {}
    for ts in toks:
        for t in ts:
            df[t] = df.get(t, 0) + 1
    rows = []
    for b, ts in zip(blocks, toks):
        common = query_tokens & ts
        if not common:
            continue
        score = sum(math.log(1 + n / (1 + df.get(t, 0))) for t in common)
        rows.append((score, _body(b)))
    rows.sort(key=lambda t: t[0], reverse=True)
    return [body for _, body in rows]


@tool("recall_concepts")
def recall_concepts(query: str) -> str:
    """Retrieve strategic image-analysis heuristics relevant to the work at hand.

    Pull from the fixed CONCEPT LIBRARY — expert WHEN/DO/WHY/AVOID rules for *how* and
    *when* to choose an analysis approach (thresholding strategy, splitting touching
    objects, denoising vs. quantifying, metric/statistics choice, acquisition trade-offs,
    figure/reporting hygiene, …). Call it when PLANNING a pipeline or choosing an
    approach for a step — pass the scientific goal or the step description. This is
    conceptual guidance for strategy, NOT verified code (use `recall` for that) and NOT
    documentation lookup (use `rag_retrieve` for API details). Returns the most relevant
    concepts, or "" if nothing matches.
    """
    want = _tokens(query)
    if not want:
        return ""
    hits = _scored(want, _blocks())
    if not hits:
        return ""
    return ("RELEVANT ANALYSIS CONCEPTS (expert heuristics — follow the DO, heed the "
            "AVOID; strategic guidance, not verified code):\n\n"
            + "\n\n".join(hits[:CONCEPT_K]))
