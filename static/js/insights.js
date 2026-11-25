/*
 * insights.js — AI Insights page. Posts a question to /api/insights
 * (which hands Groq only pre-computed pandas statistics, never raw
 * records) and appends the Q&A to a running thread. Also renders the
 * same KPI numbers as "grounding data" so the person can see exactly
 * what the AI was given.
 */

document.addEventListener("DOMContentLoaded", async () => {
  const emptyState = document.getElementById("emptyState");
  const body = document.getElementById("insightsBody");

  const { ok, data } = await apiFetch("/api/analytics");
  if (!ok) {
    emptyState.hidden = false;
    body.hidden = true;
    return;
  }
  emptyState.hidden = true;
  body.hidden = false;

  renderGroundingKpis(data.kpis);

  document.querySelectorAll(".chip-btn").forEach((chip) => {
    chip.addEventListener("click", () => {
      document.getElementById("insightQuestion").value = chip.textContent;
      askQuestion(chip.textContent);
    });
  });

  const form = document.getElementById("insightForm");
  if (form) {
    form.addEventListener("submit", (e) => {
      e.preventDefault();
      const input = document.getElementById("insightQuestion");
      const question = input.value.trim();
      if (!question) return;
      askQuestion(question);
      input.value = "";
    });
  }
});

function renderGroundingKpis(kpis) {
  const el = document.getElementById("insightKpis");
  if (!el || !kpis) return;
  const entries = [
    ["Total leases", formatNumber(kpis.total_leases)],
    ["Avg monthly rent", formatCurrency(kpis.avg_monthly_rent)],
    ["Avg lease duration", formatNumber(kpis.avg_lease_duration_years, 1) + " yrs"],
    ["Active leases", formatNumber(kpis.active_leases)],
    ["Expired leases", formatNumber(kpis.expired_leases)],
  ];
  el.innerHTML = entries
    .map(([label, value]) => `<div class="kpi-cell"><span class="kpi-label">${label}</span><span class="kpi-value mono">${value}</span></div>`)
    .join("");
}

async function askQuestion(question) {
  const panel = document.getElementById("insightThreadPanel");
  const thread = document.getElementById("insightThread");
  const askBtn = document.getElementById("askBtn");

  panel.hidden = false;
  askBtn.disabled = true;

  const qaEl = document.createElement("div");
  qaEl.className = "insight-qa";
  qaEl.innerHTML = `<div class="insight-q"><i class="bi bi-question-circle"></i> ${escapeHtml(question)}</div><div class="insight-a"><span class="insight-a-label">Thinking…</span></div>`;
  thread.prepend(qaEl);

  const { ok, data } = await apiFetch("/api/insights", {
    method: "POST",
    body: JSON.stringify({ question }),
  });

  askBtn.disabled = false;

  const answerEl = qaEl.querySelector(".insight-a");
  if (!ok) {
    answerEl.innerHTML = `<span class="insight-a-label" style="color:var(--danger)">Couldn't answer</span>${escapeHtml((data && data.error) || "Something went wrong.")}`;
    return;
  }
  answerEl.innerHTML = `<span class="insight-a-label">AI Insight</span>${escapeHtml(data.answer)}`;
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}
