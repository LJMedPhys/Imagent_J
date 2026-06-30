# Learned memory

The agent's own compiled memory of verified **pitfalls** (error → fix lessons) and
reusable **recipes** (verified scripts), curated by a background **Librarian** subagent
on top of the Qdrant RAG. Orchestration: `src/imagentj/tools/learned_memory.py`;
vector-store layer: `src/imagentj/tools/rag_tools.py`.

## Two tiers — a vector REGULAR library + a markdown CORE floor

- **REGULAR library → Qdrant** (collections `codingerrors_and_solutions` for pitfalls,
  `code_recipes` for recipes). Semantic hybrid recall, write-time cosine dedup, and
  per-language / error_type filters. The worker agents pull it on demand via
  `rag_retrieve_mistakes` / `rag_retrieve_recipes`. Each point carries a stable
  `ehash`, a `core` flag, a `scope` (general|plugin), and a `times_seen` counter.
- **CORE floor → this directory (a derived markdown cache).** A small, fixed-size,
  **per-language** set that is ALWAYS injected:
  - `pitfalls/CORE.<Language>.md` — ≤ 12 per language; full rule + snippet inline.
  - `recipes/CORE.<Language>.md` — ≤ 5 per language; name + inputs + description +
    SCRIPT path (**never the code**).
  These files are read by `core_pitfalls()` / `core_recipes()` for injection —
  bulletproof and zero-dependency, so the can't-miss floor works **even if Qdrant is
  down**. They are *regenerated from Qdrant* whenever CORE membership changes; `recall`
  excludes `core=True` points (they are already injected). CORE is per-language so the
  Python analyst never sees Groovy entries and vice versa.

## Recipe code lives on disk

- `recipes/code/<chash>.<ext>` — the verified recipe **scripts**, content-addressed by
  hash. This is the source of truth for recipe code; the Qdrant recipe point embeds
  only name + description and stores a `path` pointer. The thing you run stays a file;
  the thing you search is the vector. (Gitignored — kept locally, not pushed.)
- `log.md` — append-only audit. `.runcount` — persisted Librarian-dispatch counter.

## How entries are created and curated (automatic — never by hand)

The **Librarian is the sole writer.** On every **verified-green** run,
`learned_memory.on_success()` fires it in a background thread (model `gpt-5.x-mini`,
off the hot path — the task never waits) with the new recipe and/or the debugger's
buffered error→fix lesson, plus a snapshot. The Librarian:

- **files** the new recipe (copying its code to `recipes/code/`) and/or pitfall via
  the `library_*` tools, choosing the tier (CORE vs regular);
- relies on **automatic write-time dedup** (near-identical entries bump `times_seen`
  instead of inserting);
- on a periodic **gap-band neighbor sweep** (~every 10 green runs), resolves
  *similar-but-not-identical* clusters the write-time guard missed, and **rebalances
  CORE** (promotion + demotion within the caps).

It mutates the store **only** through `library_add_pitfall`, `library_add_recipe`,
`library_remove`, and `library_set_core`, so it can judge but never garble the format.
If the model or the learning RAG is unavailable, `on_success` falls back to a
deterministic minimal save (and CORE regeneration is skipped so the cache is never
clobbered during an outage).

## Robustness

Recipe code (files) + the CORE markdown floor (git-tracked) are the durable layer;
the Qdrant index is rebuildable from them. The always-injected floor degrades
gracefully — it never depends on Qdrant being up.
