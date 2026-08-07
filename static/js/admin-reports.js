/**
 * Super Admin — reports: status/category/role breakdowns and signup trend.
 * Simple CSS bar charts (no chart library).
 */
document.addEventListener("DOMContentLoaded", () => {
  AdminReports.init();
});

const AdminReports = (() => {

  function init() {
    load();
  }

  async function load() {
    try {
      const data = await Api.get("/admin/reports/");
      const users = data.total_users || 0;
      set("report-users", users);
      set("report-complaints", data.total_complaints || 0);
      const byStatus = data.complaints_by_status || {};
      set("report-resolved", byStatus.RESOLVED || 0);
      set("report-pending", byStatus.PENDING_VALIDATION || 0);

      renderChart("by-status", byStatus, statusLabel);
      renderChart("by-category", data.complaints_by_category || {});
      renderChart("by-role", roleLabel(data.users_by_role || {}));
      renderTrend(data.signup_trend_14d || {});

      const gen = document.getElementById("generated-at");
      if (gen && data.generated_at) gen.textContent = I18n.t("generated_at") + ": " + UI.formatDate(data.generated_at);
    } catch (err) {
      UI.toast(err.message, "error");
    }
  }

  function renderChart(id, map, labelFn) {
    const el = document.getElementById(id);
    if (!el) return;
    const entries = Object.entries(map || {}).filter(([, v]) => v > 0);
    if (!entries.length) { el.innerHTML = '<p class="muted">—</p>'; return; }
    const max = Math.max(...entries.map(([, v]) => v), 1);
    el.innerHTML = entries.map(([key, val]) => {
      const label = labelFn ? labelFn(key) : key;
      return (
        '<div class="chart-row">' +
          '<span class="chart-label" title="' + UI.escapeHtml(label) + '">' + UI.escapeHtml(label) + "</span>" +
          '<div class="chart-track"><div class="chart-fill" style="width:' + Math.round((val / max) * 100) + '%"></div></div>' +
          '<span class="chart-val">' + val + "</span>" +
        "</div>"
      );
    }).join("");
  }

  function renderTrend(map) {
    const el = document.getElementById("trend");
    if (!el) return;
    const days = Object.keys(map || {}).sort();
    if (!days.length) { el.innerHTML = '<p class="muted">—</p>'; return; }
    const max = Math.max(...Object.values(map), 1);
    el.innerHTML = days.map((d) => {
      const val = map[d] || 0;
      const h = Math.max(4, Math.round((val / max) * 120));
      const short = d.slice(5); // MM-DD
      return (
        '<div class="trend-bar">' +
          "<span>" + val + "</span>" +
          '<div class="bar ' + (val >= max ? "hi" : "") + '" style="height:' + h + 'px"></div>' +
          "<span>" + short + "</span>" +
        "</div>"
      );
    }).join("");
  }

  function statusLabel(key) {
    return UI.statusLabel(key) || key;
  }

  function roleLabel(map) {
    const out = {};
    Object.entries(map).forEach(([k, v]) => { out[I18n.t("role_" + k)] = v; });
    return out;
  }

  function set(id, value) {
    const el = document.getElementById(id);
    if (el) el.textContent = value;
  }

  return { init };
})();
