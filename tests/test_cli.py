from sungrid_copilot import cli


def test_check_llm_runs_offline_with_fake_provider(monkeypatch, capsys):
    monkeypatch.setenv("LLM_PROVIDER", "fake")
    assert cli.main(["check-llm"]) == 0
    out = capsys.readouterr().out
    assert "Provider: fake" in out
    assert "JSON: {'status': 'ok'}" in out


def test_check_llm_fails_readably_on_missing_config(monkeypatch, capsys):
    monkeypatch.setenv("LLM_PROVIDER", "azure_openai")
    assert cli.main(["check-llm"]) == 1
    captured = capsys.readouterr()
    assert "API key: MISSING" in captured.out
    assert "AZURE_OPENAI_" in captured.err
