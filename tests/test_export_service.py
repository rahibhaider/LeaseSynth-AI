import sys
import os
import json
import tempfile

import pandas as pd

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from services.generation_service import GenerationConfig, generate_lease_dataset
from services.validation_service import validate_dataset
from services.analytics_service import compute_kpis
from services import export_service


def _df(n=100, seed=1):
    cfg = GenerationConfig.from_dict({"num_records": n, "seed": seed})
    return generate_lease_dataset(cfg)


def test_export_csv_contains_actual_records(tmp_path):
    df = _df(75, seed=2)
    path = export_service.export_csv(df, str(tmp_path))
    assert os.path.exists(path)
    reloaded = pd.read_csv(path)
    assert len(reloaded) == len(df)
    assert list(reloaded.columns) == list(df.columns)
    assert set(reloaded["lease_id"]) == set(df["lease_id"])


def test_export_json_contains_metadata_and_actual_records(tmp_path):
    df = _df(60, seed=3)
    path = export_service.export_json(df, str(tmp_path))
    with open(path) as f:
        data = json.load(f)
    assert data["metadata"]["is_synthetic_data"] is True
    assert data["metadata"]["record_count"] == len(df)
    assert len(data["records"]) == len(df)
    assert {r["lease_id"] for r in data["records"]} == set(df["lease_id"])


def test_export_validation_csv(tmp_path):
    df = _df(50, seed=4)
    report = validate_dataset(df)
    path = export_service.export_validation_csv(report, str(tmp_path))
    assert os.path.exists(path)
    with open(path) as f:
        content = f.read()
    assert "Data Validation Report" in content
    assert str(report["total_records"]) in content


def test_export_summary_report(tmp_path):
    df = _df(50, seed=5)
    report = validate_dataset(df)
    kpis = compute_kpis(df)
    path = export_service.export_summary_report(df, kpis, report, str(tmp_path))
    assert os.path.exists(path)
    with open(path) as f:
        content = f.read()
    assert "SYNTHETIC DATA" in content
    assert "KEY METRICS" in content


def test_filenames_are_unique_across_calls(tmp_path):
    df = _df(10, seed=6)
    path1 = export_service.export_csv(df, str(tmp_path))
    import time

    time.sleep(1.1)  # filenames are timestamped to the second
    path2 = export_service.export_csv(df, str(tmp_path))
    assert path1 != path2
