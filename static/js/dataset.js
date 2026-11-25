/*
 * dataset.js — Generated Dataset page: search box, three filter selects,
 * and pagination, all driven by GET /api/dataset?search=&property_type=
 * &location=&lease_status=&page=&page_size=. Filter dropdown options are
 * populated from the API response itself (filter_options), so they
 * always match whatever was actually generated.
 */

const PAGE_SIZE = 25;
let currentPage = 1;
let debounceTimer = null;

document.addEventListener("DOMContentLoaded", async () => {
  const emptyState = document.getElementById("emptyState");
  const body = document.getElementById("datasetBody");

  const probe = await apiFetch("/api/dataset?page=1&page_size=1");
  if (!probe.ok) {
    emptyState.hidden = false;
    body.hidden = true;
    return;
  }
  emptyState.hidden = true;
  body.hidden = false;

  populateFilterOptions(probe.data.filter_options);
  loadPage(1);

  document.getElementById("searchInput").addEventListener("input", () => {
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(() => loadPage(1), 300);
  });
  ["filterPropertyType", "filterLocation", "filterLeaseStatus"].forEach((id) => {
    document.getElementById(id).addEventListener("change", () => loadPage(1));
  });
  document.getElementById("prevPageBtn").addEventListener("click", () => loadPage(currentPage - 1));
  document.getElementById("nextPageBtn").addEventListener("click", () => loadPage(currentPage + 1));
});

function populateFilterOptions(options) {
  if (!options) return;
  const fill = (id, values) => {
    const select = document.getElementById(id);
    values.forEach((v) => {
      const opt = document.createElement("option");
      opt.value = v;
      opt.textContent = v;
      select.appendChild(opt);
    });
  };
  fill("filterPropertyType", options.property_types || []);
  fill("filterLocation", options.locations || []);
  fill("filterLeaseStatus", options.lease_statuses || []);
}

async function loadPage(page) {
  const search = document.getElementById("searchInput").value.trim();
  const propertyType = document.getElementById("filterPropertyType").value;
  const location = document.getElementById("filterLocation").value;
  const leaseStatus = document.getElementById("filterLeaseStatus").value;

  const params = new URLSearchParams({
    page: String(Math.max(page, 1)),
    page_size: String(PAGE_SIZE),
  });
  if (search) params.set("search", search);
  if (propertyType) params.set("property_type", propertyType);
  if (location) params.set("location", location);
  if (leaseStatus) params.set("lease_status", leaseStatus);

  const { ok, data } = await apiFetch(`/api/dataset?${params.toString()}`);
  if (!ok) {
    showToast((data && data.error) || "Could not load the dataset.", "error");
    return;
  }

  currentPage = data.page;
  renderTable(data.records);
  document.getElementById("resultCount").textContent = `${formatNumber(data.total_records)} records`;
  document.getElementById("pageIndicator").textContent = `Page ${data.page} of ${data.total_pages}`;
  document.getElementById("prevPageBtn").disabled = data.page <= 1;
  document.getElementById("nextPageBtn").disabled = data.page >= data.total_pages;
}

function statusChip(status) {
  const cls = status === "Active" ? "status-active" : status === "Pending" ? "status-pending" : "status-expired";
  return `<span class="status-chip ${cls}">${status}</span>`;
}

function renderTable(records) {
  const tbody = document.getElementById("datasetTableBody");
  if (!records || records.length === 0) {
    tbody.innerHTML = `<tr><td colspan="22" class="muted">No records match your filters.</td></tr>`;
    return;
  }
  tbody.innerHTML = records
    .map(
      (r) => `<tr>
        <td class="mono">${r.lease_id}</td>
        <td class="mono">${r.property_id}</td>
        <td class="mono">${r.tenant_id}</td>
        <td>${r.property_type}</td>
        <td class="property-location"></td>
        <td>${r.tenant_industry}</td>
        <td class="mono">${formatNumber(r.property_size_sqft)}</td>
        <td class="mono">${(r.lease_start_date || "").slice(0, 10)}</td>
        <td class="mono">${(r.lease_end_date || "").slice(0, 10)}</td>
        <td class="mono">${r.lease_duration_years}</td>
        <td>${r.payment_frequency}</td>
        <td class="mono">${formatCurrency(r.monthly_rent)}</td>
        <td class="mono">${formatCurrency(r.annual_rent)}</td>
        <td class="mono">$${formatNumber(r.rent_per_sqft, 2)}</td>
        <td class="mono">${formatCurrency(r.security_deposit)}</td>
        <td>${r.lease_type}</td>
        <td class="mono">${formatNumber(r.escalation_rate, 2)}%</td>
        <td>${r.occupancy_status}</td>
        <td>${r.renewal_option}</td>
        <td>${r.maintenance_responsibility}</td>
        <td>${r.market_condition}</td>
        <td>${statusChip(r.lease_status)}</td>
      </tr>`
    )
    .join("");
  tbody.querySelectorAll(".property-location").forEach((cell, index) => {
    cell.textContent = records[index].property_location;
  });
}
