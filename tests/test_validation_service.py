import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from services.generation_service import GenerationConfig, generate_lease_dataset
from services.validation_service import validate_dataset


def _clean_df(n=500, seed=1):
    cfg = GenerationConfig.from_dict({"num_records": n, "seed": seed})
    return generate_lease_dataset(cfg)


def test_clean_dataset_scores_100_percent():
    df = _clean_df()
    report = validate_dataset(df)
    assert report["data_quality_percentage"] == 100.0
    assert report["invalid_records"] == 0
    assert report["duplicate_records"] == 0


def test_detects_duplicate_lease_ids():
    df = _clean_df().copy()
    df.loc[1, "lease_id"] = df.loc[0, "lease_id"]
    report = validate_dataset(df)
    assert report["duplicate_records"] == 1
    assert report["invalid_records"] >= 2


def test_detects_invalid_dates():
    df = _clean_df().copy()
    df.loc[0, "lease_end_date"] = df.loc[0, "lease_start_date"]
    report = validate_dataset(df)
    assert report["checks"]["invalid_dates"] >= 1


def test_detects_negative_rent():
    df = _clean_df().copy()
    df.loc[0, "monthly_rent"] = -100.0
    report = validate_dataset(df)
    assert report["checks"]["negative_or_missing_monetary_values"] >= 1


def test_detects_annual_rent_mismatch():
    df = _clean_df().copy()
    df.loc[0, "annual_rent"] = df.loc[0, "annual_rent"] + 5000
    report = validate_dataset(df)
    assert report["checks"]["annual_rent_mismatches"] >= 1


def test_detects_invalid_property_size():
    df = _clean_df().copy()
    df.loc[0, "property_size_sqft"] = -50
    report = validate_dataset(df)
    assert report["checks"]["invalid_property_sizes"] >= 1


def test_detects_rent_per_sqft_mismatch():
    df = _clean_df().copy()
    df.loc[0, "rent_per_sqft"] = 999999.0
    report = validate_dataset(df)
    assert report["checks"]["rent_per_sqft_mismatches"] >= 1


def test_detects_invalid_escalation_rate():
    df = _clean_df().copy()
    df.loc[0, "escalation_rate"] = 500.0
    report = validate_dataset(df)
    assert report["checks"]["invalid_escalation_rates"] >= 1


def test_detects_duration_mismatch():
    df = _clean_df().copy()
    df.loc[0, "lease_duration_years"] = df.loc[0, "lease_duration_years"] + 30
    report = validate_dataset(df)
    assert report["checks"]["duration_mismatches"] >= 1


def test_detects_missing_values():
    df = _clean_df().copy()
    df.loc[0, "tenant_industry"] = None
    report = validate_dataset(df)
    assert report["rows_with_missing_values"] >= 1
    assert report["missing_value_cells"] >= 1


def test_detects_status_inconsistency():
    df = _clean_df().copy()
    # Force a clearly-active window but mislabel it as Expired.
    df.loc[0, "lease_start_date"] = "2026-01-01"
    df.loc[0, "lease_end_date"] = "2030-01-01"
    df.loc[0, "lease_duration_years"] = 4
    df.loc[0, "lease_status"] = "Expired"
    report = validate_dataset(df)
    assert report["checks"]["status_inconsistencies"] >= 1


def test_empty_dataframe_handled_gracefully():
    import pandas as pd

    report = validate_dataset(pd.DataFrame())
    assert report["total_records"] == 0
    assert report["data_quality_percentage"] == 0.0


def test_does_not_modify_input_dataframe():
    df = _clean_df()
    original = df.copy(deep=True)
    validate_dataset(df)
    import pandas as pd

    pd.testing.assert_frame_equal(df, original)
