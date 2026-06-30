"""learned_memory.py — the agent's learned-memory loop, curated by a background
"Librarian" subagent on top of the Qdrant RAG (tools/rag_tools.py).

ARCHITECTURE (combined RAG + Librarian):
  * The REGULAR library of PITFALLS (error->fix lessons) and RECIPES (reusable
    scripts) lives in Qdrant — semantic hybrid recall, write-time cosine dedup,
    per-language/error_type filters (see rag_tools.store_*). Workers pull it on
    demand via the rag_retrieve_mistakes / rag_retrieve_recipes tools.
  * The CORE floor — a small, fixed-size, per-language set that is ALWAYS injected —
    is a DERIVED MARKDOWN CACHE here (pitfalls/CORE.<Lang>.md, recipes/CORE.<Lang>.md).
    core_pitfalls()/core_recipes() read those files: bulletproof + zero-dependency, so
    the can't-miss floor works even if Qdrant is down. library_set_core (and a core add)
    regenerate the cache FROM Qdrant; recall EXCLUDES core points (already injected).
  * RECIPE CODE is kept as runnable files on disk (recipes/code/<chash>.<ext>); the
    Qdrant recipe point stores only name+description (embedded) + a `path` pointer.
  * The Librarian is the SOLE writer. on_success() fires it in a BACKGROUND thread on
    every verified-green run (the task never waits) — to file the new recipe AND/OR the
    debugger's buffered error->fix lesson, dedup, and (periodically) sweep near-dup
    clusters + rebalance CORE. It acts ONLY through the deterministic library_* tools
    below, which delegate to rag_tools, so it can judge but never garble the store.
"""
import os
import re
import hashlib
import datetime
import threading
from typing import Dict, List

from langchain.tools import tool

from .rag_tools import (
    store_save_pitfall, store_save_recipe, store_remove, store_set_core,
    store_list_core, store_snapshot, store_neighbor_clusters, store_recipe_exists,
)
from .vector_stores import is_learning_rag_available

ROOT = os.environ.get("LEARNED_ROOT", "/app/data/learned")   # writable (skills/ is read-only)
PITFALLS_DIR = os.path.join(ROOT, "pitfalls")
RECIPES_DIR = os.path.join(ROOT, "recipes")
RECIPE_CODE_DIR = os.path.join(RECIPES_DIR, "code")
LOG_PATH = os.path.join(ROOT, "log.md")

# CORE is per-language so the Python analyst never sees Groovy entries; each caps
# independently. CORE membership is a Qdrant flag; these files are the injected cache.
CORE_MAX = 12             # fixed cap on CORE pitfalls per language
CORE_RECIPE_MAX = 5       # fixed cap on featured recipes per language
# Two-tier lint cadence (a persisted, restart-proof dispatch counter drives it):
#  - every LINT_RECENT_EVERY-th dispatch: a snapshot dedup pass (cheap).
#  - every LINT_FULL_EVERY-th dispatch:   a gap-band neighbor SWEEP + CORE rebalance.
LINT_RECENT_EVERY = 3
LINT_FULL_EVERY = 10
RECIPE_MIN_CHARS = 200    # below this, too trivial to be a reusable recipe

_EXT = {".groovy": "Groovy", ".py": "Python"}
_LOCK = threading.Lock()
_PENDING: Dict[str, dict] = {}                       # script_path -> buffered failure->fix lesson
_RUNCOUNT_PATH = os.path.join(ROOT, ".runcount")     # persisted dispatch counter (survives restarts)
_COMMENT_RE = re.compile(r"\s*<!--.*?-->")
# Plugin/environment-specific lessons are NEVER promoted to CORE: version/install-site
# specific, so injecting them into every run is noise (and can be wrong elsewhere).
# Match REAL plugin/environment signals only — NOT the bare word "plugin" (ImageJ's own
# classes live in ij.plugin.*, so "plugin" alone false-flags ordinary import lessons).
_PLUGIN_RE = re.compile(
    r"(update[\s-]?site|not installed|isn'?t installed|missing dependency|"
    r"install (?:the )?\S+ plugin|enable (?:the )?\S+ update site)", re.I)

__all__ = ["register_pending_lesson", "on_success", "core_pitfalls", "core_recipes",
           "library_add_pitfall", "library_add_recipe", "library_remove",
           "library_set_core"]


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _hash(s: str) -> str:
    return hashlib.sha1((s or "").strip().encode("utf-8")).hexdigest()[:8]

def _read(path: str) -> str:
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""

def _core_pitfall_page(language: str) -> str:
    return os.path.join(PITFALLS_DIR, f"CORE.{language}.md")

def _core_recipe_page(language: str) -> str:
    return os.path.join(RECIPES_DIR, f"CORE.{language}.md")

def _is_plugin(rule: str, error_type: str, class_involved: str) -> bool:
    return ((error_type or "").strip().lower() == "plugin"
            or bool(_PLUGIN_RE.search(" ".join((rule or "", class_involved or "")))))

def _log(language: str, kind: str, etype: str, h: str, summary: str) -> None:
    try:
        os.makedirs(ROOT, exist_ok=True)
        ts = datetime.datetime.utcnow().isoformat(timespec="seconds")
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"{ts} | {language} | {kind} | {etype} | {h} | {(summary or '')[:100]}\n")
    except OSError:
        pass

def _bump_runcount() -> int:
    """Persisted, restart-proof count of Librarian dispatches, so 'every Nth run' is a
    true cumulative count, not reset on reboot."""
    with _LOCK:
        try:
            n = int(_read(_RUNCOUNT_PATH).strip() or "0")
        except ValueError:
            n = 0
        n += 1
        try:
            os.makedirs(ROOT, exist_ok=True)
            with open(_RUNCOUNT_PATH, "w", encoding="utf-8") as f:
                f.write(str(n))
        except OSError:
            pass
    return n


# --------------------------------------------------------------------------- #
# CORE markdown cache — regenerated FROM Qdrant; read for always-injection.
# --------------------------------------------------------------------------- #
def _regen_core(language: str, kind: str) -> None:
    """Rewrite the CORE.<lang>.md cache for this kind from the current CORE points in
    Qdrant. Guarded: if the learning RAG is unavailable, DO NOT clobber the cache (a
    transient outage must not erase the always-injected floor)."""
    if not is_learning_rag_available():
        return
    page = _core_pitfall_page(language) if kind == "pitfall" else _core_recipe_page(language)
    entries = store_list_core(language, kind)        # sorted by times_seen desc
    cap = CORE_MAX if kind == "pitfall" else CORE_RECIPE_MAX
    entries = entries[:cap]
    lines = [f"# CORE {kind}s — {language} (always injected; auto-generated from "
             f"Qdrant — do not edit by hand)"]
    for e in entries:
        tag = f"  <!--{e.get('ehash')} seen:{e.get('times_seen', 1)}-->"
        if kind == "pitfall":
            lines.append(f"- {e.get('rule', '')}{tag}")
            for ln in (e.get("snippet") or "").splitlines():
                if ln.strip():
                    lines.append("    " + ln)
        else:
            lines.append(f"- {e.get('name', '')}  [inputs: {e.get('inputs', '')}]{tag}")
            if e.get("description"):
                lines.append("  " + e["description"])
            lines.append(f"  SCRIPT: {e.get('path', '')}")
    try:
        os.makedirs(os.path.dirname(page), exist_ok=True)
        with open(page, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    except OSError:
        pass

def _enforce_and_regen(language: str, kind: str) -> None:
    """Re-assert the cap on CORE (keep highest times_seen) and regenerate the cache."""
    cap = CORE_MAX if kind == "pitfall" else CORE_RECIPE_MAX
    current = [e["ehash"] for e in store_list_core(language, kind) if e.get("ehash")]
    if current:
        store_set_core(language, kind, current, cap)
    _regen_core(language, kind)

def _read_core_body(page: str) -> str:
    txt = _read(page)
    body = "\n".join(ln for ln in txt.splitlines() if not ln.lstrip().startswith("#"))
    return _COMMENT_RE.sub("", body).strip("\n")

def core_pitfalls(language: str = "Groovy") -> str:
    """The always-injected CORE pitfalls for this language (read from the markdown
    cache — works even if Qdrant is down)."""
    body = _read_core_body(_core_pitfall_page(language))
    if not body.strip():
        return ""
    return ("KNOWN PITFALLS (verified lessons from past failures — apply "
            "unconditionally where the same class/call appears):\n" + body)

def core_recipes(language: str = "Groovy") -> str:
    """The always-injected featured recipes for this language (from the markdown cache)."""
    body = _read_core_body(_core_recipe_page(language))
    if not body.strip():
        return ""
    return ("FEATURED RECIPES (verified reusable scripts — read a SCRIPT path for "
            "the code, then ADAPT it, do not copy verbatim):\n" + body)


# --------------------------------------------------------------------------- #
# CAPTURE — the debugger/analyst buffers the error->fix lesson here; on_success
# hands it (plus any verified recipe) to the background Librarian.
# --------------------------------------------------------------------------- #
def register_pending_lesson(script_path: str, *, language: str, rule: str,
                            failed_code: str = "", working_code: str = "",
                            error_type: str = "Logic", class_involved: str = "") -> None:
    if not script_path or not (rule or "").strip():
        return
    _PENDING[os.path.abspath(script_path)] = {
        "language": language or "Groovy", "rule": rule.strip(),
        "failed_code": failed_code or "", "working_code": working_code or "",
        "error_type": error_type or "Logic", "class_involved": class_involved or "",
    }

def _run_succeeded(out: str) -> bool:
    if not out or "STATUS: ERROR" in out:
        return False
    return ("STATUS: SUCCESS" in out or "STATUS: WARNING" in out
            or out.lstrip().startswith("SUCCESS:"))


# --------------------------------------------------------------------------- #
# LIBRARIAN TOOLS — the ONLY way the store is mutated. Delegate to rag_tools so the
# Qdrant format/invariants can never be garbled by a bad plan.
# --------------------------------------------------------------------------- #
@tool("library_add_pitfall")
def library_add_pitfall(language: str, rule: str, snippet: str = "",
                        error_type: str = "Logic", class_involved: str = "",
                        core: bool = False) -> str:
    """Add a verified error->fix lesson. `rule` is one imperative line (symptom AND
    fix) — this is what gets EMBEDDED, so write the symptom the way a future error
    would read; `snippet` is a minimal working fix (stored, not embedded). Set
    core=True ONLY for a broadly-useful, recurring/high-severity trap (plugin/
    environment-specific lessons are forced to the regular library). Near-duplicates
    are auto-merged (times_seen bumped) — skip obvious repeats."""
    rule = (rule or "").strip()
    if not rule:
        return "skipped: empty rule"
    language = language or "Groovy"
    h = _hash(rule)
    scope = "plugin" if _is_plugin(rule, error_type, class_involved) else "general"
    to_core = bool(core) and scope != "plugin"
    res = store_save_pitfall(language, rule, snippet=snippet, failed_code="",
                             error_type=error_type, class_involved=class_involved,
                             scope=scope, ehash=h, core=to_core)
    status = res.get("status")
    if status == "unavailable":
        return "skipped: learning store unavailable"
    _log(language, "pitfall", error_type or "Logic", h, rule)
    if to_core and status == "added":
        _enforce_and_regen(language, "pitfall")
    return f"{status} {'CORE ' if to_core else ''}pitfall [{h}] {rule[:60]}"

@tool("library_add_recipe")
def library_add_recipe(language: str, name: str, description: str, inputs: str,
                       source_path: str, core: bool = False) -> str:
    """File a VERIFIED, just-run script as a recipe. `source_path` is the working
    script; its CODE is copied to a runnable file on disk and the store keeps a `path`
    pointer + content hash (the code is never embedded). Write a short reusable `name`,
    a 1-3 sentence `description` (what it does + when to use it) — this is what gets
    EMBEDDED for retrieval — and the `inputs` it expects. Set core=True only for a
    broadly-reusable workflow; one-offs go to the regular library (still saved, just
    not featured). Near-duplicates are auto-merged."""
    name = (name or "").strip()
    if not name or not source_path or not os.path.isfile(source_path):
        return "skipped: need a name and an existing source_path"
    language = language or _EXT.get(os.path.splitext(source_path)[1].lower()) or "Groovy"
    try:
        code = open(source_path, encoding="utf-8").read()
    except OSError:
        return "skipped: could not read source_path"
    if len(code.strip()) < RECIPE_MIN_CHARS:
        return "skipped: too trivial"
    chash = _hash(code)
    ext = ".py" if language == "Python" else ".groovy"
    code_path = os.path.join(RECIPE_CODE_DIR, f"{chash}{ext}")
    try:
        os.makedirs(RECIPE_CODE_DIR, exist_ok=True)
        if not os.path.exists(code_path):
            with open(code_path, "w", encoding="utf-8") as f:
                f.write(code)
    except OSError:
        return "skipped: could not write recipe code"
    h = _hash(name)
    res = store_save_recipe(language, name, description, inputs, code_path, chash,
                            ehash=h, core=bool(core))
    status = res.get("status")
    if status == "unavailable":
        return "skipped: learning store unavailable"
    _log(language, "recipe", "core" if core else "lib", h, name)
    if bool(core) and status == "added":
        _enforce_and_regen(language, "recipe")
    # A description-dup (cosine) with DIFFERENT code leaves the file we just wrote
    # orphaned (no point references it) — remove it. A chash-dup reuses an existing
    # file, so leave that alone.
    if status == "bumped" and res.get("reason") != "chash":
        try:
            if os.path.exists(code_path):
                os.remove(code_path)
        except OSError:
            pass
    return f"{status} {'CORE ' if core else ''}recipe [{h}] {name}"

@tool("library_remove")
def library_remove(entry_hash: str) -> str:
    """Delete an entry by its [ehash] — to clean up a duplicate or a wrong entry. For a
    recipe, its stored code file is removed too. Bump the kept duplicate first with
    library_add_* if you want it to absorb the seen count."""
    entry_hash = (entry_hash or "").strip()
    if not entry_hash:
        return "skipped: no hash"
    info = store_remove(entry_hash)
    if info.get("code_path"):
        try:
            os.remove(info["code_path"])
        except OSError:
            pass
    if info.get("was_core") and info.get("language") and info.get("kind"):
        _regen_core(info["language"], info["kind"])
    n = info.get("removed", 0)
    return f"removed [{entry_hash}] from {n} point(s)" if n else f"no entry [{entry_hash}]"

@tool("library_set_core")
def library_set_core(language: str, kind: str, core_hashes: str) -> str:
    """Set CORE membership for a language. `kind` is "pitfall" or "recipe";
    `core_hashes` is a comma-separated list of the [ehash]es that should be CORE. Does
    BOTH promotion (regular->CORE) and demotion (CORE->regular) and enforces the fixed
    cap (12 pitfalls / 5 recipes per language; least-seen dropped if over). Plugin/
    environment-specific pitfalls are never kept in CORE."""
    kind = "recipe" if "recip" in (kind or "").lower() else "pitfall"
    language = language or "Groovy"
    cap = CORE_MAX if kind == "pitfall" else CORE_RECIPE_MAX
    hashes = [h.strip() for h in re.split(r"[,\s]+", core_hashes or "") if h.strip()]
    result = store_set_core(language, kind, hashes, cap)
    _regen_core(language, kind)
    names = ", ".join(e.get("ehash", "") for e in result) or "(none)"
    return f"CORE {kind}s for {language} set to {len(result)} entr(y/ies): {names}"


# --------------------------------------------------------------------------- #
# DISPATCH — fire the background Librarian on a verified-green run. Never blocks.
# --------------------------------------------------------------------------- #
def _script_description(directory: str, filename: str) -> str:
    try:
        import json
        with open(os.path.join(directory, "script_dictionary.json"), encoding="utf-8") as f:
            return (json.load(f).get(filename) or {}).get("description", "")
    except Exception:
        return ""

def on_success(directory: str, filename: str, execute_output: str) -> None:
    """Called by execute_script after EVERY run. On a verified-green run that has
    something to learn — a reusable new recipe, OR a debugger error->fix lesson — fire
    the background Librarian. The task never waits on it."""
    if not _run_succeeded(execute_output):
        return
    language = _EXT.get(os.path.splitext(filename)[1].lower())
    if not language:
        return
    full = os.path.join(directory, filename)
    pending = _PENDING.pop(os.path.abspath(full), None)    # the debugger's pitfall fix, if any
    try:
        code = open(full, encoding="utf-8").read()
    except OSError:
        code = ""
    recipe_ok = (len(code.strip()) >= RECIPE_MIN_CHARS
                 and not store_recipe_exists(language, _hash(code)))
    if not recipe_ok and not pending:
        return                                             # nothing new to learn
    n = _bump_runcount()
    mode = ("full" if n % LINT_FULL_EVERY == 0
            else "recent" if n % LINT_RECENT_EVERY == 0 else None)
    desc = _script_description(directory, filename)
    threading.Thread(target=_librarian_bg, daemon=True,
                     args=(language, full, recipe_ok, desc, pending, mode)).start()


# --------------------------------------------------------------------------- #
# Snapshot / cluster rendering for the Librarian prompt
# --------------------------------------------------------------------------- #
def _e_line(e: dict) -> str:
    if e.get("kind") == "recipe" or "name" in e:
        txt = e.get("name", "")
        if e.get("description"):
            txt += f" — {e['description'][:90]}"
    else:
        txt = e.get("rule", "")
    return f"  [{e.get('ehash')} seen:{e.get('times_seen', 1)}] {txt[:140]}"

def _render_snapshot(snap: dict) -> str:
    def sect(label, items):
        return f"{label}:\n" + ("\n".join(_e_line(e) for e in items) or "  (none)")
    return "\n".join((
        f"LIBRARY SNAPSHOT (language={snap.get('language')})",
        sect(f"CORE PITFALLS (cap {CORE_MAX})", snap.get("core_pitfalls", [])),
        sect("REGULAR PITFALLS (top by seen)", snap.get("reg_pitfalls", [])),
        sect(f"CORE RECIPES (cap {CORE_RECIPE_MAX})", snap.get("core_recipes", [])),
        sect("REGULAR RECIPES (top by seen)", snap.get("reg_recipes", [])),
    ))

def _render_clusters(clusters: list) -> str:
    out = []
    for c in clusters:
        members = "  ||  ".join(_e_line(m).strip() for m in c.get("members", []))
        out.append(f"  ({c.get('kind')}, cosine={c.get('cosine')}) {members}")
    return "\n".join(out)

def _librarian_bg(language, full, recipe_ok, desc, pending, mode) -> None:
    lint = mode in ("recent", "full")
    snap = store_snapshot(language, full=lint)
    parts = [f"A script just ran GREEN (verified). Maintain the {language} learned-memory "
             f"store, following the learned_memory skill. Act ONLY through the library_* "
             f"tools.", "", _render_snapshot(snap), ""]
    if recipe_ok:
        try:
            head = "\n".join(open(full, encoding="utf-8").read().splitlines()[:18])
        except OSError:
            head = ""
        parts += [f"NEW RECIPE CANDIDATE (verified working script):\n  source_path: {full}\n"
                  f"  description hint: {desc or '(none)'}\n  first lines:\n{head}", ""]
    if pending:
        snip = "\n".join((pending.get("working_code") or "").splitlines()[:8])
        parts += [f"NEW PITFALL CANDIDATE (the fix that produced this green run):\n"
                  f"  rule: {pending['rule']}\n  error_type: {pending.get('error_type')} "
                  f"class: {pending.get('class_involved')}\n  working snippet:\n{snip}", ""]
    if mode == "full":
        clusters = store_neighbor_clusters(language)
        if clusters:
            parts += ["NEAR-DUPLICATE CLUSTERS (cosine in the gap band — judge whether each "
                      "pair is the SAME entry; if so library_remove the weaker/less-seen one, "
                      "keeping the clearer one):", _render_clusters(clusters), ""]
        parts.append(
            "DEDUP/REBALANCE RUN. DO: (1) file each NEW candidate above that is genuinely "
            "novel (near-dups are auto-merged, so just skip obvious repeats). (2) For each "
            "NEAR-DUPLICATE CLUSTER, library_remove the redundant entry, keeping the clearest/"
            "most-seen one. (3) REBALANCE CORE for pitfalls and recipes with library_set_core: "
            "promote the most broadly-reusable, high-value entries and demote stale/narrow "
            "ones, within the caps. Only act on entries shown above.")
    elif mode == "recent":
        parts.append(
            "DEDUP RUN. DO: (1) file each NEW candidate above that is genuinely novel. "
            "(2) If any entries in the snapshot are clear duplicates of each other (same "
            "operation/workflow, or same root cause + fix), library_remove the weaker one, "
            "keeping the clearer/most-seen. Do NOT rebalance CORE this run.")
    else:
        parts.append(
            "DO: file each NEW candidate above that is genuinely novel (skip an obvious "
            "duplicate of an existing entry). Do NOT audit/remove existing entries or "
            "rebalance CORE this run; only set core=True when a new entry is clearly, "
            "broadly reusable.")
    try:
        from ..agents import librarian_agent
    except Exception:
        librarian_agent = None
    if librarian_agent is None:                            # resilient fallback: never lose data
        if recipe_ok:
            library_add_recipe.invoke({"language": language, "name": (desc or "recipe")[:60],
                                       "description": desc or "", "inputs": "",
                                       "source_path": full, "core": False})
        if pending:
            library_add_pitfall.invoke({"language": language, "rule": pending["rule"],
                                        "snippet": pending.get("working_code", ""),
                                        "error_type": pending.get("error_type", "Logic"),
                                        "class_involved": pending.get("class_involved", "")})
        return
    try:
        librarian_agent.invoke({"messages": [{"role": "user", "content": "\n".join(parts)}]})
    except Exception:
        pass
