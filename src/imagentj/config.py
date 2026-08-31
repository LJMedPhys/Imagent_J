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
from typing import Iterator, Optional

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


#: Sentinel distinguishing "key absent" from an explicit ``null``. A role set to
#: null in YAML means "send no reasoning_effort at all", which is a real choice
#: (the nano role ships that way) and not the same as falling back to a default.
_UNSET = object()


def local_model_for(role: str, default: str = "moonshotai/Kimi-K3") -> str:
    """Return the model id exposed by the local OpenAI-compatible server.

    ``local_llm.models.<role>`` can override individual roles; otherwise all
    roles share ``local_llm.model``.  This is deliberately separate from the
    cloud ``models`` mapping so enabling/disabling the local endpoint never
    requires rewriting the user's OpenAI/OpenRouter choices.
    """
    local = _CFG.get("local_llm") if isinstance(_CFG.get("local_llm"), dict) else {}
    models = local.get("models") if isinstance(local.get("models"), dict) else {}
    role_val = models.get(role)
    if isinstance(role_val, str) and role_val.strip():
        return role_val.strip()
    common = local.get("model")
    if isinstance(common, str) and common.strip():
        return common.strip()
    return default


def local_api(default: str = "responses") -> str:
    """Return the protocol shared by every role on the local endpoint."""
    local = _CFG.get("local_llm") if isinstance(_CFG.get("local_llm"), dict) else {}
    val = local.get("api")
    return val.strip().lower() if isinstance(val, str) and val.strip() else default


def _effort_from_block(block, role: str):
    """Read one role out of a reasoning-effort block.

    Returns ``_UNSET`` when the role is absent, so the caller falls through to
    the next source; returns ``None`` when the role is explicitly ``null``,
    which means "send no reasoning_effort at all" and must not fall through.
    """
    if not isinstance(block, dict) or role not in block:
        return _UNSET
    val = block[role]
    if val is None:
        return None
    if isinstance(val, str) and val.strip():
        return val.strip()
    # A non-string, non-null value is a config error; fall through rather
    # than pass something the endpoint will reject.
    return _UNSET


def reasoning_effort_for(role: str, default: Optional[str] = None) -> Optional[str]:
    """Return the configured reasoning effort for ``role``, or ``default``.

    Mirrors :func:`model_for`. Precedence, highest first:

    1. ``IMAGENTJ_<ROLE>_REASONING_EFFORT`` — one role, for A/B runs;
    2. ``local_llm.reasoning_effort.<role>``, consulted only while
       ``LOCAL_LLM_BASE_URL`` is set. A local model's ladder need not match the
       cloud one — Kimi K3 takes low/high/max where the cloud roles ship
       "medium" — so the local profile carries its own block rather than having
       one vocabulary forced onto both;
    3. ``reasoning_effort.<role>`` in imagentj_config.yaml — including an
       explicit ``null``, which means "send nothing" and is preserved as None;
    4. ``IMAGENTJ_REASONING_EFFORT`` — the pre-existing blanket env override,
       kept as a fallback so current deployments behave identically;
    5. ``default`` — this role's shipped value.

    The blanket env var deliberately does NOT win over an explicit per-role
    setting: the point of the block is to declare effort per role, and a
    blanket env var silently overriding one would defeat that. The per-role
    env var does win, because it names the same role — there is nothing it
    could silently override.
    """
    role_env = os.environ.get(f"IMAGENTJ_{role.upper()}_REASONING_EFFORT", "").strip()
    if role_env:
        return role_env

    if os.environ.get("LOCAL_LLM_BASE_URL", "").strip():
        local = _CFG.get("local_llm") if isinstance(_CFG.get("local_llm"), dict) else {}
        val = _effort_from_block(local.get("reasoning_effort"), role)
        if val is not _UNSET:
            return val

    val = _effort_from_block(_CFG.get("reasoning_effort"), role)
    if val is not _UNSET:
        return val

    env = os.environ.get("IMAGENTJ_REASONING_EFFORT", "").strip()
    if env:
        return env
    return default


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
