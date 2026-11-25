"""
analytics_service.py — Computes KPIs and chart-ready data from an actual
generated dataset using pandas. Nothing here is hardcoded: every number
is derived from the DataFrame passed in, which is what lets ai_service
hand real statistics to Groq instead of letting the model invent any.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def compute_kpis(df: pd.DataFrame) -> dict:
    if df.empty:
        return {
            "total_leases": 0,
            "total_properties": 0,
            "avg_monthly_rent": 0,
            "avg_annual_rent": 0,
            "avg_lease_duration_years": 0,
            "avg_rent_per_sqft": 0,
            "active_leases": 0,
            "expired_leases": 0,
            "pending_leases": 0,
        }
    return {
        "total_leases": int(len(df)),
        "total_properties": int(df["property_id"].nunique()),
        "avg_monthly_rent": round(float(df["monthly_rent"].mean()), 2),
        "avg_annual_rent": round(float(df["annual_rent"].mean()), 2),
        "avg_lease_duration_years": round(float(df["lease_duration_years"].mean()), 2),
        "avg_rent_per_sqft": round(float(df["rent_per_sqft"].mean()), 2),
        "active_leases": int((df["lease_status"] == "Active").sum()),
        "expired_leases": int((df["lease_status"] == "Expired").sum()),
        "pending_leases": int((df["lease_status"] == "Pending").sum()),
    }


def _value_counts_chart(df: pd.DataFrame, column: str) -> dict:
    counts = df[column].value_counts()
    return {"labels": counts.index.tolist(), "values": [int(v) for v in counts.values]}


def _group_mean_chart(df: pd.DataFrame, group_col: str, value_col: str, top_n: int = None) -> dict:
    grouped = df.groupby(group_col)[value_col].mean().round(2).sort_values(ascending=False)
    if top_n:
        grouped = grouped.head(top_n)
    return {"labels": grouped.index.tolist(), "values": [float(v) for v in grouped.values]}


def _commencement_trend(df: pd.DataFrame) -> dict:
    """Lease commencements over time, bucketed by quarter so the trend
    stays legible even when long lease durations push the date range
    back many years.
    """
    starts = pd.to_datetime(df["lease_start_date"], errors="coerce").dropna()
    if starts.empty:
        return {"labels": [], "values": []}
    quarterly = starts.dt.to_period("Q").value_counts()
    quarters = pd.period_range(quarterly.index.min(), quarterly.index.max(), freq="Q")
    quarterly = quarterly.reindex(quarters, fill_value=0)
    return {
        "labels": [str(p) for p in quarterly.index],
        "values": [int(v) for v in quarterly.values],
    }


def _duration_buckets(df: pd.DataFrame) -> dict:
    bins = [0, 2, 5, 10, 999]
    labels = ["1-2 yrs", "3-5 yrs", "6-10 yrs", "11+ yrs"]
    bucketed = pd.cut(df["lease_duration_years"], bins=bins, labels=labels, right=True)
    counts = bucketed.value_counts().reindex(labels, fill_value=0)
    return {"labels": labels, "values": [int(v) for v in counts.values]}


def _histogram(df: pd.DataFrame, column: str, bins: int = 10) -> dict:
    values = df[column].dropna().to_numpy()
    if len(values) == 0:
        return {"labels": [], "values": []}
    if values.min() == values.max():
        return {"labels": [f"${values[0]:,.2f}"], "values": [len(values)]}
    counts, edges = np.histogram(values, bins=bins)
    labels = [f"${lower:,.2f}–${upper:,.2f}" for lower, upper in zip(edges, edges[1:])]
    return {"labels": labels, "values": [int(c) for c in counts]}


def compute_chart_data(df: pd.DataFrame) -> dict:
    if df.empty:
        empty = {"labels": [], "values": []}
        return {
            "lease_by_property_type": empty,
            "avg_rent_by_property_type": empty,
            "tenant_industry_distribution": empty,
            "lease_commencement_trend": empty,
            "lease_duration_distribution": empty,
            "occupancy_status_distribution": empty,
            "payment_frequency_distribution": empty,
            "rent_by_location": empty,
            "monthly_rent_histogram": empty,
        }
    return {
        "lease_by_property_type": _value_counts_chart(df, "property_type"),
        "avg_rent_by_property_type": _group_mean_chart(df, "property_type", "monthly_rent"),
        "tenant_industry_distribution": _value_counts_chart(df, "tenant_industry"),
        "lease_commencement_trend": _commencement_trend(df),
        "lease_duration_distribution": _duration_buckets(df),
        "occupancy_status_distribution": _value_counts_chart(df, "occupancy_status"),
        "payment_frequency_distribution": _value_counts_chart(df, "payment_frequency"),
        "rent_by_location": _group_mean_chart(df, "property_location", "monthly_rent", top_n=12),
        "monthly_rent_histogram": _histogram(df, "monthly_rent", bins=10),
    }
