/*
 * validation.js — Data Validation page: pulls GET /api/validation and
 * renders the quality score, summary ledger, per-check breakdown, and
 * the detailed error list (capped server-side at 500 rows).
 */

const CHECK_LABELS = {
  invalid_dates: "Invalid dates",
  duration_mismatches: "Lease duration mismatches",
  negative_or_missing_monetary_values: "Negative or missing monetary values",
  annual_rent_mismatches: "Annual rent calculation errors",
  invalid_property_sizes: "Invalid property sizes",
  rent_per_sqft_mismatches: "Rent-per-sqft calculation errors",
  invalid_escalation_rates: "Invalid escalation rates",
  status_inconsistencies: "Lease status inconsistencies",
};

document.addEventListener("DOMContentLoaded", async () => {
  const emptyState = document.getElementById("emptyState");
  const body = document.getElementById("validationBody");

  const { ok, data } = await apiFetch("/api/validation");
  if (!ok) {
    emptyState.hidden = false;
    body.hidden = true;
    return;
  }
  emptyState.hidden = true;
  body.hidden = false;

  document.getElementById("qualityScore").textContent = `${data.data_quality_percentage}%`;
  document.getElementById("valTotal").textContent = formatNumber(data.total_records);
  document.getElementById("valValid").textContent = formatNumber(data.valid_records);
  document.getElementById("valInvalid").textContent = formatNumber(data.invalid_records);
  document.getElementById("valDuplicates").textContent = formatNumber(data.duplicate_records);
  document.getElementById("valMissing").textContent = formatNumber(data.missing_value_cells);

  const checksGrid = document.getElementById("checksGrid");
  checksGrid.innerHTML = Object.entries(data.checks || {})
    .map(([key, count]) => {
      const label = CHECK_LABELS[key] || key;
      const cls = count > 0 ? "has-issues" : "clean";
      const icon = count > 0 ? "bi-exclamation-triangle" : "bi-check-circle";
      return `<div class="check-item ${cls}"><span><i class="bi ${icon}"></i> ${label}</span><span class="check-count mono">${count}</span></div>`;
    })
    .join("");

  const errorsTableBody = document.getElementById("errorsTableBody");
  const noErrorsState = document.getElementById("noErrorsState");
  const errorsTable = document.getElementById("errorsTable");
  const errorsNote = document.getElementById("errorsNote");

  if (!data.errors || data.errors.length === 0) {
    errorsTable.hidden = true;
    noErrorsState.hidden = false;
  } else {
    errorsTable.hidden = false;
    noErrorsState.hidden = true;
    errorsTableBody.innerHTML = data.errors
      .map(
        (e) =>
          `<tr><td class="mono">${e.row_index}</td><td class="mono">${e.lease_id || "—"}</td><td>${e.errors.join(", ")}</td></tr>`
      )
      .join("");
    errorsNote.textContent = data.truncated ? `Showing first ${data.errors.length} of ${data.invalid_records} invalid records` : `${data.errors.length} invalid record(s)`;
  }
});
