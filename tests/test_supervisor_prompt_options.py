from tests.module_loader import load_source_module


prompts = load_source_module(
    "prompts_under_test",
    "src/imagentj/prompts.py",
)


def test_disabled_supervisor_prompt_contains_no_vlm_instructions():
    prompt = prompts.build_supervisor_prompt(enable_qa=True, enable_vision=False)

    assert "vlm_judge" not in prompt
    assert "VLM" not in prompt
    assert "{{VISION_" not in prompt


def test_enabled_supervisor_prompt_reviews_every_image_producing_step():
    prompt = prompts.build_supervisor_prompt(enable_qa=True, enable_vision=True)

    assert "- vlm_judge:" in prompt
    assert "VLM VISUAL CHECKPOINTS" in prompt
    assert "after EACH image-producing processing step" in prompt
    assert "FINAL PLOT REVIEW" in prompt
    assert "call vlm_judge on each generated PNG figure" in prompt
    assert "clipped, overlapping, overflowing" in prompt
    assert "after each VLM checkpoint" in prompt


def test_disabled_supervisor_prompt_removes_plot_review_instructions():
    prompt = prompts.build_supervisor_prompt(enable_qa=True, enable_vision=False)

    assert "FINAL PLOT REVIEW" not in prompt
    assert "call vlm_judge on each generated PNG figure" not in prompt
    assert "vlm_judge" not in prompt
