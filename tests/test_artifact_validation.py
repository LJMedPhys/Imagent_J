from pathlib import Path
from typing import Optional

from pydantic import BaseModel

from imagentj.artifact_validation import validate_script_artifact


class FakeHandoff(BaseModel):
    script_path: str
    success: bool
    error_message: Optional[str] = None


def validate(handoff: FakeHandoff, root: Path, suffix: str = ".py") -> FakeHandoff:
    return validate_script_artifact(
        handoff,
        allowed_directory=str(root),
        expected_suffix=suffix,
        producer="test_coder",
    )


def test_accepts_existing_nonempty_script(tmp_path: Path) -> None:
    script = tmp_path / "script.py"
    script.write_text("print('ok')\n", encoding="utf-8")

    result = validate(FakeHandoff(script_path=str(script), success=True), tmp_path)

    assert result.success is True
    assert result.script_path == str(script)
    assert result.error_message is None


def test_rejects_missing_script_and_clears_path(tmp_path: Path) -> None:
    missing = tmp_path / "missing.py"

    result = validate(FakeHandoff(script_path=str(missing), success=True), tmp_path)

    assert result.success is False
    assert result.script_path == ""
    assert "does not exist" in (result.error_message or "")


def test_rejects_empty_script(tmp_path: Path) -> None:
    script = tmp_path / "empty.py"
    script.touch()

    result = validate(FakeHandoff(script_path=str(script), success=True), tmp_path)

    assert result.success is False
    assert "is empty" in (result.error_message or "")


def test_rejects_path_outside_allowed_directory(tmp_path: Path) -> None:
    root = tmp_path / "scripts"
    root.mkdir()
    outside = tmp_path / "outside.py"
    outside.write_text("print('unsafe')\n", encoding="utf-8")

    result = validate(FakeHandoff(script_path=str(outside), success=True), root)

    assert result.success is False
    assert result.script_path == ""
    assert "outside the allowed directory" in (result.error_message or "")


def test_rejects_wrong_extension(tmp_path: Path) -> None:
    script = tmp_path / "script.groovy"
    script.write_text("println 'ok'\n", encoding="utf-8")

    result = validate(FakeHandoff(script_path=str(script), success=True), tmp_path)

    assert result.success is False
    assert "must end with .py" in (result.error_message or "")


def test_preserves_existing_failure_handoff(tmp_path: Path) -> None:
    original = FakeHandoff(
        script_path=str(tmp_path / "missing.py"),
        success=False,
        error_message="original error",
    )

    result = validate(original, tmp_path)

    assert result is original
