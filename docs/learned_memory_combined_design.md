# Learned memory — combined RAG + Librarian design (proposal)

**Status:** design proposal (not yet implemented). Supersedes the pure file-based
wiki on `bugfix/coder_learning` and the agent-writes-directly RAG on `main` by
**combining** them. Reuses the proven Qdrant store from `main`, keeps the two
genuinely-new ideas from the file branch (an always-injected **CORE floor** and a
**background Librarian**), and drops the hand-rolled retrieval machinery (IDF
scoring, keyword aliases, manual shard dedup, markdown `seen:` counters) that the
vector store makes redundant.

---

## 1. Why combine

The file-based wiki reimplements, by hand, things the `main` RAG already does well:

| File branch (hand-rolled) | `main` RAG (already built) |
|---|---|
| IDF token scoring + keyword aliases | dense + sparse + RRF hybrid (real semantics) |
| Librarian eyeballs shards to dedup | cosine dedup at write (`_find_dedup_candidate`, 0.92) |
| `seen:N` bump in markdown | `times_seen` auto-increment on duplicate |
| separate `Groovy.md` / `Python.md` | `metadata.language` filter |
| (no notion of "too weak") | `MIN_MISTAKE_SCORE` / `MIN_RECIPE_SCORE` thresholds |

So "combine the Librarian with the existing RAG" = **adopt `main`'s Qdrant store as
the backend**, and keep only what the file branch genuinely invented:

1. **The CORE always-injected floor** — `main` is pure pull; nothing is injected
   unconditionally. A small, fixed-size, per-language can't-miss set is new.
2. **The background Librarian** — on `main` the *worker agent* calls `save_*` on the
   hot path. Moving curation off-path into a background subagent is new.

The retrieval quality goes **up** (hybrid+RRF > IDF+aliases), scale stops being a
concern (sub-linear lookup), and a pile of bespoke retrieval code goes away.

---

## 2. Who writes, who reads

**The Librarian is the only writer.** This is the central rule.

- **Worker agents (coder / debugger / analyst) are read-only.** They never call
  `save_recipe` / `save_coding_experience`. They reach the store through:
  - **auto-injected CORE** — the always-on floor (read from markdown, see §4);
  - **`rag_retrieve_recipes(task, language)`** (coder/analyst) and
    **`rag_retrieve_mistakes(error, language, error_type, class_involved)`** (debugger);
  - **`smart_file_reader`** — to read a recipe's code file for the full script.
- **The background Librarian is the sole writer.** `on_success()` fires it in a
  daemon thread on every verified-green run — the task never waits. The Librarian
  judges novelty, files via the deterministic write tools, dedups, and rebalances
  CORE. Nothing enters the DB except through it.

Why route all writes through the Librarian:
- **Off the hot path** — embedding + dedup + judgment never block the worker.
- **One place for judgment** — novelty, semantic merges cosine can't make, and
  CORE promotion/demotion all live in one curator with one operating manual
  (`skills/learned_memory/SKILL.md`), not scattered across worker prompts.
- **No uncurated junk** — workers can't dump half-baked entries into the store; the
  Librarian decides what is worth keeping and at which tier.

The write tools are **deterministic** (the Librarian decides, code applies) so the
store's format/invariants can never be garbled by a bad LLM plan.

---

## 3. Storage layout at a glance

| | searched on | stored where | code |
|---|---|---|---|
| **Recipe** | description | Qdrant point (`code_recipes`) + **file on disk** | full script → `recipes/code/<chash>.<ext>` |
| **Pitfall** | rule / symptom | **Qdrant point only** (`codingerrors_and_solutions`) | tiny snippets → metadata |
| **CORE recipe** | (always injected) | markdown floor | **pointer only** (path) |
| **CORE pitfall** | (always injected) | markdown floor | **full rule + snippet inline** |

Principle: **files for the thing you run, vectors for the thing you search, a small
markdown floor for the thing that must never fail.**

---

## 4. The CORE floor (markdown, per language)

CORE = the fixed-size, always-injected can't-miss set, kept as **small markdown
files** — *not* a Qdrant flag — because this floor must be readable, git-tracked,
hand-editable, and **bulletproof / zero-dependency**: it has to work even if Qdrant
is down or the embedder is cold.

```
data/learned/
  pitfalls/CORE.Groovy.md     # ≤ 12 pitfalls, full rule + snippet inline
  pitfalls/CORE.Python.md
  recipes/CORE.Groovy.md      # ≤ 5 recipes, name + inputs + description + path
  recipes/CORE.Python.md
  recipes/code/<chash>.groovy # recipe scripts (source of truth; gitignored)
  recipes/code/<chash>.py
```

- **CORE is per-language** (the Python analyst never sees Groovy entries).
- **CORE pitfall entries store the full rule + snippet inline** — they are tiny, so
  the lesson *and* its fix are fully readable in git without touching Qdrant.
- **CORE recipe entries store only name + inputs + description + the code path** —
  the code is large and lives in the file (referenced by the same `<chash>` path the
  Qdrant point uses).
- Membership is **rebalanced by the Librarian** (promotion AND demotion) to stay
  within the caps (§7). The regular library (everything else) lives in Qdrant.

---

## 5. Recipes — files on disk + Qdrant pointer

A recipe is a verified, **runnable** script. The script is the artifact you execute,
so the file *is* the canonical store; Qdrant only indexes how to find it.

- **Code → one file per recipe**, `recipes/code/<chash>.<ext>`, named by **content
  hash** (free exact-dedup, no name collisions). Source of truth. Gitignored for now.
- **Qdrant `code_recipes` point** → embed the *description/name*; metadata =
  `{language, inputs, chash, times_seen, core, path}`. **No code blob** — the code is
  never embedded (it would pollute the vector) and never the canonical copy.

Why files, not payload:
- **Runnability** — you execute a file; a payload string would have to be written
  back out every use.
- **The code is never a search signal** — `main` already embeds only the
  description, so there is zero retrieval benefit to storing code in Qdrant.
- **Qdrant is the *derived* index** (§9) — code in the payload would be lost on a
  rebuild-from-source; code as files survives and you re-ingest the descriptions.
- **Sharing** — readable/runnable locally now; flip one gitignore line to share.

---

## 6. Pitfalls — entirely in Qdrant

A pitfall is an error→fix lesson. Its snippets are tiny and **never executed**, and
the whole entry is both the search target and the answer — so it is one atomic
Qdrant point, no files, no pointer.

- **Qdrant `codingerrors_and_solutions` point** → embed the **`rule`** (symptom +
  one-line fix); metadata = `{language, error_type, class_involved, scope,
  failed_code, working_code, times_seen}`.
- This is exactly `main`'s `save_coding_experience` (embed the rule, code in
  metadata "so it doesn't pollute the embedding").
- **Sharper filtered recall than recipes:** the debugger recalls with an
  error/stack-trace, so retrieval can filter by `error_type` and `class_involved`,
  not just `language` (`_build_metadata_filter` already supports this).

---

## 7. Dedup — two thresholds

Write-time cosine dedup (`_find_dedup_candidate`, dense-only cosine, threshold ~0.92)
is **pairwise, at-insert, high-threshold**. It kills obvious near-identical dupes
cheaply (no LLM) and increments `times_seen` instead of inserting. But it
**structurally misses accreted clusters**: A≈B≈C≈D where each adjacent pair is 0.90
(< 0.92) but A and D are the same thing — no single insert ever saw the cluster.

So two thresholds, two mechanisms:

- **≥ ~0.92 → machine-merges at write.** Increment `times_seen`, no LLM. (Current
  `main` behavior.)
- **~0.82–0.92 ("gap band") → Librarian-judged merge on the periodic sweep** (§8).
  This is the band write-time ignores and where judgment is actually needed ("same
  thing, or legitimately different?").
- **< 0.82 → left alone.**

Dedup signals differ by kind:
- **Recipes:** `chash` (exact code match, cheap + exact) **+** cosine on the
  description (near-duplicate *intent*).
- **Pitfalls:** cosine on the `rule`, filtered by `language` + `error_type`. No
  `chash` — the same lesson can carry different illustrative snippets, so code-hash
  is meaningless; intent-similarity is the only signal.

Note (carried from `main`): dedup uses **dense cosine** (a real similarity in
[-1,1]); retrieval uses **RRF** (rank-derived). RRF scores are **not** comparable to
a cosine threshold — keep the two paths distinct.

---

## 8. Linting — a gap-band neighbor sweep, not blind cycling

Periodic linting is **more** important here, because write-time dedup cannot catch
the gap-band clusters. But it should not carry over the file-branch mechanism of
cycling similarity-*sorted* markdown shards and hoping near-dups land adjacent — in
the vector world you don't guess where the similar entries are, **you query for
them.**

- **Cluster-targeted sweep.** Periodically, for each candidate point, run a
  dense-cosine neighbor search and collect any whose nearest neighbor falls in the
  **gap band (~0.82–0.92)**. Hand only those clusters to the Librarian for a judgment
  merge (keep the clearest / most-`times_seen`, `library_remove` the rest). The index
  finds the clusters; the Librarian only judges them.
- **Cursor over the *candidate* set, not the raw library.** You only need to review
  entries that have a close neighbor. The lint cursor walks the gap-band candidate
  list, bounded per pass, for coverage over time.
- **Re-sweep matters** because the candidate set is not static: a 0.90 pair stays
  0.90, but as the library grows new neighbors form *new* clusters that existed at no
  single insert. A periodic re-sweep catches them — this is the drift problem, solved.
- **Cadence reuses the existing machinery** — the persisted `.runcount` dispatch
  counter (every-3 "recent" / every-10 "full"). Point the "full" pass at the
  neighbor sweep instead of the markdown shard.
- **Cost** is N sub-linear queries, off the hot path; bound it to "entries added
  since last lint + their neighbors." CORE needs none of this — it is small enough
  (≤ 12 + 5 per language) that the Librarian sees all of it on every rebalance.

---

## 9. Retrieval routing & graceful degradation

- **Debugger:** `rag_retrieve_mistakes(error_text, language, error_type, class_involved)`.
- **Coder / analyst:** `rag_retrieve_recipes(task, language)` → read the recipe's
  code file via its `path` and adapt.
- **CORE (both kinds):** read from the markdown floor and **always injected** into
  the worker prompt.
- **Graceful degradation:** because CORE is files, the always-injected floor works
  even when Qdrant is down or the embedder is cold — only the on-demand `recall`
  degrades, and the worker still has its can't-miss set. (Optionally, if the regular
  RAG is unavailable, fall back to a simple scan of a flat export — see §10.)

---

## 10. Reuse / new / drop

**Reuse from `main` (largely as-is):**
- `code_recipes` + `codingerrors_and_solutions` collections; `hybrid_search_with_rrf`,
  `apply_rrf`; `_find_dedup_candidate`, `_build_metadata_filter`; `rag_retrieve_*`;
  `save_recipe`, `save_coding_experience` (now called **only** by the Librarian);
  `MIN_*_SCORE`, `DEDUP_SIMILARITY_THRESHOLD`, `bge-large-en-v1.5` + SPLADE.

**New (from the file branch, kept):**
- CORE markdown floor (per-language, fixed caps, always injected); the background
  Librarian + `on_success` dispatch + `skills/learned_memory/SKILL.md`; CORE
  promotion/demotion; the plugin-scope guard (`_PLUGIN_RE` → `scope` metadata; the
  Librarian never promotes a `scope:plugin` point to CORE).
- The gap-band neighbor-sweep linting (§8) with the `.runcount` cadence.

**Drop (made redundant by the vector store):**
- IDF/BM25-lite `_scored`, keyword aliases (`_norm_kw`, the `kw:` tag), manual
  similarity-sorted shard dedup, markdown `seen:` counters, the `_deep_recall` LLM
  fallback (RRF + min-score replace it). Recipe code stays on disk; the rest of the
  per-language markdown *regular* libraries are replaced by Qdrant collections.

---

## 11. Robustness

- **Files are the durable layer; Qdrant is a rebuildable index.** Recipe code lives
  on disk; CORE lives in git-tracked markdown. If the Qdrant index is lost or drifts,
  re-ingest: recipe descriptions from `recipes/code/` + the CORE markdown. The store
  self-heals. (A payload-blob design has no such recovery.)
- **Sync is trivial and self-healing.** `save_recipe` writes the file then upserts
  the point with its `path`; `library_remove` deletes the point then unlinks the
  file. A full re-ingest rebuilds every point from the files.
- **Deterministic write tools** mean the Librarian can judge but never garble the
  format or silently lose an entry outside an explicit remove/merge.

---

## 12. Open questions

- **Optional flat export for fallback recall** — periodically dump the regular
  library to a flat markdown/JSONL so a degraded mode can scan it when Qdrant is
  unavailable. Worth it only if Qdrant uptime is a real concern.
- **`core` as Qdrant metadata vs markdown-only** — CORE membership is the markdown
  floor (source of truth). Mirroring a `core:true` flag into the Qdrant point is
  optional bookkeeping; the floor is what is injected.
- **Gap-band thresholds (0.82 / 0.92)** are starting points — tune against real
  drift once the library has volume.
- **Migration** — the current `bugfix/coder_learning` library is empty, so there is
  nothing to migrate; this can be built directly on top of `main`'s RAG.
