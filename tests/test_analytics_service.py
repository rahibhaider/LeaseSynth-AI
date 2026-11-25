import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from services.generation_service import GenerationConfig, generate_lease_dataset
from services.analytics_service import compute_kpis, compute_chart_data


def _df(n=500, seed=1):
    cfg = GenerationConfig.from_dict({"num_records": n, "seed": seed})
    return generate_lease_dataset(cfg)


def test_kpis_match_manual_pandas_calculation():
    df = _df(800, seed=2)
    kpis = compute_kpis(df)
    assert kpis["total_leases"] == len(df)
    assert kpis["total_properties"] == df["property_id"].nunique()
    assert kpis["avg_monthly_rent"] == round(float(df["monthly_rent"].mean()), 2)
    assert kpis["active_leases"] == int((df["lease_status"] == "Active").sum())
    assert kpis["expired_leases"] == int((df["lease_status"] == "Expired").sum())


def test_all_charts_present_with_matching_lengths():
    df = _df(600, seed=3)
    charts = compute_chart_data(df)
    expected_keys = {
        "lease_by_property_type",
        "avg_rent_by_property_type",
        "tenant_industry_distribution",
        "lease_commencement_trend",
        "lease_duration_distribution",
        "occupancy_status_distribution",
        "payment_frequency_distribution",
        "rent_by_location",
        "monthly_rent_histogram",
    }
    assert set(charts.keys()) == expected_keys
    for name, chart in charts.items():
        assert len(chart["labels"]) == len(chart["values"]), f"{name} labels/values length mismatch"
        assert len(chart["labels"]) > 0, f"{name} is empty"


def test_pie_chart_totals_match_record_count():
    df = _df(400, seed=4)
    charts = compute_chart_data(df)
    total = sum(charts["lease_by_property_type"]["values"])
    assert total == len(df)


def test_single_rent_value_uses_one_histogram_bar():
    chart = compute_chart_data(_df(1))["monthly_rent_histogram"]
    assert len(chart["labels"]) == 1
    assert chart["values"] == [1]


def test_empty_dataframe_handled_gracefully():
    import pandas as pd

    kpis = compute_kpis(pd.DataFrame())
    assert kpis["total_leases"] == 0
    charts = compute_chart_data(pd.DataFrame())
    assert all(c["labels"] == [] for c in charts.values())
