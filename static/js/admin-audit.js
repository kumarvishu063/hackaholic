/**
 * Super Admin — audit log viewer.
 */
document.addEventListener("DOMContentLoaded", () => {
  AdminAudit.init();
});

const AdminAudit = (() => {
  const state = { q: "", page: 1 };

  function init() {
    const q = document.getElementById("search-input");
    if (q) q.addEventListener("input", UI.debounce(() => { state.q = q.value.trim(); load(1); }, 350));
    load(1);
  }

  async function load(page) {
    const body = document.getElementById("audit-body");
    body.innerHTML = "<tr><td colspan='5'><div class='skeleton-card'></div></td></tr>";
    const params = new URLSearchParams({ page: String(page) });
    if (state.q) params.set("q", state.q);

    try {
      const data = await Api.get("/admin/audit-logs/?" + params.toString());
      render(data.results || []);
      document.getElementById("empty-state").classList.toggle("hidden", (data.results || []).length > 0);
      UI.renderPagination(document.getElementById("pagination"), {
        page, totalPages: data.total_pages || 1, total: data.count,
        onPage: (p) => { state.page = p; load(p); },
      });
    } catch (err) {
      body.innerHTML = "";
      UI.toast(err.message, "error");
    }
  }

  function render(entries) {
    const body = document.getElementById("audit-body");
    if (!entries.length) { body.innerHTML = ""; return; }
    body.innerHTML = entries.map((a) => {
      const esc = UI.escapeHtml;
      const target = a.details && a.details.email
        ? esc(a.details.email)
        : (a.target_type ? esc(a.target_type) + " " + esc(a.target_id || "") : "—");
      const details = Object.entries(a.details || {})
        .filter(([k]) => !["email"].includes(k))
        .map(([k, v]) => esc(k) + ": " + esc(String(v)))
        .join(", ");
      return (
        "<tr>" +
          "<td><b>" + esc(a.action) + "</b></td>" +
          "<td>" + esc(a.actor_email || "system") + "</td>" +
          "<td>" + target + "</td>" +
          '<td class="muted">' + (details || "—") + "</td>" +
          "<td>" + UI.formatDate(a.created_at) + "</td>" +
        "</tr>"
      );
    }).join("");
  }

  return { init };
})();
