from imagentj import config


def test_local_endpoint_reads_its_own_effort_block(monkeypatch):
    monkeypatch.setattr(config, "_CFG", {
        "reasoning_effort": {"supervisor": "high", "nano": None},
        "local_llm": {"reasoning_effort": {"supervisor": "max", "worker": None}},
    })
    monkeypatch.delenv("IMAGENTJ_REASONING_EFFORT", raising=False)

    monkeypatch.delenv("LOCAL_LLM_BASE_URL", raising=False)
    assert config.reasoning_effort_for("supervisor", "low") == "high"

    monkeypatch.setenv("LOCAL_LLM_BASE_URL", "http://host.docker.internal:11434/v1")
    assert config.reasoning_effort_for("supervisor", "low") == "max"
    assert config.reasoning_effort_for("worker", "low") is None  # explicit null
    assert config.reasoning_effort_for("nano", "low") == "low"   # cloud block ignored
