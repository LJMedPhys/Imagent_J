"""Deterministic validation for script-producing agent handoffs."""

from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel


HandoffT = TypeVar("HandoffT", bound=BaseModel)


def validate_script_artifact(
    handoff: HandoffT,
    *,
    allowed_directory: str,
    expected_suffix: str,
    producer: str,
) -> HandoffT:
    """Reject a successful handoff unless its script exists and is safe to use.

    Structured output validates JSON shape, not filesystem side effects. This
    postcondition prevents a model from reporting ``success=True`` with a
    plausible but unwritten path. Existing failure handoffs are left untouched
    so callers retain their original diagnostic details.
    """
    if not getattr(handoff, "success", False):
        return handoff

    reported_path = str(getattr(handoff, "script_path", "") or "").strip()
    root = Path(allowed_directory).expanduser().resolve(strict=False)
    suffix = expected_suffix.lower()
    reason = ""

    if not reported_path:
        reason = "no script_path was returned"
    else:
        raw_path = Path(reported_path).expanduser()
        if not raw_path.is_absolute():
            reason = f"script_path is not absolute: {reported_path}"
        else:
            path = raw_path.resolve(strict=False)
            try:
                path.relative_to(root)
            except ValueError:
                reason = f"script_path is outside the allowed directory: {reported_path}"
            else:
                if path.suffix.lower() != suffix:
                    reason = f"script_path must end with {expected_suffix}: {reported_path}"
                elif not path.is_file():
                    reason = f"script file does not exist: {reported_path}"
                elif path.stat().st_size <= 0:
                    reason = f"script file is empty: {reported_path}"

    if not reason:
        return handoff

    updates = {
        "success": False,
        # The Supervisor recovery prompt executes a failure handoff once when it
        # still carries a path, so clear an unverified path.
        "script_path": "",
        "error_message": (
            f"{producer} reported success, but artifact validation failed: {reason}"
        ),
    }
    model_copy = getattr(handoff, "model_copy", None)
    if callable(model_copy):  # Pydantic v2
        return model_copy(update=updates)
    return handoff.copy(update=updates)  # Pydantic v1 compatibility
