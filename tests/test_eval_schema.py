import pytest
import yaml

from sungrid_copilot.evaluation.schema import EvalSetError, load_eval_set, provenance_note

VALID = {
    "version": 1,
    "questions": [
        {
            "id": "q1",
            "tags": ["billing_account"],
            "turns": [{"say": "When is my bill due?"}],
            "expect": {"category_any": ["billing_account"], "sources": ["bills"],
                       "escalated": True},
            "reference": "Within 21 days.",
        },
        {
            "id": "q2",
            "turns": [{"say": "do I qualify?", "expect_outcome": "needs_info"}, {"say": "94103"}],
        },
    ],
}


def _write(tmp_path, data, header=""):
    path = tmp_path / "questions.yaml"
    path.write_text(header + yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


def test_valid_file_parses(tmp_path):
    s = load_eval_set(_write(tmp_path, VALID), {"bills"})
    assert [q.id for q in s.questions] == ["q1", "q2"]
    assert s.questions[1].text == "do I qualify? || 94103"
    assert s.questions[1].expect.outcome_in is None


@pytest.mark.parametrize(
    "mutate, message",
    [
        (lambda d: d["questions"][0].update(surprise=1), "surprise"),
        (lambda d: d["questions"][0]["expect"].update(sorces=["x"]), "sorces"),
        (lambda d: d["questions"][0]["expect"].update(must_contain=["x"]), "must_contain"),
        (lambda d: d["questions"][0]["expect"].update(must_not_contain=["x"]), "must_not_contain"),
        (lambda d: d["questions"][0]["turns"][0].update(expect="x"), "expect"),
        (lambda d: d["questions"][1].update(id="q1"), "duplicate question ids: q1"),
        (lambda d: d["questions"][0].update(turns=[]), "turns"),
    ],
)
def test_invalid_files_are_rejected(tmp_path, mutate, message):
    import copy

    data = copy.deepcopy(VALID)
    mutate(data)
    with pytest.raises(EvalSetError, match=message):
        load_eval_set(_write(tmp_path, data))


def test_unknown_expected_source_is_rejected(tmp_path):
    with pytest.raises(EvalSetError, match="q1: bills"):
        load_eval_set(_write(tmp_path, VALID), {"other"})


def test_provenance_note_is_read_from_header(tmp_path):
    header = "# Title line\n#\n# Provenance: written after the demos,\n# so not blind.\n#\n# Schema\n"
    path = _write(tmp_path, VALID, header)
    assert provenance_note(path) == "Provenance: written after the demos, so not blind."
