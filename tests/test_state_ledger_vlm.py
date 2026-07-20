from tests.module_loader import load_source_module


state_ledger = load_source_module(
    "state_ledger_under_test",
    "src/imagentj/tools/state_ledger.py",
)


def test_vlm_assessment_is_injected_as_advisory_context():
    formatted = state_ledger._format_ledger({
        "project_root": "/app/data/projects/demo",
        "vlm_assessments": [{
            "pipeline_step": "input_review",
            "overall_verdict": "INFO",
            "summary": "Bright objects are visible on a dark, uneven background.",
            "issues_found": ["Mild edge shading"],
        }],
    })

    assert "VLM VISUAL ASSESSMENTS (advisory; confirm quantitatively)" in formatted
    assert "[input_review/INFO]" in formatted
    assert "Mild edge shading" in formatted


def test_latest_vlm_assessment_replaces_stale_verdict(monkeypatch):
    ledger = {}
    monkeypatch.setattr(state_ledger, "_load_ledger", lambda _root: ledger)
    monkeypatch.setattr(state_ledger, "_save_ledger", lambda _root, _ledger: None)

    common = {
        "project_root": "/app/data/projects/demo",
        "vlm_assessment": {
            "pipeline_step": "segmentation",
            "overall_verdict": "FAIL",
            "summary": "Mask is empty.",
        },
    }
    state_ledger.set_ledger_metadata.invoke(common)
    common["vlm_assessment"] = {
        "pipeline_step": "segmentation",
        "overall_verdict": "PASS",
        "summary": "Revised mask follows the objects.",
    }
    state_ledger.set_ledger_metadata.invoke(common)

    assert len(ledger["vlm_assessments"]) == 1
    assert ledger["vlm_assessments"][0]["overall_verdict"] == "PASS"
