/*
 * main.js — shared utilities used by every page:
 *   - showToast(): small notification in the bottom-right corner
 *   - apiFetch(): fetch wrapper that always returns parsed JSON + ok flag
 *   - mobile sidebar toggle
 *   - AI status pill (polls /api/status so every page shows whether
 *     Groq is configured, without each page re-implementing it)
 */

function showToast(message, type = "info") {
  const stack = document.getElementById("toastStack");
  if (!stack) return;
  const icon = type === "error" ? "bi-exclamation-circle" : type === "success" ? "bi-check-circle" : "bi-info-circle";
  const el = document.createElement("div");
  el.className = `toast-item ${type === "error" ? "is-error" : type === "success" ? "is-success" : ""}`;
  el.innerHTML = `<i class="bi ${icon}"></i><span>${message}</span>`;
  stack.appendChild(el);
  setTimeout(() => {
    el.style.transition = "opacity 0.25s ease";
    el.style.opacity = "0";
    setTimeout(() => el.remove(), 260);
  }, 4200);
}

async function apiFetch(url, options = {}) {
  try {
    const resp = await fetch(url, {
      headers: { "Content-Type": "application/json" },
      ...options,
    });
    let body = null;
    try {
      body = await resp.json();
    } catch (_) {
      body = null;
    }
    return { ok: resp.ok, status: resp.status, data: body };
  } catch (err) {
    return { ok: false, status: 0, data: { error: "Network error — is the Flask server running?" } };
  }
}

function formatCurrency(value) {
  if (value === null || value === undefined || isNaN(value)) return "—";
  return "$" + Number(value).toLocaleString(undefined, { maximumFractionDigits: 0 });
}

function formatNumber(value, decimals = 0) {
  if (value === null || value === undefined || isNaN(value)) return "—";
  return Number(value).toLocaleString(undefined, { maximumFractionDigits: decimals, minimumFractionDigits: decimals });
}

// ---- Mobile sidebar toggle ----
(function initSidebarToggle() {
  const shell = document.getElementById("appShell");
  const toggle = document.getElementById("sidebarToggle");
  const scrim = document.getElementById("sidebarScrim");
  if (!shell || !toggle) return;
  toggle.addEventListener("click", () => shell.classList.toggle("sidebar-open"));
  if (scrim) scrim.addEventListener("click", () => shell.classList.remove("sidebar-open"));
})();

// ---- AI status pill ----
(function initAiStatusPill() {
  const pill = document.getElementById("aiStatusPill");
  const label = document.getElementById("aiStatusLabel");
  if (!pill || !label) return;
  apiFetch("/api/status").then(({ ok, data }) => {
    if (ok && data && data.ai_enabled) {
      pill.classList.add("is-on");
      label.textContent = `AI enabled (${data.groq_model || "Groq"})`;
    } else {
      pill.classList.add("is-off");
      label.textContent = "AI disabled — no API key";
    }
  });
})();
