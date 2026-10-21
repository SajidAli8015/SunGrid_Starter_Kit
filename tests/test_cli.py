from sungrid_copilot import cli


def test_check_llm_runs_offline_with_fake_provider(monkeypatch, capsys):
    monkeypatch.setenv("LLM_PROVIDER", "fake")
    assert cli.main(["check-llm"]) == 0
    out = capsys.readouterr().out
    assert "Provider: fake" in out
    assert "JSON: {'status': 'ok'}" in out


def test_check_llm_warns_when_no_price_matches(monkeypatch, capsys):
    monkeypatch.setenv("LLM_PROVIDER", "fake")  # config.yaml has no price for the fake provider
    assert cli.main(["check-llm"]) == 0  # a warning, not a failure
    err = capsys.readouterr().err
    assert "no price" in err.lower() and "pricing" in err and "estimated cost" in err.lower()


def test_check_llm_fails_readably_on_missing_config(monkeypatch, capsys):
    monkeypatch.setenv("LLM_PROVIDER", "azure_openai")
    assert cli.main(["check-llm"]) == 1
    captured = capsys.readouterr()
    assert "API key: MISSING" in captured.out
    assert "AZURE_OPENAI_" in captured.err
