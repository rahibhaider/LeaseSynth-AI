"""
test_ai_service.py

What this file DOES verify (for real, no mocking needed):
  - _sanitize_scenario_params never lets malformed/out-of-range model output
    reach the generation engine.
  - With no GROQ_API_KEY configured, every public function fails immediately
    with a clear AIServiceError and makes no network call.
  - With a key configured but no real network path to Groq (true in most
    sandboxes/CI runners), the retry logic runs and surfaces a clean
    AIServiceError rather than crashing or hanging.

What this file does NOT and CANNOT verify: an actual successful round trip
to Groq's API. That needs a real GROQ_API_KEY and outbound internet access.
Test that manually via the Generate Dataset / AI Insights pages once your
.env is configured.
"""

import sys
import os
import json
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from config import Config
import services.ai_service as ai_service
from services.generation_service import PROPERTY_TYPES, LEASE_TYPES


@pytest.fixture(autouse=True)
def restore_config():
    """Each test may mutate Config.* — restore it afterwards so tests don't
    leak state into each other."""
    original = {
        "GROQ_API_KEY": Config.GROQ_API_KEY,
        "AI_ENABLED": Config.AI_ENABLED,
        "GROQ_MAX_RETRIES": Config.GROQ_MAX_RETRIES,
        "GROQ_TIMEOUT_SECONDS": Config.GROQ_TIMEOUT_SECONDS,
    }
    yield
    for key, value in original.items():
        setattr(Config, key, value)


def test_sanitize_fills_defaults_for_missing_fields():
    result = ai_service._sanitize_scenario_params({})
    assert result["property_types"] == PROPERTY_TYPES
    assert result["num_records"] == 500
    assert result["payment_frequencies"] == ["Monthly"]
    assert result["lease_duration_min"] <= result["lease_duration_max"]


def test_sanitize_rejects_values_outside_allowed_sets():
    result = ai_service._sanitize_scenario_params(
        {"property_types": ["Office", "Spaceship Hangar"], "lease_types": ["NNN", "Handshake Deal"]}
    )
    assert result["property_types"] == ["Office"]
    assert result["lease_types"] == ["NNN"]


def test_sanitize_clamps_out_of_range_numbers():
    result = ai_service._sanitize_scenario_params(
        {"num_records": 99999999, "escalation_rate_min": -50, "escalation_rate_max": 500}
    )
    assert 1 <= result["num_records"] <= Config.MAX_RECORDS
    assert 0 <= result["escalation_rate_min"] <= 20
    assert result["escalation_rate_min"] <= result["escalation_rate_max"] <= 20


def test_sanitize_handles_completely_wrong_types_without_crashing():
    result = ai_service._sanitize_scenario_params(
        {"num_records": "a lot please", "lease_duration_min": None, "property_types": "Office"}
    )
    assert isinstance(result["num_records"], int)
    assert isinstance(result["lease_duration_min"], int)
    assert result["property_types"] == PROPERTY_TYPES  # falls back to default, doesn't crash


def test_no_api_key_fails_fast_with_clear_message():
    Config.GROQ_API_KEY = ""
    Config.AI_ENABLED = False
    with pytest.raises(ai_service.AIServiceError) as exc_info:
        ai_service.interpret_scenario("Office leases in Chicago")
    assert "GROQ_API_KEY" in str(exc_info.value)

    with pytest.raises(ai_service.AIServiceError):
        ai_service.generate_insight("What is the average rent?", {"kpis": {}})


def test_scenario_rejects_location_substitution(monkeypatch):
    result = SimpleNamespace(message=SimpleNamespace(content='{"locations": ["New York, NY"]}'))
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(
        create=lambda **kwargs: SimpleNamespace(choices=[result]),
    )))
    monkeypatch.setattr(ai_service, "_get_client", lambda: client)
    Config.GROQ_MAX_RETRIES = 0
    with pytest.raises(ai_service.AIServiceError, match="did not match the scenario"):
        ai_service.interpret_scenario("Generate office leases in Pune, India.")


@pytest.mark.parametrize(
    "description, source, rates, expected",
    [
        ("Generate Dallas leases with annual payments.", None, (0, 0), (2.0, 4.0)),
        ("Generate Dallas leases.", "flat rent", (0, 0), (2.0, 4.0)),
        ("Generate Dallas leases with flat rent.", "flat rent", (0, 0), (0.0, 0.0)),
        ("Generate Dallas leases with 3.5% annual escalation.", "3.5% annual escalation", (3.5, 3.5), (3.5, 3.5)),
        ("Generate Dallas leases with 1% to 2.5% rent increases.", "1% to 2.5% rent increases", (1, 2.5), (1.0, 2.5)),
    ],
)
def test_escalation_rates_require_support_from_scenario(monkeypatch, description, source, rates, expected):
    params = {
        "locations": ["Dallas"],
        "escalation_source": source,
        "escalation_rate_min": rates[0],
        "escalation_rate_max": rates[1],
    }
    result = SimpleNamespace(message=SimpleNamespace(content=json.dumps(params)))
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(
        create=lambda **kwargs: SimpleNamespace(choices=[result]),
    )))
    monkeypatch.setattr(ai_service, "_get_client", lambda: client)

    actual = ai_service.interpret_scenario(description)
    assert (actual["escalation_rate_min"], actual["escalation_rate_max"]) == expected


def test_is_ai_enabled_reflects_config():
    Config.GROQ_API_KEY = ""
    Config.AI_ENABLED = False
    assert ai_service.is_ai_enabled() is False

    Config.GROQ_API_KEY = "gsk_dummy"
    Config.AI_ENABLED = True
    assert ai_service.is_ai_enabled() is True


def test_network_failure_is_caught_and_raises_clean_error():
    """This makes a REAL call attempt with a fake key. In an environment
    without egress to api.groq.com (true for this project's sandbox), the
    SDK raises a connection error, which ai_service must catch and wrap —
    not let bubble up as a raw SDK exception, and not hang indefinitely.
    """
    Config.GROQ_API_KEY = "gsk_dummy_key_for_test_only"
    Config.AI_ENABLED = True
    Config.GROQ_MAX_RETRIES = 0
    Config.GROQ_TIMEOUT_SECONDS = 5

    with pytest.raises(ai_service.AIServiceError):
        ai_service.interpret_scenario("Retail leases in Miami")
