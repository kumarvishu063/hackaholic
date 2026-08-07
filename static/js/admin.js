/**
 * Super Admin dashboard — platform statistics + recent signups/audit feed.
 */
document.addEventListener("DOMContentLoaded", () => {
  Admin.init();
});

const Admin = (() => {

  function init() {
    loadStats();
  }

  async function loadStats() {
    try {
      const data = await Api.get("/admin/dashboard/");
      set("stat-citizens", data.total_citizens || 0);
      set("stat-pending-validators", data.pending_validators || 0);
      set("stat-pending-officials", data.pending_officials || 0);
      set("stat-approved-validators", data.approved_validators || 0);
      set("stat-approved-officials", data.approved_officials || 0);
      set("stat-rejected", data.rejected_applications || 0);
      set("stat-pending-complaints", data.pending_complaints || 0);
      set("stat-resolved-complaints", data.resolved_complaints || 0);

      renderUsers(data.recent_users || []);
      renderAudit(data.recent_audit || []);

      const gen = document.getElementById("generated-at");
      if (gen && data.generated_at) {
        gen.textContent = I18n.t("generated_at") + ": " + UI.formatDate(data.generated_at);
      }
    } catch (err) {
      UI.toast(err.message, "error");
    }
  }

  function renderUsers(users) {
    const el = document.getElementById("recent-users");
    if (!el) return;
    if (!users.length) { el.innerHTML = '<p class="muted">—</p>'; return; }
    el.innerHTML = users.map((u) =>
      '<div class="feed-item">' +
        "<b>" + UI.escapeHtml(u.full_name) + "</b>" +
        "<p>" + UI.escapeHtml(u.email) + " · " + I18n.t("role_" + u.role) + "</p>" +
        "<time>" + UI.timeAgo(u.created_at) + "</time>" +
      "</div>"
    ).join("");
  }

  function renderAudit(logs) {
    const el = document.getElementById("recent-audit");
    if (!el) return;
    if (!logs.length) { el.innerHTML = '<p class="muted">—</p>'; return; }
    el.innerHTML = logs.map((a) =>
      '<div class="feed-item">' +
        "<b>" + UI.escapeHtml(a.action) + "</b>" +
        "<p>" + UI.escapeHtml(a.actor_email || "system") +
          (a.details && a.details.email ? " → " + UI.escapeHtml(a.details.email) : "") + "</p>" +
        "<time>" + UI.timeAgo(a.created_at) + "</time>" +
      "</div>"
    ).join("");
  }

  function set(id, value) {
    const el = document.getElementById(id);
    if (el) el.textContent = value;
  }

  return { init };
})();
