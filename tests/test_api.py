import sys
import os
import json
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import app as flask_app_module


@pytest.fixture()
def client():
    flask_app_module.app.config.update(TESTING=True)
    flask_app_module.STATE.update(
        {
            "df": None,
            "validation_report": None,
            "analytics": None,
            "config": None,
            "generated_at": None,
            "csv_path": None,
            "json_path": None,
        }
    )
    with flask_app_module.app.test_client() as client:
        yield client


@pytest.mark.parametrize(
    "route",
    ["/", "/dashboard", "/generate", "/dataset", "/validation", "/insights"],
)
def test_page_routes_return_200(client, route):
    resp = client.get(route)
    assert resp.status_code == 200


def test_dataset_api_requires_generation_first(client):
    resp = client.get("/api/dataset")
    assert resp.status_code == 400


def test_generate_then_read_back_dataset(client):
    resp = client.post("/api/generate", json={"num_records": 80, "seed": 1})
    assert resp.status_code == 201
    body = resp.get_json()
    assert body["record_count"] == 80
    assert body["data_quality_percentage"] == 100.0

    resp2 = client.get("/api/dataset?page=1&page_size=10")
    assert resp2.status_code == 200
    body2 = resp2.get_json()
    assert body2["total_records"] == 80
    assert len(body2["records"]) == 10


def test_generate_rejects_bad_payload(client):
    resp = client.post("/api/generate", json={"num_records": -1})
    assert resp.status_code == 400
    assert "error" in resp.get_json()


def test_validation_and_analytics_after_generation(client):
    client.post("/api/generate", json={"num_records": 120, "seed": 2})

    val = client.get("/api/validation")
    assert val.status_code == 200
    assert val.get_json()["total_records"] == 120

    analytics = client.get("/api/analytics")
    assert analytics.status_code == 200
    body = analytics.get_json()
    assert "kpis" in body and "charts" in body
    assert body["kpis"]["total_leases"] == 120


def test_generate_from_description_updates_dashboard_without_manual_settings(client, monkeypatch):
    ai = flask_app_module.ai_service
    description = "Generate 12 warehouse leases in São Paulo, Brazil, and 東京 with annual payments."
    requests = []

    def complete(**kwargs):
        requests.append(kwargs["messages"][-1]["content"])
        params = {
            "num_records": 12,
            "property_types": ["Warehouse"],
            "locations": ["são paulo, brazil", "東京"],
            "payment_frequencies": ["Annual"],
            "escalation_rate_min": 0,
            "escalation_rate_max": 0,
        }
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(params)))])

    monkeypatch.setattr(flask_app_module.Config, "AI_ENABLED", True)
    monkeypatch.setattr(ai, "_get_client", lambda: SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=complete))
    ))

    first = client.post("/api/generate", json={"num_records": 20, "property_types": ["Office"]})
    assert first.status_code == 201
    response = client.post("/api/generate-from-scenario", json={"scenario_description": description})
    assert response.status_code == 201
    assert requests == [description]

    records = client.get("/api/dataset").get_json()["records"]
    analytics = client.get("/api/analytics").get_json()
    assert len(records) == analytics["kpis"]["total_leases"] == 12
    locations = {"São Paulo, Brazil", "東京"}
    assert {record["property_location"] for record in records} == locations
    assert all(2.0 <= record["escalation_rate"] <= 4.0 for record in records)
    assert set(analytics["charts"]["rent_by_location"]["labels"]) == locations
    filtered = client.get("/api/dataset", query_string={"location": "東京"}).get_json()
    assert filtered["records"]
    assert {record["property_location"] for record in filtered["records"]} == {"東京"}
    assert analytics["charts"]["lease_by_property_type"] == {"labels": ["Warehouse"], "values": [12]}
    assert analytics["charts"]["payment_frequency_distribution"] == {"labels": ["Annual"], "values": [12]}
    avg_rent = round(sum(row["monthly_rent"] for row in records) / len(records), 2)
    assert analytics["charts"]["avg_rent_by_property_type"]["values"] == [avg_rent]
    assert client.get("/api/history").get_json()[0]["config"]["scenario_description"] == description


def test_failed_scenario_preserves_current_dataset(client, monkeypatch):
    ai = flask_app_module.ai_service

    def unavailable(text):
        raise ai.AIServiceError("Could not interpret scenario.")

    monkeypatch.setattr(flask_app_module.Config, "AI_ENABLED", True)
    monkeypatch.setattr(ai, "interpret_scenario", unavailable)
    client.post("/api/generate", json={"num_records": 10})

    response = client.post("/api/generate-from-scenario", json={"scenario_description": "Office leases"})
    assert response.status_code == 502
    assert client.get("/api/analytics").get_json()["kpis"]["total_leases"] == 10


def test_scenario_with_more_locations_than_leases_returns_error(client, monkeypatch):
    monkeypatch.setattr(flask_app_module.Config, "AI_ENABLED", True)
    monkeypatch.setattr(flask_app_module.ai_service, "interpret_scenario",
                        lambda text: {"locations": ["Pune", "Tokyo"], "num_records": 1})
    response = client.post("/api/generate-from-scenario", json={
        "scenario_description": "Generate one lease in Pune and Tokyo.",
    })
    assert response.status_code == 400
    assert response.get_json()["error"] == "Request at least one lease per location."


def test_exports_after_generation(client):
    client.post("/api/generate", json={"num_records": 40, "seed": 3})

    csv_resp = client.get("/api/export/csv")
    assert csv_resp.status_code == 200
    assert "attachment" in csv_resp.headers.get("Content-Disposition", "")

    json_resp = client.get("/api/export/json")
    assert json_resp.status_code == 200

    val_csv_resp = client.get("/api/export/validation-csv")
    assert val_csv_resp.status_code == 200

    summary_resp = client.get("/api/export/summary")
    assert summary_resp.status_code == 200


def test_history_endpoint_records_generations(client):
    client.post("/api/generate", json={"num_records": 30, "seed": 4})
    resp = client.get("/api/history")
    assert resp.status_code == 200
    history = resp.get_json()
    assert len(history) >= 1
    assert history[0]["record_count"] == 30


def test_ai_endpoints_return_503_without_api_key(client):
    from config import Config

    Config.AI_ENABLED = False
    Config.GROQ_API_KEY = ""

    resp = client.post("/api/interpret-scenario", json={"scenario_description": "Offices in Dallas"})
    assert resp.status_code == 503
    resp = client.post("/api/generate-from-scenario", json={"scenario_description": "Offices in Dallas"})
    assert resp.status_code == 503

    client.post("/api/generate", json={"num_records": 10, "seed": 5})
    resp2 = client.post("/api/insights", json={"question": "What is the average rent?"})
    assert resp2.status_code == 503


def test_dataset_filters_work_through_api(client):
    client.post(
        "/api/generate",
        json={"num_records": 200, "property_types": ["Office", "Retail"], "seed": 6},
    )
    resp = client.get("/api/dataset?property_type=Office")
    body = resp.get_json()
    assert all(r["property_type"] == "Office" for r in body["records"])


def test_status_endpoint(client):
    resp = client.get("/api/status")
    assert resp.status_code == 200
    body = resp.get_json()
    assert "ai_enabled" in body
    assert "has_dataset" in body
