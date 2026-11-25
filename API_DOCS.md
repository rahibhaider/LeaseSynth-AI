# LeaseSynth AI — API Reference

Base URL (local dev): `http://127.0.0.1:5000`

All `/api/*` endpoints return JSON. All page routes (`/`, `/dashboard`,
`/generate`, `/dataset`, `/validation`, `/insights`) return HTML and
aren't listed again below.

Every dataset-dependent endpoint (`/api/dataset`, `/api/validation`,
`/api/analytics`, `/api/insights`, `/api/export/*`) returns **400** with
`{"error": "..."}` until `POST /api/generate` or
`POST /api/generate-from-scenario` succeeds in the current server session.

---

## `POST /api/interpret-scenario`

Converts a free-text scenario description into structured generation
parameters using Groq. Requires `GROQ_API_KEY` to be configured.

**Request body**
```json
{ "scenario_description": "Office leases in Pune, India, with terms of 3-10 years in a high-demand market" }
```

**Success — 200**
```json
{
  "ai_enabled": true,
  "parameters": {
    "property_types": ["Office"],
    "locations": ["Pune, India"],
    "num_records": 500,
    "lease_duration_min": 3,
    "lease_duration_max": 10,
    "tenant_industries": ["Technology", "Finance", "..."],
    "lease_types": ["Gross", "Modified Gross", "NNN"],
    "occupancy_statuses": ["Occupied", "Vacant", "Pending"],
    "payment_frequencies": ["Monthly"],
    "market_conditions": ["High Demand"],
    "escalation_rate_min": 2.0,
    "escalation_rate_max": 4.0
  }
}
```

**Errors**
- `400` — `scenario_description` missing/empty.
- `503` — AI disabled (no `GROQ_API_KEY` configured).
- `502` — Groq call failed after retries (network error, timeout, or
  persistently malformed output).

---

## `POST /api/generate`

Generates a new synthetic lease dataset, replacing the "current" one for
the session. Every field is optional; omitted fields fall back to
sensible defaults (see `GenerationConfig` in `services/generation_service.py`).

**Request body**
```json
{
  "num_records": 1000,
  "property_types": ["Office", "Retail"],
  "locations": ["New York, NY", "Austin, TX"],
  "tenant_industries": ["Technology", "Finance"],
  "lease_types": ["Gross", "NNN"],
  "occupancy_statuses": ["Occupied", "Vacant", "Pending"],
  "market_conditions": ["High Demand", "Stable"],
  "payment_frequencies": ["Monthly", "Annual"],
  "lease_duration_min": 3,
  "lease_duration_max": 10,
  "escalation_rate_min": 2.0,
  "escalation_rate_max": 4.0,
  "scenario_description": "optional free text, stored as metadata",
  "seed": 42
}
```

| Field | Type | Constraint |
|---|---|---|
| `num_records` | int | `1` – `20000` (configurable via `MIN_RECORDS`/`MAX_RECORDS` in `.env`) |
| `*_types` / `*_industries` / `*_statuses` / `*_conditions` / `*_frequencies` | string[] | Values outside the allowed set are dropped; an empty/omitted list defaults to "all" |
| `locations` | string[] | Any string accepted; unrecognized locations get a neutral rent multiplier |
| `lease_duration_min/max` | int | `1 <= min <= max <= 50` |
| `escalation_rate_min/max` | float | `0 <= min <= max <= 20` |
| `seed` | int (optional) | Makes the run reproducible |

**Success — 201**
```json
{
  "message": "Generated 1000 synthetic lease records.",
  "record_count": 1000,
  "generated_at": "2026-11-15T16:30:00",
  "data_quality_percentage": 100.0,
  "preview": [ { "...first 10 records as objects...": "" } ]
}
```

**Errors**
- `400` — invalid configuration (out-of-range values, bad types); body
  includes a specific `error` message.
- `500` — unexpected generation failure (check server logs).

---

## `POST /api/generate-from-scenario`

Accepts the same `scenario_description` body as `POST /api/interpret-scenario`.
Groq extracts the settings and the generator creates the dataset in the same
request. The dataset uses the places named in the description. When you request
multiple locations, specify at least one record per location. If the scenario
omits the location, the generator uses its default location list. If it omits
rent escalation, the generator uses annual rates from 2% to 4%. A scenario
can request a fixed rate, a range, or flat rent with 0% escalation. Returns the
same **201** response as `POST /api/generate`, or a **400**, **502**, or
**503** response if the scenario cannot be used for generation.

---

## `GET /api/dataset`

Paginated, searchable, filterable view of the current dataset.

**Query parameters** (all optional)

| Param | Default | Notes |
|---|---|---|
| `search` | — | Matches against the stringified row (case-insensitive substring) |
| `property_type` | — | Exact match |
| `location` | — | Exact match |
| `lease_status` | — | Exact match (`Active` / `Expired` / `Pending`) |
| `page` | `1` | |
| `page_size` | `25` | Max `200` |

**Response — 200**
```json
{
  "total_records": 1000,
  "page": 1,
  "page_size": 25,
  "total_pages": 40,
  "records": [ { "...": "" } ],
  "filter_options": {
    "property_types": ["Industrial", "Mixed-Use", "..."],
    "locations": ["Austin, TX", "..."],
    "lease_statuses": ["Active", "Expired", "Pending"]
  }
}
```

---

## `GET /api/validation`

Returns the full validation report for the current dataset (see
`services/validation_service.py` for the exact rules).

**Response — 200**
```json
{
  "total_records": 1000,
  "valid_records": 1000,
  "invalid_records": 0,
  "duplicate_records": 0,
  "missing_value_cells": 0,
  "rows_with_missing_values": 0,
  "data_quality_percentage": 100.0,
  "checks": {
    "invalid_dates": 0,
    "duration_mismatches": 0,
    "negative_or_missing_monetary_values": 0,
    "annual_rent_mismatches": 0,
    "invalid_property_sizes": 0,
    "rent_per_sqft_mismatches": 0,
    "invalid_escalation_rates": 0,
    "status_inconsistencies": 0
  },
  "errors": [],
  "truncated": false
}
```
`errors` lists up to 500 invalid rows as
`{"row_index": 0, "lease_id": "LS-000001", "errors": ["invalid_dates"]}`;
`truncated: true` means more than 500 were found.

---

## `GET /api/analytics`

**Response — 200**
```json
{
  "kpis": {
    "total_leases": 1000, "total_properties": 480,
    "avg_monthly_rent": 145230.12, "avg_annual_rent": 1742761.44,
    "avg_lease_duration_years": 5.4, "avg_rent_per_sqft": 28.6,
    "active_leases": 340, "expired_leases": 330, "pending_leases": 330
  },
  "charts": {
    "lease_by_property_type": { "labels": ["Office", "..."], "values": [320, "..."] },
    "avg_rent_by_property_type": { "labels": ["..."], "values": ["..."] },
    "tenant_industry_distribution": { "labels": ["..."], "values": ["..."] },
    "lease_commencement_trend": { "labels": ["2024Q1", "..."], "values": ["..."] },
    "lease_duration_distribution": { "labels": ["1-2 yrs", "..."], "values": ["..."] },
    "occupancy_status_distribution": { "labels": ["..."], "values": ["..."] },
    "payment_frequency_distribution": { "labels": ["Monthly", "Annual"], "values": [700, 300] },
    "rent_by_location": { "labels": ["..."], "values": ["..."] },
    "monthly_rent_histogram": { "labels": ["$0-$1000", "..."], "values": ["..."] }
  }
}
```

---

## `POST /api/insights`

**Request body**
```json
{ "question": "Which property type has the highest average rent?" }
```

**Success — 200**
```json
{
  "question": "Which property type has the highest average rent?",
  "answer": "Based on the dataset's computed averages, ...",
  "ai_enabled": true
}
```

**Errors**: `400` (no question / no dataset), `503` (AI disabled),
`502` (Groq call failed after retries).

---

## `GET /api/export/csv`
## `GET /api/export/json`
## `GET /api/export/validation-csv`
## `GET /api/export/summary`

Each streams a file download (`Content-Disposition: attachment`) built
from the live dataset/validation report — never cached or hardcoded
data:

| Endpoint | Filename pattern | Content |
|---|---|---|
| `/api/export/csv` | `LeaseSynth_Dataset_<year>.csv` | Full dataset, one row per lease |
| `/api/export/json` | `LeaseSynth_Dataset_<year>.json` | `{"metadata": {...}, "records": [...]}` |
| `/api/export/validation-csv` | `LeaseSynth_ValidationReport_<year>.csv` | Summary + per-check counts + per-row errors |
| `/api/export/summary` | `LeaseSynth_Summary_<year>.txt` | Human-readable KPI + quality summary |

---

## `GET /api/history`

Returns up to the 10 most recent generation runs (metadata only — see
`services/history_service.py`), newest first.

```json
[
  { "id": 3, "created_at": "2026-11-15T16:30:00", "record_count": 1000, "quality_score": 100.0, "config": { "...": "" } }
]
```

---

## `GET /api/status`

Lightweight status check polled by the frontend's AI indicator.

```json
{
  "ai_enabled": true,
  "groq_model": "llama-3.3-70b-versatile",
  "has_dataset": true,
  "record_count": 1000,
  "generated_at": "2026-11-15T16:30:00"
}
```
