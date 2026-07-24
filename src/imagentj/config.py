"""
config.py — single-file runtime configuration for Imagent_J.

Loads ``imagentj_config.yaml`` (see the shipped file at the repo root for the
schema + docs) and exposes small accessors used by:

  * ``agents.py``            — which LLM backs each agent role, and
  * ``benchmark_gui_hooks``  — whether the Vision (VLM) judge / QA reporter run.

The point is to keep model choice and the optional-agent switches in one
human-editable document instead of scattered env vars. A missing file or a
missing key transparently falls back to the caller-supplied default, so the app
behaves exactly as before if no config is present.

Resolution order (first existing file wins):
  1. ``$IMAGENTJ_CONFIG``
  2. ``/app/imagentj_config.yaml``           (the in-container bind mount)
  3. ``<repo-root>/imagentj_config.yaml``    (dev / host runs)
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Iterator

_log = logging.getLogger("imagentj.config")

_TRUE = {"1", "true", "yes", "on"}


def _candidate_paths() -> Iterator[Path]:
    env = os.environ.get("IMAGENTJ_CONFIG")
    if env:
        yield Path(env)
    yield Path("/app/imagentj_config.yaml")
    # <repo-root>/imagentj_config.yaml  (this file is <root>/src/imagentj/config.py)
    yield Path(__file__).resolve().parents[2] / "imagentj_config.yaml"


def _load() -> dict:
    for path in _candidate_paths():
        try:
            if not path.is_file():
                continue
            import yaml  # lazy: never let a yaml import problem break startup
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            if isinstance(data, dict):
                _log.info("Loaded Imagent_J config from %s", path)
                return data
            _log.warning("Config %s is not a mapping; ignoring.", path)
        except Exception:
            _log.exception("Failed to read config %s; using defaults.", path)
    return {}


_CFG: dict = _load()


def reload() -> dict:
    """Re-read the config file (useful in tests). Returns the new mapping."""
    global _CFG
    _CFG = _load()
    return _CFG


def model_for(role: str, default: str) -> str:
    """Return the configured model id for ``role`` (e.g. 'supervisor'),
    or ``default`` when unset/blank."""
    models = _CFG.get("models") if isinstance(_CFG.get("models"), dict) else {}
    val = models.get(role)
    return val if isinstance(val, str) and val.strip() else default


def _agent_flag(name: str, default: bool = False) -> bool:
    agents = _CFG.get("agents") if isinstance(_CFG.get("agents"), dict) else {}
    val = agents.get(name, default)
    if isinstance(val, bool):
        return val
    return str(val).strip().lower() in _TRUE


def use_vlm() -> bool:
    """True when the Vision (VLM) judge should run (benchmark auto-pilot)."""
    return _agent_flag("vlm", False)


def use_qa() -> bool:
    """True when the QA reporter should run (benchmark auto-pilot)."""
    return _agent_flag("qa", False)
