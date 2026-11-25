"""
app.py — LeaseSynth AI Flask application.

This file only wires HTTP routes to the services in services/. All the
actual logic (generation math, validation rules, analytics, exports, AI
calls) lives in services/ so each piece can be tested in isolation.

State model: this is a local, single-user app (per the project brief).
The "current" dataset lives in the in-memory STATE dict below, and is
also persisted to generated_datasets/ (CSV + JSON) and to the SQLite
generation_history table on every /api/generate call, so history survives
a restart even though the live in-memory dataset does not.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime

from flask import Flask, render_template, request, jsonify, send_file, abort

from config import Config
from services import (
    generation_service,
    validation_service,
    analytics_service,
    export_service,
    ai_service,
    history_service,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config.from_object(Config)

history_service.init_db()

# ---------------------------------------------------------------------
# In-memory "current dataset" state (see module docstring).
# ---------------------------------------------------------------------
STATE = {
    "df": None,
    "validation_report": None,
    "analytics": None,
    "config": None,
    "generated_at": None,
    "csv_path": None,
    "json_path": None,
}


def _require_dataset():
    if STATE["df"] is None:
        abort(400, description="No dataset has been generated yet. Generate one from the Generate Dataset page first.")


def _dataframe_to_records(df, date_format="iso"):
    return json.loads(df.to_json(orient="records", date_format=date_format))


# =======================================================================
# Page routes
# =======================================================================

@app.route("/")
def index():
    return render_template("index.html", active_page="landing")


@app.route("/dashboard")
def dashboard():
    return render_template("dashboard.html", active_page="dashboard", ai_enabled=Config.AI_ENABLED)


@app.route("/generate")
def generate_page():
    return render_template(
        "generate.html",
        active_page="generate",
        property_types=generation_service.PROPERTY_TYPES,
        locations=sorted(generation_service.LOCATION_MULTIPLIERS.keys()),
        tenant_industries=generation_service.TENANT_INDUSTRIES,
        lease_types=generation_service.LEASE_TYPES,
        occupancy_statuses=generation_service.OCCUPANCY_STATUSES,
        market_conditions=generation_service.MARKET_CONDITIONS,
        payment_frequencies=generation_service.PAYMENT_FREQUENCIES,
        ai_enabled=Config.AI_ENABLED,
    )


@app.route("/dataset")
def dataset_page():
    return render_template("dataset.html", active_page="dataset")


@app.route("/validation")
def validation_page():
    return render_template("validation.html", active_page="validation")


@app.route("/insights")
def insights_page():
    return render_template("insights.html", active_page="insights", ai_enabled=Config.AI_ENABLED)


# =======================================================================
# API routes
# =======================================================================

@app.route("/api/interpret-scenario", methods=["POST"])
def api_interpret_scenario():
    params, error = _interpret_scenario(request.get_json(silent=True))
    if error:
        return error
    return jsonify({"ai_enabled": True, "parameters": params})


def _interpret_scenario(payload):
    text = payload.get("scenario_description") if isinstance(payload, dict) else None
    if not isinstance(text, str) or not text.strip():
        return None, (jsonify({"error": "Enter a scenario description."}), 400)
    if not Config.AI_ENABLED:
        return None, (jsonify({
            "error": "Add GROQ_API_KEY to your .env file to generate from a scenario.",
            "ai_enabled": False,
        }), 503)
    try:
        return ai_service.interpret_scenario(text.strip()[:2000]), None
    except ai_service.AIServiceError as e:
        return None, (jsonify({"error": str(e), "ai_enabled": True}), 502)


@app.route("/api/generate-from-scenario", methods=["POST"])
def api_generate_from_scenario():
    payload = request.get_json(silent=True)
    params, error = _interpret_scenario(payload)
    if error:
        return error
    if len(params["locations"]) > params["num_records"]:
        return jsonify({"error": "Request at least one lease per location."}), 400
    return _generate_dataset({
        **params,
        "scenario_description": payload["scenario_description"].strip(),
    })


@app.route("/api/generate", methods=["POST"])
def api_generate():
    payload = request.get_json(silent=True) or {}
    return _generate_dataset(payload)


def _generate_dataset(payload):
    if not isinstance(payload, dict):
        return jsonify({"error": "Generation settings must be a JSON object."}), 400
    try:
        gen_config = generation_service.GenerationConfig.from_dict(payload)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    try:
        df = generation_service.generate_lease_dataset(gen_config)
    except Exception:
        logger.exception("Generation failed")
        return jsonify({"error": "Dataset generation failed. Check server logs for details."}), 500

    report = validation_service.validate_dataset(df)
    kpis = analytics_service.compute_kpis(df)
    charts = analytics_service.compute_chart_data(df)

    finished_at = datetime.now()
    generated_at = finished_at.isoformat(timespec="seconds")
    filename = f"LeaseSynth_Dataset_{finished_at:%Y%m%d_%H%M%S_%f}"
    csv_path = export_service.export_csv(df, Config.DATASET_DIR, f"{filename}.csv")
    json_path = export_service.export_json(df, Config.DATASET_DIR, f"{filename}.json")
    saved_config = gen_config.to_dict()

    history_service.record_generation(
        record_count=len(df),
        config=saved_config,
        quality_score=report["data_quality_percentage"],
        csv_path=csv_path,
        json_path=json_path,
    )

    STATE.update(
        {
            "df": df,
            "validation_report": report,
            "analytics": {"kpis": kpis, "charts": charts},
            "config": saved_config,
            "generated_at": generated_at,
            "csv_path": csv_path,
            "json_path": json_path,
        }
    )

    return (
        jsonify(
            {
                "message": f"Generated {len(df)} synthetic lease records.",
                "record_count": len(df),
                "generated_at": generated_at,
                "data_quality_percentage": report["data_quality_percentage"],
                "preview": _dataframe_to_records(df.head(10)),
            }
        ),
        201,
    )


@app.route("/api/dataset")
def api_dataset():
    _require_dataset()
    df = STATE["df"]

    search = request.args.get("search", "").strip().lower()
    property_type = request.args.get("property_type", "").strip()
    location = request.args.get("location", "").strip()
    lease_status = request.args.get("lease_status", "").strip()

    try:
        page = max(int(request.args.get("page", 1)), 1)
    except ValueError:
        page = 1
    try:
        page_size = min(max(int(request.args.get("page_size", 25)), 1), 200)
    except ValueError:
        page_size = 25

    view = df
    if property_type:
        view = view[view["property_type"] == property_type]
    if location:
        view = view[view["property_location"] == location]
    if lease_status:
        view = view[view["lease_status"] == lease_status]
    if search:
        mask = view.apply(lambda row: search in " ".join(str(v) for v in row.values).lower(), axis=1)
        view = view[mask]

    total = len(view)
    start = (page - 1) * page_size
    end = start + page_size
    page_df = view.iloc[start:end]

    return jsonify(
        {
            "total_records": total,
            "page": page,
            "page_size": page_size,
            "total_pages": max(1, (total + page_size - 1) // page_size),
            "records": _dataframe_to_records(page_df),
            "filter_options": {
                "property_types": sorted(df["property_type"].unique().tolist()),
                "locations": sorted(df["property_location"].unique().tolist()),
                "lease_statuses": sorted(df["lease_status"].unique().tolist()),
            },
        }
    )


@app.route("/api/validation")
def api_validation():
    _require_dataset()
    return jsonify(STATE["validation_report"])


@app.route("/api/analytics")
def api_analytics():
    _require_dataset()
    return jsonify(STATE["analytics"])


@app.route("/api/insights", methods=["POST"])
def api_insights():
    _require_dataset()
    payload = request.get_json(silent=True) or {}
    question = (payload.get("question") or "").strip()
    if not question:
        return jsonify({"error": "question is required"}), 400
    if not Config.AI_ENABLED:
        return jsonify({
            "error": "AI features are disabled: no GROQ_API_KEY configured.",
            "ai_enabled": False,
        }), 503

    stats_summary = {
        "kpis": STATE["analytics"]["kpis"],
        "charts_summary": STATE["analytics"]["charts"],
    }
    try:
        answer = ai_service.generate_insight(question, stats_summary)
        return jsonify({"question": question, "answer": answer, "ai_enabled": True})
    except ai_service.AIServiceError as e:
        return jsonify({"error": str(e), "ai_enabled": True}), 502


@app.route("/api/export/csv")
def api_export_csv():
    _require_dataset()
    year = datetime.now().year
    return send_file(STATE["csv_path"], as_attachment=True, download_name=f"LeaseSynth_Dataset_{year}.csv")


@app.route("/api/export/json")
def api_export_json():
    _require_dataset()
    year = datetime.now().year
    return send_file(STATE["json_path"], as_attachment=True, download_name=f"LeaseSynth_Dataset_{year}.json")


@app.route("/api/export/validation-csv")
def api_export_validation_csv():
    _require_dataset()
    path = export_service.export_validation_csv(STATE["validation_report"], Config.DATASET_DIR)
    year = datetime.now().year
    return send_file(path, as_attachment=True, download_name=f"LeaseSynth_ValidationReport_{year}.csv")


@app.route("/api/export/summary")
def api_export_summary():
    _require_dataset()
    path = export_service.export_summary_report(
        STATE["df"], STATE["analytics"]["kpis"], STATE["validation_report"], Config.DATASET_DIR
    )
    year = datetime.now().year
    return send_file(path, as_attachment=True, download_name=f"LeaseSynth_Summary_{year}.txt")


@app.route("/api/history")
def api_history():
    return jsonify(history_service.get_recent_generations(limit=10))


@app.route("/api/status")
def api_status():
    """Lightweight status endpoint the frontend polls to know whether AI
    features and a current dataset are available."""
    return jsonify(
        {
            "ai_enabled": Config.AI_ENABLED,
            "groq_model": Config.GROQ_MODEL if Config.AI_ENABLED else None,
            "has_dataset": STATE["df"] is not None,
            "record_count": int(len(STATE["df"])) if STATE["df"] is not None else 0,
            "generated_at": STATE["generated_at"],
        }
    )


# =======================================================================
# Error handlers
# =======================================================================

@app.errorhandler(400)
def bad_request(e):
    return jsonify({"error": str(e.description)}), 400


@app.errorhandler(404)
def not_found(e):
    if request.path.startswith("/api/"):
        return jsonify({"error": "Not found"}), 404
    return render_template("index.html", active_page="landing"), 404


@app.errorhandler(500)
def server_error(e):
    logger.exception("Unhandled server error")
    return jsonify({"error": "Internal server error"}), 500


if __name__ == "__main__":
    app.run(host=Config.HOST, port=Config.PORT, debug=Config.DEBUG)
