/**
 * Official dashboard.
 *
 * - Registry statistics (total / verified / resolved / rejected)
 * - Verified complaint registry with search, status/category filters,
 *   urgency bounds, date range and sorting.
 * - View details or mark a complaint as resolved (with remarks).
 */
document.addEventListener("DOMContentLoaded", () => {
  UI.bindModalClose();
  Official.init();
});

const Official = (() => {
  const state = { page: 1, actionComplaintId: null };

  function init() {
    loadStats();
    loadRegistry(1);
    bindControls();
    bindActionModal();
  }

  // ---------------------------------------------------------------- stats
  async function loadStats() {
    try {
      const data = await Api.get("/analytics/");
      const by = data.by_status || {};
      setText("stat-total", data.total || 0);
      setText("stat-verified", by.VERIFIED || 0);
      setText("stat-resolved", by.RESOLVED || 0);
      setText("stat-rejected", by.REJECTED || 0);
    } catch (err) {
      console.warn("Stats unavailable:", err.message);
    }
  }

  // -------------------------------------------------------------- registry
  function buildParams(page) {
    const params = new URLSearchParams({ page: String(page) });
    const q = document.getElementById("search-input").value.trim();
    const status = document.getElementById("status-filter").value;
    const category = document.getElementById("category-filter").value;
    const sort = document.getElementById("sort-filter").value;
    const from = document.getElementById("date-from").value;
    const to = document.getElementById("date-to").value;
    if (q) params.set("q", q);
    if (status) params.set("status", status);
    if (category) params.set("category", category);
    if (sort) params.set("sort", sort);
    if (from) params.set("date_from", from);
    if (to) params.set("date_to", to);
    return params;
  }

  async function loadRegistry(page = 1) {
    const params = buildParams(page);
    const tbody = document.getElementById("official-table-body");
    tbody.innerHTML = '<tr><td colspan="7"><div class="skeleton-card"></div></td></tr>';

    try {
      const data = await Api.get("/complaints/?" + params.toString());
      renderTable(data.results || []);
      document.getElementById("empty-state").classList.toggle("hidden", (data.results || []).length > 0);
      UI.renderPagination(document.getElementById("pagination"), {
        page, totalPages: data.total_pages || 1, total: data.count,
        onPage: (p) => { state.page = p; loadRegistry(p); },
      });
    } catch (err) {
      tbody.innerHTML = "";
      UI.toast(err.message, "error");
    }
  }

  function renderTable(items) {
    const tbody = document.getElementById("official-table-body");
    if (!items.length) { tbody.innerHTML = ""; return; }

    tbody.innerHTML = items.map((c) => {
      const esc = UI.escapeHtml;
      const actions =
        '<button class="btn btn-ghost btn-sm" data-view="' + c.complaint_id + '">' + I18n.t("view_details") + "</button>" +
        (c.status === "VERIFIED"
          ? '<button class="btn btn-primary btn-sm" data-resolve="' + c.complaint_id + '">' + I18n.t("mark_resolved") + "</button>"
          : "");
      return (
        "<tr>" +
          '<td><span class="mono">' + c.complaint_id + "</span></td>" +
          "<td>" + esc(c.category) + "</td>" +
          '<td><span class="badge ' + UI.statusClass(c.status) + '">' + UI.statusLabel(c.status) + "</span></td>" +
          '<td><span class="urgency-pill ' + UI.urgencyClass(c.urgency_score) + '">' + c.urgency_score + "/10</span></td>" +
          "<td>" + esc((c.address || "").split(",")[0] || "—") + "</td>" +
          "<td>" + UI.formatDate(c.created_at, false) + "</td>" +
          '<td class="actions-cell">' + actions + "</td>" +
        "</tr>"
      );
    }).join("");

    tbody.querySelectorAll("[data-view]").forEach((btn) =>
      btn.addEventListener("click", () => { window.location.href = "/complaint/?id=" + btn.dataset.view; })
    );
    tbody.querySelectorAll("[data-resolve]").forEach((btn) =>
      btn.addEventListener("click", () => openResolveModal(btn.dataset.resolve))
    );
  }

  // --------------------------------------------------------------- resolve
  function openResolveModal(complaintId) {
    state.actionComplaintId = complaintId;
    document.getElementById("action-remarks").value = "";
    document.getElementById("action-confirm").textContent = I18n.t("mark_resolved");
    UI.openModal("action-modal");
  }

  function bindActionModal() {
    document.getElementById("action-confirm").addEventListener("click", confirmResolve);
  }

  async function confirmResolve() {
    if (!state.actionComplaintId) return;
    const remarks = document.getElementById("action-remarks").value.trim();
    UI.showLoading();
    try {
      await Api.post("/complaints/" + state.actionComplaintId + "/resolve/", { remarks });
      UI.hideLoading();
      UI.closeModal("action-modal");
      UI.toast(I18n.t("resolve_success"), "success");
      loadStats();
      loadRegistry(state.page);
    } catch (err) {
      UI.hideLoading();
      UI.toast(err.message, "error");
    }
  }

  // -------------------------------------------------------------- controls
  function bindControls() {
    const ids = ["search-input", "status-filter", "category-filter", "sort-filter", "date-from", "date-to"];
    ids.forEach((id) => {
      const el = document.getElementById(id);
      if (!el) return;
      const handler = id === "search-input"
        ? UI.debounce(() => { state.page = 1; loadRegistry(1); }, 350)
        : () => { state.page = 1; loadRegistry(1); };
      el.addEventListener(id === "search-input" ? "input" : "change", handler);
    });
  }

  function setText(id, value) {
    const el = document.getElementById(id);
    if (el) el.textContent = value;
  }

  return { init };
})();
