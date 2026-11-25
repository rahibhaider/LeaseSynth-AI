import sys
import os
from datetime import date

import pandas as pd

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from services.generation_service import (
    GenerationConfig,
    generate_lease_dataset,
    OUTPUT_COLUMNS,
)


def test_default_config_generates_requested_count():
    cfg = GenerationConfig.from_dict({"num_records": 250, "seed": 1})
    df = generate_lease_dataset(cfg)
    assert len(df) == 250


def test_output_columns_match_spec():
    cfg = GenerationConfig.from_dict({"num_records": 20, "seed": 1})
    df = generate_lease_dataset(cfg)
    assert list(df.columns) == OUTPUT_COLUMNS


def test_lease_ids_are_unique():
    cfg = GenerationConfig.from_dict({"num_records": 2000, "seed": 2})
    df = generate_lease_dataset(cfg)
    assert df["lease_id"].is_unique


def test_tenant_ids_are_unique():
    cfg = GenerationConfig.from_dict({"num_records": 2000, "seed": 2})
    df = generate_lease_dataset(cfg)
    assert df["tenant_id"].is_unique


def test_end_date_always_after_start_date():
    cfg = GenerationConfig.from_dict({"num_records": 1000, "seed": 3})
    df = generate_lease_dataset(cfg)
    start = pd.to_datetime(df["lease_start_date"])
    end = pd.to_datetime(df["lease_end_date"])
    assert (end > start).all()


def test_annual_rent_equals_monthly_times_twelve():
    cfg = GenerationConfig.from_dict({"num_records": 1000, "seed": 4})
    df = generate_lease_dataset(cfg)
    diff = (df["annual_rent"] - df["monthly_rent"] * 12).abs()
    assert (diff < 0.01).all()


def test_rent_per_sqft_consistent_with_annual_rent_and_size():
    cfg = GenerationConfig.from_dict({"num_records": 1000, "seed": 5})
    df = generate_lease_dataset(cfg)
    expected = df["annual_rent"] / df["property_size_sqft"]
    diff = (df["rent_per_sqft"] - expected).abs()
    assert (diff < 0.02).all()


def test_lease_duration_matches_dates():
    cfg = GenerationConfig.from_dict({"num_records": 1000, "seed": 6})
    df = generate_lease_dataset(cfg)
    start = pd.to_datetime(df["lease_start_date"])
    end = pd.to_datetime(df["lease_end_date"])
    computed_years = (end - start).dt.days / 365.25
    diff = (computed_years - df["lease_duration_years"]).abs()
    assert (diff < 0.15).all()


def test_lease_type_determines_maintenance_responsibility():
    cfg = GenerationConfig.from_dict({"num_records": 1000, "seed": 7})
    df = generate_lease_dataset(cfg)
    mapping = {"Gross": "Landlord", "Modified Gross": "Shared", "NNN": "Tenant"}
    for lease_type, maintenance in mapping.items():
        subset = df[df["lease_type"] == lease_type]
        if len(subset) > 0:
            assert (subset["maintenance_responsibility"] == maintenance).all()


def test_occupancy_status_implies_consistent_lease_status():
    cfg = GenerationConfig.from_dict({"num_records": 2000, "seed": 8})
    df = generate_lease_dataset(cfg, as_of=date(2026, 11, 15))
    mapping = {"Pending": "Pending", "Occupied": "Active", "Vacant": "Expired"}
    for occ, status in mapping.items():
        subset = df[df["occupancy_status"] == occ]
        if len(subset) > 0:
            assert (subset["lease_status"] == status).all()


def test_all_rows_tagged_synthetic():
    cfg = GenerationConfig.from_dict({"num_records": 50, "seed": 9})
    df = generate_lease_dataset(cfg)
    assert (df["is_synthetic"] == True).all()  # noqa: E712


def test_no_negative_rents_or_sizes():
    cfg = GenerationConfig.from_dict({"num_records": 2000, "seed": 10})
    df = generate_lease_dataset(cfg)
    assert (df["monthly_rent"] >= 0).all()
    assert (df["annual_rent"] >= 0).all()
    assert (df["security_deposit"] >= 0).all()
    assert (df["property_size_sqft"] > 0).all()


def test_restricting_property_types_is_honored():
    cfg = GenerationConfig.from_dict({"num_records": 200, "property_types": ["Industrial"], "seed": 11})
    df = generate_lease_dataset(cfg)
    assert (df["property_type"] == "Industrial").all()


def test_small_dataset_covers_every_requested_location():
    locations = ["São Paulo, Brazil", "東京", "Ballydehob", "Europe"]
    cfg = GenerationConfig.from_dict({"num_records": 4, "locations": locations, "seed": 11})
    df = generate_lease_dataset(cfg)
    assert set(df["property_location"]) == set(locations)


def test_restricting_lease_types_is_honored():
    cfg = GenerationConfig.from_dict({"num_records": 200, "lease_types": ["NNN"], "seed": 12})
    df = generate_lease_dataset(cfg)
    assert (df["lease_type"] == "NNN").all()
    assert (df["maintenance_responsibility"] == "Tenant").all()


def test_invalid_num_records_raises():
    import pytest

    with pytest.raises(ValueError):
        GenerationConfig.from_dict({"num_records": -10})
    with pytest.raises(ValueError):
        GenerationConfig.from_dict({"num_records": 10 ** 9})


def test_invalid_duration_range_raises():
    import pytest

    with pytest.raises(ValueError):
        GenerationConfig.from_dict({"num_records": 10, "lease_duration_min": 10, "lease_duration_max": 2})


def test_seed_is_reproducible():
    cfg1 = GenerationConfig.from_dict({"num_records": 100, "seed": 123})
    cfg2 = GenerationConfig.from_dict({"num_records": 100, "seed": 123})
    df1 = generate_lease_dataset(cfg1, as_of=date(2026, 11, 15))
    df2 = generate_lease_dataset(cfg2, as_of=date(2026, 11, 15))
    pd.testing.assert_frame_equal(df1, df2)


def test_performance_5000_records_under_5_seconds():
    import time

    cfg = GenerationConfig.from_dict({"num_records": 5000, "seed": 13})
    t0 = time.time()
    df = generate_lease_dataset(cfg)
    elapsed = time.time() - t0
    assert len(df) == 5000
    assert elapsed < 5.0
