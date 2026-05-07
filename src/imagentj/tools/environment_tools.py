"""Environment introspection for the supervisor.

Exposes the container snapshot (data/environment/container_snapshot.md) as a
searchable lookup so the agent can verify "is X installed and at what version?"
without dragging the full ~15 KB file into context.
"""

from pathlib import Path
from typing import Dict, List, Optional

from langchain.tools import tool


_CONTAINER_SNAPSHOT = Path("/app/data/environment/container_snapshot.md")
_HOST_SNAPSHOT = (
    Path(__file__).resolve().parents[3] / "data" / "environment" / "container_snapshot.md"
)


def _resolve_snapshot_path() -> Optional[Path]:
    if _CONTAINER_SNAPSHOT.exists():
        return _CONTAINER_SNAPSHOT
    if _HOST_SNAPSHOT.exists():
        return _HOST_SNAPSHOT
    return None


def _parse_sections(text: str) -> Dict[str, List[str]]:
    sections: Dict[str, List[str]] = {"preamble": []}
    current = "preamble"
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("## ") or stripped.startswith("### "):
            current = stripped.lstrip("#").strip()
            sections[current] = []
            continue
        sections[current].append(line)
    return sections


_SECTIONS_CACHE: Optional[Dict[str, List[str]]] = None


def _get_sections() -> Dict[str, List[str]]:
    global _SECTIONS_CACHE
    if _SECTIONS_CACHE is not None:
        return _SECTIONS_CACHE
    path = _resolve_snapshot_path()
    if path is None:
        _SECTIONS_CACHE = {}
        return _SECTIONS_CACHE
    try:
        _SECTIONS_CACHE = _parse_sections(path.read_text(encoding="utf-8"))
    except Exception:
        _SECTIONS_CACHE = {}
    return _SECTIONS_CACHE


def _is_data_row(line: str) -> bool:
    if "|" not in line:
        return False
    if "---" in line:
        return False
    if line.strip().lower().startswith("| package "):
        return False
    if line.strip().lower().startswith("| jar "):
        return False
    if line.strip().lower().startswith("| component "):
        return False
    return bool(line.strip())


@tool
def check_environment(query: str = "", section: str = "") -> str:
    """
    Look up software installed in the running container.

    Use this to verify whether a Python package, Fiji plugin, Fiji jar, or
    system tool is available BEFORE recommending it in a pipeline. Cheaper
    than reading the full snapshot file.

    Args:
        query: Case-insensitive substring. Examples: "stardist",
               "scikit-image", "cuda", "trackmate", "java". Leave empty
               (with `section=`) to list every entry in one section.
        section: Optional. Limit the search to one section. Pass "list" to
                 see all section names. Common sections:
                 "System / runtime", "Main conda env", "Appose / DeepImageJ env",
                 "Fiji plugins", "Key Fiji jars".

    Returns:
        Matching rows grouped by section, "no match" if absent, or an
        error string if the snapshot file is missing.
    """
    sections = _get_sections()
    if not sections:
        return (
            "Container snapshot not available. Expected at "
            f"{_CONTAINER_SNAPSHOT} (or {_HOST_SNAPSHOT} on the host). "
            "Regenerate the snapshot or ask the user."
        )

    if section.strip().lower() == "list":
        names = [name for name in sections if name and name != "preamble"]
        return "Available sections:\n- " + "\n- ".join(names)

    q = query.strip().lower()
    sec_filter = section.strip().lower()

    if sec_filter:
        target = [s for s in sections if sec_filter in s.lower() and s != "preamble"]
        if not target:
            return (
                f"No section matches '{section}'. "
                "Call check_environment(section='list') to see options."
            )
    else:
        target = [s for s in sections if s != "preamble"]

    out: List[str] = []
    total_matches = 0
    CAP = 60
    for s in target:
        rows = [line for line in sections[s] if _is_data_row(line)]
        matches = [r for r in rows if q in r.lower()] if q else rows
        if not matches:
            continue
        out.append(f"## {s}")
        out.extend(matches[:CAP])
        if len(matches) > CAP:
            out.append(f"... ({len(matches) - CAP} more rows truncated; refine your query)")
        out.append("")
        total_matches += len(matches)

    if not out:
        if q:
            return (
                f"No match for '{query}' in container snapshot — package/plugin "
                "likely NOT installed. If you need it, ask plugin_manager (Fiji) "
                "or instruct the user to install it."
            )
        return "Snapshot section is empty."

    return "\n".join(out).strip()
