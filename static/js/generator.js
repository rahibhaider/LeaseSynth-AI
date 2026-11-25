document.addEventListener("DOMContentLoaded", () => {
  const scenarioForm = document.getElementById("scenarioForm");
  const manualForm = document.getElementById("generateForm");
  const scenarioInput = document.getElementById("scenarioInput");
  const scenarioBtn = document.getElementById("scenarioBtn");
  const generateBtn = document.getElementById("generateBtn");
  const aiEnabled = !scenarioBtn.disabled;

  async function generate(form, payload, errorBox, status, pendingMessage) {
    errorBox.hidden = true;
    scenarioBtn.disabled = true;
    generateBtn.disabled = true;
    status.textContent = pendingMessage;

    const { ok, data } = await apiFetch(form.getAttribute("action"), {
      method: "POST",
      body: JSON.stringify(payload),
    });

    if (ok) {
      status.textContent = data.message + " Opening dashboard…";
      window.location.assign("/dashboard");
      return;
    }

    status.textContent = "";
    errorBox.textContent = data?.error || "Dataset generation failed. Try again.";
    errorBox.hidden = false;
    scenarioBtn.disabled = !aiEnabled;
    generateBtn.disabled = false;
  }

  scenarioForm.addEventListener("submit", (event) => {
    event.preventDefault();
    if (scenarioBtn.disabled) return;

    const errorBox = document.getElementById("scenarioError");
    const description = scenarioInput.value.trim();
    if (!description) {
      errorBox.textContent = "Enter a scenario description.";
      errorBox.hidden = false;
      scenarioInput.focus();
      return;
    }

    generate(scenarioForm, { scenario_description: description }, errorBox,
      document.getElementById("scenarioStatus"), "Interpreting your scenario and generating leases…");
  });

  const customWrap = document.getElementById("customRecordCountWrap");
  manualForm.querySelectorAll('input[name="record_count_choice"]').forEach((radio) => {
    radio.addEventListener("change", () => {
      customWrap.hidden = radio.value !== "custom";
    });
  });

  manualForm.addEventListener("submit", (event) => {
    event.preventDefault();
    if (generateBtn.disabled) return;

    const payload = buildManualPayload(manualForm);
    const errorBox = document.getElementById("formError");
    const error = validateManualPayload(payload);
    if (error) {
      errorBox.textContent = error;
      errorBox.hidden = false;
      return;
    }

    generate(manualForm, payload, errorBox, document.getElementById("generateStatus"), "Generating leases…");
  });
});

function buildManualPayload(form) {
  const fields = new FormData(form);
  const count = fields.get("record_count_choice");
  const customCount = document.getElementById("customRecordCount");
  const customLocations = document.getElementById("customLocations").value
    .split(";").map((location) => location.trim()).filter(Boolean);

  return {
    num_records: count === "custom" ? customCount.valueAsNumber : Number(count),
    property_types: fields.getAll("property_types"),
    locations: [...fields.getAll("locations"), ...customLocations],
    tenant_industries: fields.getAll("tenant_industries"),
    lease_types: fields.getAll("lease_types"),
    occupancy_statuses: fields.getAll("occupancy_statuses"),
    market_conditions: fields.getAll("market_conditions"),
    payment_frequencies: fields.getAll("payment_frequencies"),
    lease_duration_min: document.getElementById("durationMin").valueAsNumber,
    lease_duration_max: document.getElementById("durationMax").valueAsNumber,
    escalation_rate_min: document.getElementById("escalationMin").valueAsNumber,
    escalation_rate_max: document.getElementById("escalationMax").valueAsNumber,
  };
}

function validateManualPayload(payload) {
  if (!Number.isInteger(payload.num_records) || payload.num_records < 1 || payload.num_records > 20000) {
    return "Select a record count or enter a whole number from 1 to 20,000.";
  }

  const requiredGroups = {
    property_types: "Property type",
    locations: "Location",
    tenant_industries: "Tenant industry",
    lease_types: "Lease type",
    payment_frequencies: "Payment frequency",
    occupancy_statuses: "Occupancy status",
    market_conditions: "Market condition",
  };
  const missingGroups = Object.entries(requiredGroups)
    .filter(([field]) => payload[field].length === 0)
    .map(([, label]) => label);
  return missingGroups.length ? `Select at least one option for ${missingGroups.join(", ")}.` : "";
}
