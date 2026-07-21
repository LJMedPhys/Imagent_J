from pathlib import Path


PHASES = Path(__file__).parents[1] / "skills/workflow/supervisor_pipeline_phases"


def test_phase_4a_explicitly_requests_conditional_input_visual_review():
    content = (PHASES / "phase_4a_io_check.md").read_text(encoding="utf-8")

    assert "INPUT VISUAL REVIEW" in content
    assert "When `vlm_judge` is available in the current tools" in content
    assert 'pipeline_step="input_review"' in content
    assert "alongside `extract_image_metadata`" in content


def test_phase_4d_explicitly_requests_conditional_plot_visual_review():
    content = (PHASES / "phase_4d_plotting.md").read_text(encoding="utf-8")

    assert "FINAL PLOT VISUAL REVIEW" in content
    assert "When `vlm_judge` is available in the current tools" in content
    assert 'pipeline_step="plotting:<figure_filename>"' in content
    assert "once on each generated PNG" in content
    assert "review the regenerated PNG" in content
