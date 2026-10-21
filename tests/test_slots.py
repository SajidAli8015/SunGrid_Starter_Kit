import json

import pytest
from pydantic import ValidationError

from sungrid_copilot.eligibility.slots import EligibilitySlots, SlotExtractor, extract_slots
from sungrid_copilot.llm.fake import FakeLLMClient

FULL_JSON = json.dumps(
    {
        "household_zip": "94103",
        "annual_income_usd": 85000,
        "system_size_kw": 7.5,
        "installer_approved": True,
        "member_tier": "household",
    }
)


def test_missing_is_ordered():
    assert EligibilitySlots(system_size_kw=5).missing() == [
        "household_zip",
        "annual_income_usd",
        "installer_approved",
        "member_tier",
    ]
    assert EligibilitySlots.model_validate_json(FULL_JSON).missing() == []


def test_merge_new_values_override_and_nulls_keep_existing():
    old = EligibilitySlots(household_zip="94101", system_size_kw=5, installer_approved=True)
    new = EligibilitySlots(system_size_kw=7.5, installer_approved=False)
    merged = old.merge(new)
    assert merged.household_zip == "94101"
    assert merged.system_size_kw == 7.5
    assert merged.installer_approved is False  # an explicit False overrides
    assert old.system_size_kw == 5  # merge does not mutate


def test_strict_bool_and_no_bool_numbers():
    for bad in ["yes", "no", 1, "true"]:
        with pytest.raises(ValidationError):
            EligibilitySlots(installer_approved=bad)
    with pytest.raises(ValidationError):
        EligibilitySlots(annual_income_usd=True)
    with pytest.raises(ValidationError):
        EligibilitySlots(member_tier="gold")


def test_zip_number_is_kept_as_string():
    assert EligibilitySlots.model_validate({"household_zip": 94103}).household_zip == "94103"


def test_extraction_valid_json():
    client = FakeLLMClient([FULL_JSON])
    slots = extract_slots(client, "I live in 94103 ...")
    assert slots.missing() == []
    assert client.calls[0].temperature == 0.0
    assert "<message>" in client.calls[0].messages[0]["content"]


def test_extraction_fenced_json():
    client = FakeLLMClient(['```json\n{"system_size_kw": 5}\n```'])
    assert extract_slots(client, "5kW").system_size_kw == 5


def test_extraction_invalid_then_valid():
    client = FakeLLMClient(['{"installer_approved": "probably"}', '{"installer_approved": null}'])
    slots = extract_slots(client, "my installer is probably approved")
    assert slots.installer_approved is None
    assert len(client.calls) == 2


def test_extraction_merges_over_prior_and_says_what_was_asked():
    prior = EligibilitySlots(household_zip="94101", system_size_kw=5)
    client = FakeLLMClient(['{"installer_approved": true, "household_zip": null}'])
    slots = extract_slots(client, "yes it was", prior)
    assert slots.household_zip == "94101" and slots.installer_approved is True
    assert "asked for: annual_income_usd, installer_approved, member_tier" in (
        client.calls[0].messages[0]["content"]
    )


def test_extraction_cache(tmp_path):
    client = FakeLLMClient([FULL_JSON])
    first = SlotExtractor(client, cache_dir=tmp_path).extract("text")
    second = SlotExtractor(client, cache_dir=tmp_path).extract("text")
    assert first == second and len(client.calls) == 1


def test_installer_definition_matches_the_clarifying_question():
    """The extractor must use the same installer test as the question it replaces (F1)."""
    from sungrid_copilot.config import load_settings
    from sungrid_copilot.messages import Messages

    question = Messages.load(load_settings().messages.resolved_file).text("q_installer_approved")
    client = FakeLLMClient(default=FULL_JSON)
    SlotExtractor(client).extract("do I qualify?")
    system = client.calls[0].system.lower()
    for phrase in ("approved installer list", "at the time of installation"):
        assert phrase in question.lower() and phrase in system, phrase
    assert "electrician who did the work" in system
    assert "lapse" in system and "false" in system  # a lapse during the install is false
    assert "null for anything weaker" in system


# Found in a live check (gpt-4o): this phrasing came back false although the timing of the lapse
# relative to the installation is not stated. The rule must make it null so the question is asked.
LAPSE_TIMING_UNSTATED = "The installer was approved, but their certification lapsed sometime last year."


def test_lapse_with_unstated_timing_is_unknown_and_asked():
    from sungrid_copilot.config import load_settings
    from sungrid_copilot.eligibility.questions import build_clarifying_question
    from sungrid_copilot.messages import Messages

    client = FakeLLMClient(default=json.dumps({"installer_approved": None}))
    slots = SlotExtractor(client).extract(LAPSE_TIMING_UNSTATED)
    system = client.calls[0].system
    rule = " ".join(system.split("3. installer_approved:")[1].split("\n4.")[0].split())
    assert "false only if" in rule and "a lapse overlapped the installation" in rule
    assert "null if a lapse is mentioned but the member does not say whether it overlapped" in rule

    messages = Messages.load(load_settings().messages.resolved_file)
    assert slots.installer_approved is None
    question = build_clarifying_question(slots.missing(), messages)
    assert messages.text("q_installer_approved") in question
