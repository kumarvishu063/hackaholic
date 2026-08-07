/**
 * Super Admin — login history (password + face attempts).
 */
document.addEventListener("DOMContentLoaded", () => {
  AdminHistory.init();
});

const AdminHistory = (() => {
  const state = { q: "", success: "", page: 1 };

  function init() {
    const q = document.getElementById("search-input");
    const res = document.getElementById("result-filter");
    if (q) q.addEventListener("input", UI.debounce(() => { state.q = q.value.trim(); load(1); }, 350));
    if (res) res.addEventListener("change", () => { state.success = res.value; load(1); });
    load(1);
  }

  async function load(page) {
    const body = document.getElementById("history-body");
    body.innerHTML = "<tr><td colspan='6'><div class='skeleton-card'></div></td></tr>";
    const params = new URLSearchParams({ page: String(page) });
    if (state.q) params.set("q", state.q);
    if (state.success) params.set("success", state.success);

    try {
      const data = await Api.get("/admin/login-history/?" + params.toString());
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

  function render(rows) {
    const body = document.getElementById("history-body");
    if (!rows.length) { body.innerHTML = ""; return; }
    body.innerHTML = rows.map((h) => {
      const esc = UI.escapeHtml;
      return (
        "<tr>" +
          "<td>" + esc(h.email || "—") + "</td>" +
          '<td>' + (h.method === "password+face"
            ? '<span class="chip chip-role-validator">password + face</span>'
            : '<span class="chip chip-role-official">' + esc(h.method) + "</span>") + "</td>" +
          '<td><span class="badge ' + (h.success ? "badge-verified" : "badge-rejected") + '">' +
            (h.success ? I18n.t("success") : I18n.t("failed")) +
            (h.face_score != null ? " (" + Math.round(h.face_score * 100) + "%)" : "") + "</span></td>" +
          "<td>" + esc(h.ip || "—") + "</td>" +
          '<td class="muted" style="max-width:220px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="' + esc(h.user_agent || "") + '">' + esc(h.user_agent || "—") + "</td>" +
          "<td>" + UI.formatDate(h.created_at) + "</td>" +
        "</tr>"
      );
    }).join("");
  }

  return { init };
})();
