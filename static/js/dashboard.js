/*
 * dashboard.js — populates the KPI ledger, charts, and the recent
 * generations table from /api/analytics and /api/history. If no dataset
 * has been generated yet, /api/analytics returns 400 and we show the
 * empty state instead of a broken dashboard.
 */

document.addEventListener("DOMContentLoaded", async () => {
  const emptyState = document.getElementById("emptyState");
  const body = document.getElementById("dashboardBody");

  const { ok, data } = await apiFetch("/api/analytics", { cache: "no-store" });

  if (!ok) {
    emptyState.hidden = false;
    body.hidden = true;
    loadHistory(); // history can still be shown even with no live dataset
    return;
  }

  emptyState.hidden = true;
  body.hidden = false;

  const { kpis, charts } = data;

  document.getElementById("kpiTotalLeases").textContent = formatNumber(kpis.total_leases);
  document.getElementById("kpiTotalProperties").textContent = formatNumber(kpis.total_properties);
  document.getElementById("kpiAvgMonthlyRent").textContent = formatCurrency(kpis.avg_monthly_rent);
  document.getElementById("kpiAvgAnnualRent").textContent = formatCurrency(kpis.avg_annual_rent);
  document.getElementById("kpiAvgDuration").textContent = formatNumber(kpis.avg_lease_duration_years, 1) + " yrs";
  document.getElementById("kpiAvgRentSqft").textContent = "$" + formatNumber(kpis.avg_rent_per_sqft, 2);
  document.getElementById("kpiActive").textContent = formatNumber(kpis.active_leases);
  document.getElementById("kpiExpired").textContent = formatNumber(kpis.expired_leases);

  if (typeof Chart === "undefined") {
    document.getElementById("dashboardCharts").hidden = true;
    document.getElementById("chartError").hidden = false;
  } else {
    renderDashboardCharts(charts);
    document.getElementById("chartHelp").hidden = false;
  }

  loadHistory();
});

function renderDashboardCharts(charts) {
  renderBar("chartPropertyType", charts.lease_by_property_type.labels, charts.lease_by_property_type.values, { horizontal: true, label: "Leases" });
  renderBar("chartAvgRentByType", charts.avg_rent_by_property_type.labels, charts.avg_rent_by_property_type.values,
    { horizontal: true, label: "Average monthly rent", currency: true });
  renderPie("chartIndustryDoughnut", charts.tenant_industry_distribution.labels, charts.tenant_industry_distribution.values, { doughnut: true });
  renderPie("chartOccupancyPie", charts.occupancy_status_distribution.labels, charts.occupancy_status_distribution.values);
  renderLine("chartCommencementLine", charts.lease_commencement_trend.labels, charts.lease_commencement_trend.values, { label: "Leases commencing" });
  renderBar("chartDurationBar", charts.lease_duration_distribution.labels, charts.lease_duration_distribution.values, { label: "Leases" });
  renderBar("chartPaymentFrequency", charts.payment_frequency_distribution.labels, charts.payment_frequency_distribution.values, { label: "Leases" });
  renderHistogram("chartRentHistogram", charts.monthly_rent_histogram.labels, charts.monthly_rent_histogram.values);
  renderBar("chartLocationBar", charts.rent_by_location.labels, charts.rent_by_location.values,
    { horizontal: true, label: "Average monthly rent", currency: true });
}

async function loadHistory() {
  const { ok, data } = await apiFetch("/api/history");
  const tbody = document.getElementById("historyTableBody");
  if (!tbody) return;
  if (!ok || !data || data.length === 0) {
    tbody.innerHTML = `<tr><td colspan="5" class="muted">No generations yet.</td></tr>`;
    return;
  }
  tbody.replaceChildren();
  for (const run of data) {
    const cfg = run.config || {};
    const locations = cfg.locations || [];
    const row = tbody.insertRow();
    const values = [
      run.created_at.replace("T", " "),
      formatNumber(run.record_count),
      run.quality_score != null ? run.quality_score + "%" : "—",
      (cfg.property_types || []).join(", ") || "All",
      locations.slice(0, 3).join(", ") + (locations.length > 3 ? "…" : "") || "—",
    ];
    values.forEach((value, index) => {
      const cell = row.insertCell();
      cell.textContent = value;
      cell.classList.toggle("mono", index < 3);
    });
  }
}
