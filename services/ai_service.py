"""
ai_service.py — Groq / LLaMA integration.

Two jobs:
  1. interpret_scenario(text)   -> turn a free-text scenario description
     into structured generation parameters.
  2. generate_insight(question, stats) -> answer a question about the
     dataset using ONLY the pre-computed pandas statistics handed to it.
     The model is explicitly instructed never to invent a number, and
     this module never sends it raw per-record data — only aggregates.

If GROQ_API_KEY is not configured, every public function here raises
AIServiceError immediately (no network call attempted) so app.py can
show a clear message and keep the rest of the app — manual generation
in particular — fully working without AI.

A note on testing: this module is tested in this project for (a) the
"no API key configured" path and (b) real network/connection failures,
both of which are exercised for real in tests/test_ai_service.py. A full
successful round trip to Groq's API requires a real GROQ_API_KEY and
outbound internet access and is NOT something this module's own test
suite can verify — try it yourself once your .env is configured, by
submitting a scenario on the Generate Dataset page.
"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Optional

from config import Config
from services.generation_service import (
    GenerationConfig,
    LEASE_TYPES,
    MARKET_CONDITIONS,
    OCCUPANCY_STATUSES,
    PAYMENT_FREQUENCIES,
    PROPERTY_TYPES,
    TENANT_INDUSTRIES,
)

logger = logging.getLogger(__name__)

try:
    from groq import Groq, GroqError
    _GROQ_SDK_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised only if groq isn't installed
    _GROQ_SDK_AVAILABLE = False
    GroqError = Exception


class AIServiceError(Exception):
    """Raised whenever the AI service cannot fulfil a request, for any
    reason (not configured, SDK missing, network failure, bad output).
    The message is written to be shown directly to the end user.
    """


def is_ai_enabled() -> bool:
    return bool(Config.AI_ENABLED) and _GROQ_SDK_AVAILABLE


def _get_client() -> "Groq":
    if not _GROQ_SDK_AVAILABLE:
        raise AIServiceError(
            "The 'groq' package is not installed in this environment. Run: pip install groq"
        )
    if not Config.GROQ_API_KEY:
        raise AIServiceError(
            "AI features are disabled: no GROQ_API_KEY is configured. "
            "Add one to your .env file to enable scenario interpretation and AI insights. "
            "Manual (form-based) generation works without it."
        )
    return Groq(api_key=Config.GROQ_API_KEY)


# =====================================================================
# Feature 1: scenario -> structured parameters
# =====================================================================

SCENARIO_SYSTEM_PROMPT = f"""You are a parameter-extraction engine for a commercial real \
estate SYNTHETIC data generator. The user will describe, in plain English, the kind of \
commercial lease dataset they want generated. Convert their description into a single JSON \
object with exactly these keys:

{{
  "property_types": array, subset of {PROPERTY_TYPES},
  "locations": array of exact place names copied from the user's description, or [] if no location is specified,
  "num_records": integer between 1 and 20000,
  "lease_duration_min": integer (years, >= 1),
  "lease_duration_max": integer (years, >= lease_duration_min),
  "tenant_industries": array, subset of {TENANT_INDUSTRIES},
  "lease_types": array, subset of {LEASE_TYPES},
  "occupancy_statuses": array, subset of {OCCUPANCY_STATUSES},
  "payment_frequencies": array, subset of {PAYMENT_FREQUENCIES},
  "market_conditions": array, subset of {MARKET_CONDITIONS},
  "escalation_rate_min": number (percent, 0 to 20) or null,
  "escalation_rate_max": number (percent, 0 to 20) or null,
  "escalation_source": exact quote of the requested escalation terms, or null
}}

Rules:
- Output ONLY the JSON object. No markdown fences, no commentary, no explanation.
- Locations can be anywhere in the world, including a neighborhood, village, city,
  state, province, country, or region. Use the place the user requests even if
  you don't recognize the name. Keep its spelling, script, accents and any
  geographic qualifiers provided with it. Do not translate, expand, or substitute
  a location. For example, use ["Pune, India"] for "in Pune, India", ["भारत"] for
  "in भारत", and ["Europe"] for "in Europe". For "in Lagos and Accra",
  use ["Lagos", "Accra"]. Include only the locations requested for the properties.
- If the user doesn't mention a field, choose a sensible, realistic default for commercial
  real estate and still include the key. Use [] for locations only when the user
  leaves the property location unspecified.
- Honor explicitly requested values from the allowed lists. For a fixed duration,
  use the same value as the minimum and maximum.
- Set both escalation rates and escalation_source to null if the user did not
  specify a rent increase rate, a range, or a rent freeze. The generator will
  apply its default range. Payment frequency is independent of rent escalation.
- Express escalation as percentage points: "3.5% annual escalation" means
  3.5 for both rates. "2% to 4% rent increases" means 2 and 4. Only return
  0 for a bound when the user explicitly requests zero or flat rent.
  Copy the exact phrase about rent escalation into escalation_source.
- Default to 500 records and monthly payments when unspecified.
- Never include any field not listed above.
- This is for SYNTHETIC test data only — never refer to or imply any real company, tenant,
  or property.
"""


def _sanitize_scenario_params(data: dict) -> dict:
    """Clamp/validate whatever the model returned against allowed values
    and sane ranges, filling in defaults for anything missing or invalid.
    This is what stops a malformed or creative model response from ever
    reaching the generation engine unchecked.
    """

    def _subset(key, allowed, default):
        vals = data.get(key)
        if not isinstance(vals, list):
            return list(default)
        cleaned = [v for v in vals if isinstance(v, str) and v in allowed]
        return cleaned or list(default)

    out = {
        "property_types": _subset("property_types", PROPERTY_TYPES, PROPERTY_TYPES),
        "tenant_industries": _subset("tenant_industries", TENANT_INDUSTRIES, TENANT_INDUSTRIES),
        "lease_types": _subset("lease_types", LEASE_TYPES, LEASE_TYPES),
        "occupancy_statuses": _subset("occupancy_statuses", OCCUPANCY_STATUSES, OCCUPANCY_STATUSES),
        "market_conditions": _subset("market_conditions", MARKET_CONDITIONS, MARKET_CONDITIONS),
        "payment_frequencies": _subset("payment_frequencies", PAYMENT_FREQUENCIES, ["Monthly"]),
    }

    locations = data.get("locations")
    if isinstance(locations, list) and locations:
        out["locations"] = list(dict.fromkeys(
            loc.strip() for loc in locations if isinstance(loc, str) and loc.strip()
        ))
    else:
        out["locations"] = []

    try:
        num_records = int(data.get("num_records", 500))
    except (TypeError, ValueError, OverflowError):
        num_records = 500
    out["num_records"] = max(Config.MIN_RECORDS, min(num_records, Config.MAX_RECORDS))

    try:
        dmin = int(data.get("lease_duration_min", 1))
        dmax = int(data.get("lease_duration_max", 10))
    except (TypeError, ValueError, OverflowError):
        dmin, dmax = 1, 10
    dmin = max(1, min(dmin, 50))
    dmax = max(dmin, min(dmax, 50))
    out["lease_duration_min"], out["lease_duration_max"] = dmin, dmax

    try:
        emin = float(data.get("escalation_rate_min", GenerationConfig.escalation_rate_min))
        emax = float(data.get("escalation_rate_max", GenerationConfig.escalation_rate_max))
    except (TypeError, ValueError):
        emin = GenerationConfig.escalation_rate_min
        emax = GenerationConfig.escalation_rate_max
    emin = max(0.0, min(emin, 20.0))
    emax = max(emin, min(emax, 20.0))
    out["escalation_rate_min"], out["escalation_rate_max"] = round(emin, 2), round(emax, 2)

    return out


def interpret_scenario(user_text: str) -> dict:
    """Send a free-text scenario description to Groq and return a
    sanitized dict of generation parameters. Raises AIServiceError on
    any failure (missing key, network error, malformed response after
    retries).
    """
    client = _get_client()
    last_err: Optional[Exception] = None
    scenario = user_text.strip()[:4000]

    for attempt in range(Config.GROQ_MAX_RETRIES + 1):
        try:
            response = client.chat.completions.create(
                model=Config.GROQ_MODEL,
                messages=[
                    {"role": "system", "content": SCENARIO_SYSTEM_PROMPT},
                    {"role": "user", "content": scenario},
                ],
                temperature=0.2,
                max_tokens=1600,
                response_format={"type": "json_object"},
                timeout=Config.GROQ_TIMEOUT_SECONDS,
            )
            raw = response.choices[0].message.content
            data = json.loads(raw or "")
            if not isinstance(data, dict):
                raise ValueError("Expected a JSON object with generation settings.")
            if not isinstance(data.get("locations"), list):
                raise ValueError("Expected a list of property locations.")
            escalation_source = data.get("escalation_source")
            if not isinstance(escalation_source, str) or not escalation_source.strip() or (
                escalation_source.strip().casefold() not in scenario.casefold()
            ):
                data.pop("escalation_rate_min", None)
                data.pop("escalation_rate_max", None)
            params = _sanitize_scenario_params(data)
            locations = []
            for location in params["locations"]:
                match = re.search(rf"(?<!\w){re.escape(location)}(?!\w)", scenario, re.IGNORECASE)
                if match is None:
                    raise ValueError("A property location did not match the scenario. Try spelling out the place name.")
                locations.append(match.group())
            params["locations"] = list(dict.fromkeys(locations))
            return params
        except ValueError as e:
            last_err = e
            logger.warning("Groq returned invalid scenario data (attempt %s/%s): %s",
                            attempt + 1, Config.GROQ_MAX_RETRIES + 1, e)
        except GroqError as e:
            last_err = e
            logger.warning("Groq API call failed (attempt %s/%s): %s",
                            attempt + 1, Config.GROQ_MAX_RETRIES + 1, e)
        if attempt < Config.GROQ_MAX_RETRIES:
            time.sleep(min(2 ** attempt, 5))

    raise AIServiceError(
        f"Could not interpret the scenario after {Config.GROQ_MAX_RETRIES + 1} attempt(s): {last_err}. "
        "You can still fill in the generation form manually."
    )


# =====================================================================
# Feature 6: dataset insights (grounded in real, pre-computed stats)
# =====================================================================

INSIGHTS_SYSTEM_PROMPT = """You are a data analyst assistant for LeaseSynth AI. You will be \
given pre-computed statistics (KPIs and chart aggregates) from a pandas dataframe of SYNTHETIC \
commercial lease records, plus a question about that dataset.

Rules:
- Answer using ONLY the numbers in the statistics you were given.
- NEVER invent, estimate, or guess a numeric value that is not present in the provided
  statistics. If the statistics don't contain what's needed to answer precisely, say so
  explicitly rather than approximating.
- Remind the reader, briefly, that this is synthetic data if your answer could otherwise be
  mistaken for a real-market claim.
- Keep the answer under 150 words, in plain, direct language.
"""


def generate_insight(question: str, stats_summary: dict) -> str:
    client = _get_client()
    payload = json.dumps(stats_summary, default=str)
    last_err: Optional[Exception] = None

    for attempt in range(Config.GROQ_MAX_RETRIES + 1):
        try:
            response = client.chat.completions.create(
                model=Config.GROQ_MODEL,
                messages=[
                    {"role": "system", "content": INSIGHTS_SYSTEM_PROMPT},
                    {"role": "user", "content": f"STATISTICS (JSON):\n{payload}\n\nQUESTION: {question.strip()[:1000]}"},
                ],
                temperature=0.3,
                max_tokens=400,
                timeout=Config.GROQ_TIMEOUT_SECONDS,
            )
            return response.choices[0].message.content.strip()
        except GroqError as e:
            last_err = e
            logger.warning("Groq insight call failed (attempt %s/%s): %s",
                            attempt + 1, Config.GROQ_MAX_RETRIES + 1, e)
            if attempt < Config.GROQ_MAX_RETRIES:
                time.sleep(min(2 ** attempt, 5))

    raise AIServiceError(
        f"Could not generate an AI insight after {Config.GROQ_MAX_RETRIES + 1} attempt(s): {last_err}"
    )
