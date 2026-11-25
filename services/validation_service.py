"""
validation_service.py — Automatic data-quality validation for a generated
(or externally supplied) lease dataset.

Every check below mirrors a business rule from the generation engine, so
a freshly generated dataset should score ~100%. The checks are written
against the DataFrame, not against the generator, which is what lets this
module also catch *deliberately corrupted* data (see tests/test_validation_service.py)
rather than just rubber-stamping whatever generation_service produces.

Nothing here silently "fixes" bad data — it only reports what it finds.
"""

from __future__ import annotations

from datetime import date
from typing import Optional

import numpy as np
import pandas as pd

REQUIRED_COLUMNS = [
    "lease_id",
    "property_id",
    "tenant_id",
    "property_type",
    "property_location",
    "tenant_industry",
    "property_size_sqft",
    "lease_start_date",
    "lease_end_date",
    "lease_duration_years",
    "monthly_rent",
    "annual_rent",
    "rent_per_sqft",
    "security_deposit",
    "lease_type",
    "escalation_rate",
    "occupancy_status",
    "renewal_option",
    "maintenance_responsibility",
    "market_condition",
    "lease_status",
]

# Tolerances account for floating-point rounding, not business error.
CURRENCY_TOLERANCE = 0.05       # dollars
DURATION_TOLERANCE_YEARS = 0.15  # ~ 55 days, absorbs leap-year rounding
MIN_PROPERTY_SIZE = 100
MAX_PROPERTY_SIZE = 2_000_000
MAX_ESCALATION_RATE = 20.0

MAX_ERROR_ROWS_RETURNED = 500  # cap the detailed error list for huge datasets


def validate_dataset(df: pd.DataFrame, as_of: Optional[date] = None) -> dict:
    """Run every validation rule against `df` and return a report dict.

    The report always has the same shape, so the frontend / export code
    doesn't need to special-case an empty or tiny dataset.
    """
    as_of = as_of or date.today()
    n = len(df)

    if n == 0:
        return {
            "total_records": 0,
            "valid_records": 0,
            "invalid_records": 0,
            "duplicate_records": 0,
            "missing_value_cells": 0,
            "rows_with_missing_values": 0,
            "data_quality_percentage": 0.0,
            "checks": {},
            "errors": [],
            "truncated": False,
        }

    missing_cols = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    present_cols = [c for c in REQUIRED_COLUMNS if c in df.columns]

    # ---- Missing values -------------------------------------------------
    sub = df[present_cols]
    is_null = sub.isna()
    is_blank_string = sub.astype(str).apply(lambda col: col.str.strip() == "")
    missing_mask = (is_null | is_blank_string)
    if missing_cols:
        # Columns that don't even exist count as "missing" for every row.
        always_missing = pd.DataFrame(
            {c: True for c in missing_cols}, index=df.index
        )
        missing_mask = pd.concat([missing_mask, always_missing], axis=1)
    rows_with_missing = missing_mask.any(axis=1)
    missing_cell_count = int(missing_mask.sum().sum())

    # ---- Duplicate lease IDs --------------------------------------------
    if "lease_id" in df.columns:
        dup_any = df["lease_id"].duplicated(keep=False)
        dup_extra = df["lease_id"].duplicated(keep="first")
    else:
        dup_any = pd.Series(False, index=df.index)
        dup_extra = pd.Series(False, index=df.index)
    duplicate_records_count = int(dup_extra.sum())

    # ---- Dates ------------------------------------------------------------
    start = pd.to_datetime(df.get("lease_start_date"), errors="coerce")
    end = pd.to_datetime(df.get("lease_end_date"), errors="coerce")
    invalid_date_mask = start.isna() | end.isna() | (end <= start)

    # ---- Lease duration vs. dates ----------------------------------------
    computed_years = (end - start).dt.days / 365.25
    duration_col = pd.to_numeric(df.get("lease_duration_years"), errors="coerce")
    duration_mismatch_mask = (
        (computed_years - duration_col).abs() > DURATION_TOLERANCE_YEARS
    ) | duration_col.isna()
    duration_mismatch_mask = duration_mismatch_mask & ~invalid_date_mask.fillna(True)

    # ---- Negative monetary values ----------------------------------------
    monthly_rent = pd.to_numeric(df.get("monthly_rent"), errors="coerce")
    annual_rent = pd.to_numeric(df.get("annual_rent"), errors="coerce")
    security_deposit = pd.to_numeric(df.get("security_deposit"), errors="coerce")
    negative_mask = (
        (monthly_rent < 0) | (annual_rent < 0) | (security_deposit < 0)
        | monthly_rent.isna() | annual_rent.isna() | security_deposit.isna()
    )

    # ---- annual_rent == monthly_rent * 12 ---------------------------------
    annual_calc_mismatch = (annual_rent - monthly_rent * 12).abs() > CURRENCY_TOLERANCE

    # ---- Property size -----------------------------------------------------
    size = pd.to_numeric(df.get("property_size_sqft"), errors="coerce")
    size_invalid = (
        size.isna() | (size <= 0) | (size < MIN_PROPERTY_SIZE) | (size > MAX_PROPERTY_SIZE)
    )

    # ---- rent_per_sqft == annual_rent / size -------------------------------
    safe_size = size.replace(0, np.nan)
    expected_rsf = annual_rent / safe_size
    rsf = pd.to_numeric(df.get("rent_per_sqft"), errors="coerce")
    rsf_mismatch = (expected_rsf - rsf).abs() > CURRENCY_TOLERANCE
    rsf_mismatch = rsf_mismatch.fillna(True) & ~size_invalid

    # ---- Escalation rate -----------------------------------------------------
    escalation = pd.to_numeric(df.get("escalation_rate"), errors="coerce")
    escalation_invalid = escalation.isna() | (escalation < 0) | (escalation > MAX_ESCALATION_RATE)

    # ---- Lease status consistency with dates -------------------------------
    computed_status = np.where(
        start.dt.date > as_of,
        "Pending",
        np.where(end.dt.date < as_of, "Expired", "Active"),
    )
    actual_status = df.get("lease_status", pd.Series(index=df.index, dtype=object)).astype(str)
    status_mismatch = pd.Series(computed_status, index=df.index).astype(str) != actual_status
    status_mismatch = status_mismatch & ~invalid_date_mask.fillna(True)

    row_invalid = (
        rows_with_missing.values
        | dup_any.values
        | invalid_date_mask.fillna(True).values
        | duration_mismatch_mask.fillna(True).values
        | negative_mask.values
        | annual_calc_mismatch.fillna(True).values
        | size_invalid.values
        | rsf_mismatch.values
        | escalation_invalid.values
        | status_mismatch.values
    )

    valid_records = int((~row_invalid).sum())
    invalid_records = int(row_invalid.sum())
    quality_pct = round(valid_records / n * 100, 2) if n else 0.0

    # ---- Build a detailed error list for invalid rows ----------------------
    errors = []
    invalid_idx = np.where(row_invalid)[0]
    lease_ids = df["lease_id"].values if "lease_id" in df.columns else [None] * n
    for idx in invalid_idx[:MAX_ERROR_ROWS_RETURNED]:
        reasons = []
        if rows_with_missing.iloc[idx]:
            reasons.append("missing_required_value")
        if dup_any.iloc[idx]:
            reasons.append("duplicate_lease_id")
        if bool(invalid_date_mask.iloc[idx]) if not pd.isna(invalid_date_mask.iloc[idx]) else True:
            reasons.append("invalid_dates")
        if bool(duration_mismatch_mask.iloc[idx]):
            reasons.append("lease_duration_mismatch")
        if bool(negative_mask.iloc[idx]):
            reasons.append("negative_rental_value")
        if bool(annual_calc_mismatch.iloc[idx]) if not pd.isna(annual_calc_mismatch.iloc[idx]) else False:
            reasons.append("annual_rent_calculation_error")
        if bool(size_invalid.iloc[idx]):
            reasons.append("invalid_property_size")
        if bool(rsf_mismatch.iloc[idx]):
            reasons.append("rent_per_sqft_calculation_error")
        if bool(escalation_invalid.iloc[idx]):
            reasons.append("invalid_escalation_rate")
        if bool(status_mismatch.iloc[idx]):
            reasons.append("lease_status_inconsistent")

        errors.append(
            {
                "row_index": int(idx),
                "lease_id": str(lease_ids[idx]) if lease_ids[idx] is not None else None,
                "errors": reasons or ["unspecified"],
            }
        )

    report = {
        "total_records": n,
        "valid_records": valid_records,
        "invalid_records": invalid_records,
        "duplicate_records": duplicate_records_count,
        "missing_value_cells": missing_cell_count,
        "rows_with_missing_values": int(rows_with_missing.sum()),
        "data_quality_percentage": quality_pct,
        "checks": {
            "invalid_dates": int(invalid_date_mask.fillna(True).sum()),
            "duration_mismatches": int(duration_mismatch_mask.fillna(True).sum()),
            "negative_or_missing_monetary_values": int(negative_mask.sum()),
            "annual_rent_mismatches": int(annual_calc_mismatch.fillna(True).sum()),
            "invalid_property_sizes": int(size_invalid.sum()),
            "rent_per_sqft_mismatches": int(rsf_mismatch.sum()),
            "invalid_escalation_rates": int(escalation_invalid.sum()),
            "status_inconsistencies": int(status_mismatch.sum()),
        },
        "errors": errors,
        "truncated": len(invalid_idx) > MAX_ERROR_ROWS_RETURNED,
    }
    return report
