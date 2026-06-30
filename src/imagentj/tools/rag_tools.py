"""RAG layer for the agent.

Three Qdrant collections back the learning loop:

  docs (BioimageAnalysisDocs):           static reference documentation (read-only)
  mistakes (codingerrors_and_solutions): pitfalls — symptom->rule lessons from fixes
  recipes (code_recipes):                verified reusable scripts (as templates)

Design notes:

  1. A pitfall EMBEDS only the `rule` (symptom + one-line fix). Its failed/working
     snippets live in metadata, so the embedding is dominated by the natural-language
     symptom the agent later queries with — not by boilerplate tokens. The whole
     pitfall is one self-contained point: nothing is written to disk.

  2. A recipe EMBEDS only name + description. The CODE is NOT stored in Qdrant — it is
     a runnable file on disk (recipes/code/<chash>.<ext>); the point stores a `path`
     pointer + the content hash. The thing you run stays a file; the thing you search
     is the vector.

  3. Filters (language, error_type, class_involved) are honoured at retrieval, and a
     min RRF score suppresses weak top-of-noise matches.

  4. CORE is the always-injected floor, owned by learned_memory.py as a markdown cache.
     Here every point carries a `core` flag and a stable `ehash`; retrieval EXCLUDES
     core points (they are already injected) and the Librarian flips `core` / removes /
     sweeps by `ehash`. learned_memory regenerates the markdown from these points.

  5. Write-time dedup is dense-cosine at DEDUP_SIMILARITY_THRESHOLD (~0.92): a near-
     duplicate increments `times_seen` instead of inserting. The Librarian's periodic
     neighbor SWEEP surfaces the softer [GAP_BAND_LOW, threshold) clusters that the
     write-time guard ignores, for a judgment merge.

  All MUTATIONS happen only through the background Librarian (sole writer). Worker
  agents call only the read tools (rag_retrieve_*).
"""
import os
import uuid
from typing import Optional, List, Dict, Any, Tuple

from langchain.tools import tool
from langchain_core.documents import Document
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from qdrant_client.http import models as qmodels

from .vector_stores import (
    get_vec_store_mistakes,
    get_vec_store_recipes,
    is_rag_available,
    is_learning_rag_available,
)

__all__ = [
    "rag_retrieve_docs", "rag_retrieve_mistakes", "rag_retrieve_recipes",
    # store API used by the Librarian (via learned_memory.py)
    "store_save_pitfall", "store_save_recipe", "store_remove",
    "store_set_core", "store_list_core", "store_snapshot", "store_neighbor_clusters",
    "store_recipe_exists", "retrieve_pitfalls_raw", "retrieve_recipes_raw",
]

openrouter_key = os.getenv("OPEN_ROUTER_API_KEY")
openai_key = os.getenv("OPENAI_API_KEY")
if openrouter_key:
    _api_key, _base_url, _model = openrouter_key, "https://openrouter.ai/api/v1", "openai/gpt-4o-mini"
elif openai_key:
    _api_key, _base_url, _model = openai_key, None, "gpt-4o-mini"
else:
    _api_key, _base_url, _model = None, None, "gpt-4o-mini"

# Bound the background neighbor sweep so it never scans an unbounded collection.
_SWEEP_MAX_POINTS = 300


# --------------------------------------------------------------------------- #
# Docs retrieval (query expansion + per-query rank RRF) — unchanged behaviour
# --------------------------------------------------------------------------- #
def get_expanded_queries(query: str) -> list[str]:
    """Generate 3-4 query variations to improve documentation recall."""
    if _api_key is None:
        return [query]
    from ..agents import shared_tracker
    llm = ChatOpenAI(model=_model, api_key=_api_key, base_url=_base_url,
                     temperature=0., callbacks=[shared_tracker])
    prompt = ChatPromptTemplate.from_template(
        "You are an ImageJ/Fiji expert. Generate 3 search query variations for: {question}\n"
        "Focus on technical API terms, alternative function names, and common library methods.\n"
        "Output only the queries, one per line."
    )
    variants = (prompt | llm | StrOutputParser()).invoke({"question": query}).strip().split("\n")
    return list(set([query] + [v.strip("- ").strip() for v in variants]))


@tool("rag_retrieve")
def rag_retrieve_docs(query: str) -> list:
    """Retrieve relevant context from the documentation RAG (hybrid search + query expansion)."""
    if not is_rag_available():
        return [{"content": "RAG system is not configured. No documents available.",
                 "source": None, "score": 0}]
    from ..rag.RAG import hybrid_search_with_rrf, apply_rrf, DOCS_COLLECTION_NAME
    ranked_lists = [
        hybrid_search_with_rrf(q, collection_name=DOCS_COLLECTION_NAME, limit=5)
        for q in get_expanded_queries(query)
    ]
    final_results = apply_rrf(ranked_lists, k=60)[:8]
    return [
        {
            "content": p.payload.get("page_content"),
            "source": p.payload.get("metadata", {}).get("source"),
            "page": p.payload.get("metadata", {}).get("page"),
            "score": getattr(p, "score", None),
        }
        for p in final_results
    ]


# --------------------------------------------------------------------------- #
# Qdrant filter / point helpers
# --------------------------------------------------------------------------- #
def _filter(must: Optional[dict] = None, must_not: Optional[dict] = None):
    """Build a Qdrant Filter over metadata.<key> conditions (LangChain nests payload
    under `metadata`). Returns None if nothing constrains the search."""
    must_c, not_c = [], []
    for k, v in (must or {}).items():
        if v is None or v == "":
            continue
        must_c.append(qmodels.FieldCondition(key=f"metadata.{k}",
                                             match=qmodels.MatchValue(value=v)))
    for k, v in (must_not or {}).items():
        if v is None:
            continue
        not_c.append(qmodels.FieldCondition(key=f"metadata.{k}",
                                            match=qmodels.MatchValue(value=v)))
    if not must_c and not not_c:
        return None
    return qmodels.Filter(must=must_c or None, must_not=not_c or None)


def _find_dedup_candidate(vec_store, collection_name: str, text: str,
                          qfilter=None, threshold: float = 0.92, limit: int = 3):
    """Return the top dense-cosine match if it clears `threshold`, else None.

    Dense-only (no RRF, no sparse): the collection is configured with COSINE, so a
    ScoredPoint's `score` IS cosine in [-1, 1]. RRF scores are rank-derived and must
    NOT be compared against a cosine threshold.
    """
    from ..rag.RAG import DENSE_VECTOR_NAME
    try:
        dense_vec = vec_store.embeddings.embed_query(text)
        res = vec_store.client.query_points(
            collection_name=collection_name, query=dense_vec,
            using=DENSE_VECTOR_NAME, query_filter=qfilter, limit=limit,
            with_payload=True,
        )
        for cand in res.points:
            score = getattr(cand, "score", None)
            if score is not None and score >= threshold:
                return cand
    except Exception:
        return None
    return None


def _scroll_points(vec_store, collection_name: str, qfilter=None,
                   with_vectors: bool = False, cap: int = 1000):
    """Scroll up to `cap` points matching the filter. Returns a list of records."""
    out = []
    offset = None
    try:
        while len(out) < cap:
            recs, offset = vec_store.client.scroll(
                collection_name=collection_name, scroll_filter=qfilter,
                limit=min(128, cap - len(out)), offset=offset,
                with_payload=True, with_vectors=with_vectors,
            )
            out.extend(recs)
            if offset is None or not recs:
                break
    except Exception:
        return out
    return out


def _point_by_ehash(vec_store, collection_name: str, ehash: str):
    recs = _scroll_points(vec_store, collection_name, _filter({"ehash": ehash}), cap=4)
    return recs[0] if recs else None


def _md(point) -> dict:
    return (point.payload.get("metadata", {}) or {}) if getattr(point, "payload", None) else {}


def _bump_seen(vec_store, collection_name: str, point) -> int:
    md = dict(_md(point))
    md["times_seen"] = int(md.get("times_seen", 1)) + 1
    vec_store.client.set_payload(collection_name=collection_name,
                                 payload={"metadata": md}, points=[point.id])
    return md["times_seen"]


# --------------------------------------------------------------------------- #
# Entry formatting — structured dicts; learned_memory renders markdown from these
# --------------------------------------------------------------------------- #
def _format_pitfall(point) -> Dict[str, Any]:
    md = _md(point)
    return {
        "kind": "pitfall",
        "ehash": md.get("ehash"),
        "rule": point.payload.get("page_content"),
        "snippet": md.get("working_code") or "",
        "failed_code": md.get("failed_code") or "",
        "language": md.get("language"),
        "error_type": md.get("error_type"),
        "class_involved": md.get("class_involved"),
        "scope": md.get("scope", "general"),
        "times_seen": int(md.get("times_seen", 1)),
        "core": bool(md.get("core", False)),
        "score": getattr(point, "score", None),
    }


def _format_recipe(point) -> Dict[str, Any]:
    md = _md(point)
    pc = point.payload.get("page_content") or ""
    name = md.get("name") or pc.split("\n", 1)[0]
    desc = pc.split("\n", 1)[1] if "\n" in pc else ""
    return {
        "kind": "recipe",
        "ehash": md.get("ehash"),
        "name": name,
        "description": desc,
        "language": md.get("language"),
        "inputs": md.get("inputs_required") or "",
        "path": md.get("path") or "",
        "chash": md.get("chash") or "",
        "times_seen": int(md.get("times_seen", 1)),
        "core": bool(md.get("core", False)),
        "score": getattr(point, "score", None),
    }


# --------------------------------------------------------------------------- #
# Pitfalls (mistakes) — save / retrieve
# --------------------------------------------------------------------------- #
def retrieve_pitfalls_raw(query: str, language: Optional[str] = None,
                          error_type: Optional[str] = None,
                          class_involved: Optional[str] = None,
                          limit: int = 5, exclude_core: bool = True,
                          min_score: Optional[float] = None) -> List[Dict[str, Any]]:
    vec = get_vec_store_mistakes()
    if vec is None:
        return []
    from ..rag.RAG import hybrid_search_with_rrf, MISTAKES_COLLECTION_NAME
    from config.rag_config import MIN_MISTAKE_SCORE
    if min_score is None:
        min_score = MIN_MISTAKE_SCORE
    qfilter = _filter({"language": language, "error_type": error_type,
                       "class_involved": class_involved},
                      {"core": True} if exclude_core else None)
    pts = hybrid_search_with_rrf(query, collection_name=MISTAKES_COLLECTION_NAME,
                                 limit=limit, query_filter=qfilter, client=vec.client)
    out = []
    for p in pts:
        s = getattr(p, "score", None)
        if s is not None and s < min_score:
            continue
        out.append(_format_pitfall(p))
    return out


@tool("rag_retrieve_mistakes")
def rag_retrieve_mistakes(query: str, language: Optional[str] = None,
                          error_type: Optional[str] = None,
                          class_involved: Optional[str] = None) -> list:
    """Retrieve relevant past coding mistakes (with their fixes) from the agent's
    memory of prior failures — beyond the CORE pitfalls already injected.

    Args:
        query:          The error symptom — paste the actual exception line / method
                        name / short description of the failure. Do NOT paraphrase;
                        the symptom string is what's indexed.
        language:       Optional filter ("Groovy" | "Python"). Strongly recommended.
        error_type:     Optional filter (e.g. "MissingMethod", "NullPointer", "Import").
        class_involved: Optional filter (e.g. "ImagePlus", "TrackMate").

    Returns a list of {rule, snippet, failed_code, language, error_type,
    class_involved, times_seen, score}, or empty if nothing clears the threshold.
    """
    if not is_learning_rag_available():
        return [{"rule": "RAG system is not configured. No coding experiences available.",
                 "score": 0}]
    return retrieve_pitfalls_raw(query, language=language, error_type=error_type,
                                 class_involved=class_involved)


def store_save_pitfall(language: str, rule: str, snippet: str = "",
                       failed_code: str = "", error_type: str = "Logic",
                       class_involved: str = "", scope: str = "general",
                       ehash: str = "", core: bool = False) -> Dict[str, Any]:
    """Insert (or dedup-bump) a pitfall. Returns {status, ehash, cosine}. status is
    'added' | 'bumped' | 'unavailable'. Plugin-scope entries are never set core here
    (learned_memory enforces this too)."""
    vec = get_vec_store_mistakes()
    if vec is None:
        return {"status": "unavailable", "ehash": ehash}
    rule = (rule or "").strip()
    if not rule:
        return {"status": "skipped", "ehash": ehash}
    from ..rag.RAG import MISTAKES_COLLECTION_NAME
    from config.rag_config import DEDUP_SIMILARITY_THRESHOLD
    qf = _filter({"language": language, "error_type": error_type})
    cand = _find_dedup_candidate(vec, MISTAKES_COLLECTION_NAME, rule, qfilter=qf,
                                 threshold=DEDUP_SIMILARITY_THRESHOLD)
    if cand is not None:
        n = _bump_seen(vec, MISTAKES_COLLECTION_NAME, cand)
        return {"status": "bumped", "ehash": _md(cand).get("ehash"),
                "cosine": getattr(cand, "score", None), "times_seen": n}
    md = {
        "ehash": ehash, "language": language, "error_type": error_type or "Logic",
        "class_involved": class_involved or "", "scope": scope or "general",
        "failed_code": failed_code or "", "working_code": snippet or "",
        "times_seen": 1, "core": bool(core) and (scope or "general") != "plugin",
    }
    vec.add_documents([Document(page_content=rule, metadata=md)],
                      ids=[str(uuid.uuid4())])
    return {"status": "added", "ehash": ehash}


# --------------------------------------------------------------------------- #
# Recipes — save / retrieve (code on disk; point stores description + path)
# --------------------------------------------------------------------------- #
def retrieve_recipes_raw(task: str, language: Optional[str] = None, limit: int = 3,
                         exclude_core: bool = True,
                         min_score: Optional[float] = None) -> List[Dict[str, Any]]:
    vec = get_vec_store_recipes()
    if vec is None:
        return []
    from ..rag.RAG import hybrid_search_with_rrf, RECIPES_COLLECTION_NAME
    from config.rag_config import MIN_RECIPE_SCORE
    if min_score is None:
        min_score = MIN_RECIPE_SCORE
    qfilter = _filter({"language": language}, {"core": True} if exclude_core else None)
    pts = hybrid_search_with_rrf(task, collection_name=RECIPES_COLLECTION_NAME,
                                 limit=limit, query_filter=qfilter, client=vec.client)
    out = []
    for p in pts:
        s = getattr(p, "score", None)
        if s is not None and s < min_score:
            continue
        out.append(_format_recipe(p))
    return out


RECIPE_USAGE_NOTE = (
    "These recipes are REFERENCE TEMPLATES from prior verified work, not a solution "
    "to the current task. Read the SCRIPT at `path`, then ADAPT it — image properties, "
    "channels, plugin versions, and parameters may differ. Do not copy verbatim."
)


@tool("rag_retrieve_recipes")
def rag_retrieve_recipes(task: str, language: Optional[str] = None) -> dict:
    """Retrieve verified working scripts matching a task, as REFERENCE templates
    (beyond the CORE recipes already injected). Each recipe gives a `path` to the
    full script on disk — read it with smart_file_reader, then adapt.

    Args:
        task:     Natural-language description of what the script should do.
        language: Optional filter ("Groovy" | "Python").

    Returns {usage_note, recipes: [{name, description, inputs, path, times_seen, score}]}.
    """
    if not is_learning_rag_available():
        return {"usage_note": RECIPE_USAGE_NOTE, "recipes": [],
                "message": "RAG system is not configured."}
    return {"usage_note": RECIPE_USAGE_NOTE,
            "recipes": retrieve_recipes_raw(task, language=language)}


def store_recipe_exists(language: str, chash: str) -> bool:
    """Cheap check: is a recipe with this exact code (chash) already stored? Used to
    gate Librarian dispatch so an unchanged green re-run doesn't fire it for nothing."""
    from ..rag.RAG import RECIPES_COLLECTION_NAME
    vec = get_vec_store_recipes()
    if vec is None or not chash:
        return False
    return bool(_scroll_points(vec, RECIPES_COLLECTION_NAME,
                               _filter({"language": language, "chash": chash}), cap=1))


def store_save_recipe(language: str, name: str, description: str, inputs: str,
                      code_path: str, chash: str, ehash: str = "",
                      core: bool = False) -> Dict[str, Any]:
    """Insert (or dedup-bump) a recipe. The CODE file must already exist at
    `code_path`; the point stores name+description (embedded) + path/chash (metadata).
    Dedup: exact by chash, else dense-cosine on name+description."""
    vec = get_vec_store_recipes()
    if vec is None:
        return {"status": "unavailable", "ehash": ehash}
    name = (name or "").strip()
    if not name:
        return {"status": "skipped", "ehash": ehash}
    from ..rag.RAG import RECIPES_COLLECTION_NAME
    from config.rag_config import DEDUP_SIMILARITY_THRESHOLD
    # exact code dedup first (cheap, exact): same chash under this language
    same_code = _scroll_points(vec, RECIPES_COLLECTION_NAME,
                               _filter({"language": language, "chash": chash}), cap=1)
    if same_code:
        n = _bump_seen(vec, RECIPES_COLLECTION_NAME, same_code[0])
        return {"status": "bumped", "ehash": _md(same_code[0]).get("ehash"),
                "reason": "chash", "times_seen": n}
    dedup_text = f"{name}\n{description}"
    cand = _find_dedup_candidate(vec, RECIPES_COLLECTION_NAME, dedup_text,
                                 qfilter=_filter({"language": language}),
                                 threshold=DEDUP_SIMILARITY_THRESHOLD)
    if cand is not None:
        n = _bump_seen(vec, RECIPES_COLLECTION_NAME, cand)
        return {"status": "bumped", "ehash": _md(cand).get("ehash"),
                "cosine": getattr(cand, "score", None), "times_seen": n}
    md = {
        "ehash": ehash, "name": name, "language": language,
        "inputs_required": inputs or "", "path": code_path, "chash": chash,
        "times_seen": 1, "core": bool(core),
    }
    vec.add_documents([Document(page_content=f"{name}\n{description}", metadata=md)],
                      ids=[str(uuid.uuid4())])
    return {"status": "added", "ehash": ehash}


# --------------------------------------------------------------------------- #
# Cross-store ops: remove, CORE membership, snapshot, neighbor sweep
# --------------------------------------------------------------------------- #
def _collections() -> List[Tuple[str, Any, str]]:
    """(kind, vec_store, collection_name) for the two learning collections."""
    from ..rag.RAG import MISTAKES_COLLECTION_NAME, RECIPES_COLLECTION_NAME
    return [
        ("pitfall", get_vec_store_mistakes(), MISTAKES_COLLECTION_NAME),
        ("recipe", get_vec_store_recipes(), RECIPES_COLLECTION_NAME),
    ]


def store_remove(ehash: str) -> Dict[str, Any]:
    """Delete the point(s) with this ehash from both collections. Returns
    {removed, kind, code_path, was_core, language} so the caller can unlink a recipe's
    code file and regenerate the CORE markdown if needed."""
    ehash = (ehash or "").strip()
    info = {"removed": 0, "kind": None, "code_path": "", "was_core": False, "language": None}
    if not ehash:
        return info
    for kind, vec, coll in _collections():
        if vec is None:
            continue
        pt = _point_by_ehash(vec, coll, ehash)
        if pt is None:
            continue
        md = _md(pt)
        info["kind"] = kind
        info["was_core"] = bool(md.get("core", False))
        info["language"] = md.get("language")
        if kind == "recipe":
            info["code_path"] = md.get("path") or ""
        try:
            vec.client.delete(collection_name=coll,
                              points_selector=qmodels.PointIdsList(points=[pt.id]))
            info["removed"] += 1
        except Exception:
            pass
    return info


def store_list_core(language: str, kind: str) -> List[Dict[str, Any]]:
    """All current CORE entries of this language/kind (for markdown regen + cap counts)."""
    from ..rag.RAG import MISTAKES_COLLECTION_NAME, RECIPES_COLLECTION_NAME
    fmt = _format_pitfall if kind == "pitfall" else _format_recipe
    vec = get_vec_store_mistakes() if kind == "pitfall" else get_vec_store_recipes()
    coll = MISTAKES_COLLECTION_NAME if kind == "pitfall" else RECIPES_COLLECTION_NAME
    if vec is None:
        return []
    recs = _scroll_points(vec, coll, _filter({"language": language, "core": True}), cap=64)
    out = [fmt(p) for p in recs]
    out.sort(key=lambda e: e["times_seen"], reverse=True)
    return out


def store_set_core(language: str, kind: str, ehashes: List[str], cap: int) -> List[Dict[str, Any]]:
    """Set CORE membership for a language/kind: core=True on the given ehashes
    (plugin-scope pitfalls excluded), core=False on all others; enforce `cap`
    (keep highest times_seen). Returns the resulting CORE entry dicts (for markdown)."""
    from ..rag.RAG import MISTAKES_COLLECTION_NAME, RECIPES_COLLECTION_NAME
    fmt = _format_pitfall if kind == "pitfall" else _format_recipe
    vec = get_vec_store_mistakes() if kind == "pitfall" else get_vec_store_recipes()
    coll = MISTAKES_COLLECTION_NAME if kind == "pitfall" else RECIPES_COLLECTION_NAME
    if vec is None:
        return []
    want = {h.strip() for h in ehashes if h and h.strip()}
    recs = _scroll_points(vec, coll, _filter({"language": language}), cap=_SWEEP_MAX_POINTS)
    by_hash = {_md(p).get("ehash"): p for p in recs}
    chosen = []
    for h in want:
        p = by_hash.get(h)
        if p is None:
            continue
        if kind == "pitfall" and _md(p).get("scope") == "plugin":
            continue  # plugin/environment lessons are never CORE
        chosen.append(p)
    chosen.sort(key=lambda p: int(_md(p).get("times_seen", 1)), reverse=True)
    chosen = chosen[:cap]
    keep_ids = {p.id for p in chosen}
    for p in recs:
        md = _md(p)
        should = p.id in keep_ids
        if bool(md.get("core", False)) != should:
            nmd = dict(md)
            nmd["core"] = should
            try:
                vec.client.set_payload(collection_name=coll,
                                       payload={"metadata": nmd}, points=[p.id])
            except Exception:
                pass
    return store_list_core(language, kind)


def store_snapshot(language: str, full: bool = False, cap: int = 15) -> Dict[str, Any]:
    """Compact view of the library for the Librarian: CORE (all) + a bounded set of
    regular entries, per kind. `full` returns more text per entry for dedup judgment."""
    out = {"language": language, "core_pitfalls": [], "reg_pitfalls": [],
           "core_recipes": [], "reg_recipes": []}
    from ..rag.RAG import MISTAKES_COLLECTION_NAME, RECIPES_COLLECTION_NAME
    specs = [("pitfall", get_vec_store_mistakes(), MISTAKES_COLLECTION_NAME, _format_pitfall),
             ("recipe", get_vec_store_recipes(), RECIPES_COLLECTION_NAME, _format_recipe)]
    for kind, vec, coll, fmt in specs:
        if vec is None:
            continue
        core = [fmt(p) for p in _scroll_points(vec, coll, _filter({"language": language, "core": True}), cap=64)]
        reg = [fmt(p) for p in _scroll_points(vec, coll, _filter({"language": language}, {"core": True}), cap=_SWEEP_MAX_POINTS)]
        core.sort(key=lambda e: e["times_seen"], reverse=True)
        reg.sort(key=lambda e: e["times_seen"], reverse=True)
        out["core_" + kind + "s"] = core
        out["reg_" + kind + "s"] = reg[:cap]
    return out


def store_neighbor_clusters(language: str, band_low: Optional[float] = None,
                            band_high: Optional[float] = None,
                            max_clusters: int = 12) -> List[Dict[str, Any]]:
    """Gap-band SWEEP: for each regular entry, find its nearest same-kind neighbour and
    report pairs whose cosine lands in [band_low, band_high) — the 'similar but not
    auto-merged' clusters the write-time guard ignored. Returns a bounded list of
    {kind, members:[entry dicts]} for the Librarian to judge-merge."""
    from ..rag.RAG import (DENSE_VECTOR_NAME, MISTAKES_COLLECTION_NAME,
                           RECIPES_COLLECTION_NAME)
    from config.rag_config import GAP_BAND_LOW, DEDUP_SIMILARITY_THRESHOLD
    lo = GAP_BAND_LOW if band_low is None else band_low
    hi = DEDUP_SIMILARITY_THRESHOLD if band_high is None else band_high
    specs = [("pitfall", get_vec_store_mistakes(), MISTAKES_COLLECTION_NAME, _format_pitfall),
             ("recipe", get_vec_store_recipes(), RECIPES_COLLECTION_NAME, _format_recipe)]
    clusters: List[Dict[str, Any]] = []
    seen_pairs = set()
    for kind, vec, coll, fmt in specs:
        if vec is None:
            continue
        recs = _scroll_points(vec, coll, _filter({"language": language}),
                              with_vectors=True, cap=_SWEEP_MAX_POINTS)
        by_id = {p.id: p for p in recs}
        for p in recs:
            vecs = getattr(p, "vector", None) or {}
            dvec = vecs.get(DENSE_VECTOR_NAME) if isinstance(vecs, dict) else None
            if dvec is None:
                continue
            try:
                res = vec.client.query_points(
                    collection_name=coll, query=dvec, using=DENSE_VECTOR_NAME,
                    query_filter=_filter({"language": language}), limit=2,
                    with_payload=True)
            except Exception:
                continue
            for cand in res.points:
                if cand.id == p.id:
                    continue
                sc = getattr(cand, "score", None)
                if sc is None or not (lo <= sc < hi):
                    continue
                key = tuple(sorted((str(p.id), str(cand.id))))
                if key in seen_pairs:
                    continue
                seen_pairs.add(key)
                other = by_id.get(cand.id) or cand
                clusters.append({"kind": kind, "cosine": round(sc, 3),
                                 "members": [fmt(p), fmt(other)]})
                if len(clusters) >= max_clusters:
                    return clusters
    return clusters
