/**
 * Super Admin — approval applications.
 * Tabs (status), role filter, search, paginated cards, detail modal,
 * approve + reject (with mandatory remarks).
 */
document.addEventListener("DOMContentLoaded", () => {
  UI.bindModalClose();
  AdminApps.init();
});

const AdminApps = (() => {
  const state = { status: "PENDING", role: "", q: "", page: 1 };

  function init() {
    bindTabs();
    bindFilters();
    load(1);
  }

  function bindTabs() {
    document.querySelectorAll("#status-tabs .tab-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        document.querySelectorAll("#status-tabs .tab-btn").forEach((b) => b.classList.remove("active"));
        btn.classList.add("active");
        state.status = btn.dataset.status;
        load(1);
      });
    });
  }

  function bindFilters() {
    const role = document.getElementById("role-filter");
    if (role) role.addEventListener("change", () => { state.role = role.value; load(1); });
    const q = document.getElementById("search-input");
    if (q) q.addEventListener("input", UI.debounce(() => { state.q = q.value.trim(); load(1); }, 350));
  }

  async function load(page) {
    const grid = document.getElementById("apps-grid");
    grid.innerHTML = '<div class="skeleton-card"></div><div class="skeleton-card"></div>';
    const params = new URLSearchParams({ page: String(page) });
    if (state.status) params.set("status", state.status);
    if (state.role) params.set("role", state.role);
    if (state.q) params.set("q", state.q);

    try {
      const data = await Api.get("/admin/applications/?" + params.toString());
      render(data.results || []);
      document.getElementById("empty-state").classList.toggle("hidden", (data.results || []).length > 0);
      UI.renderPagination(document.getElementById("pagination"), {
        page, totalPages: data.total_pages || 1, total: data.count,
        onPage: (p) => { state.page = p; load(p); },
      });
    } catch (err) {
      grid.innerHTML = "";
      UI.toast(err.message, "error");
    }
  }

  function render(items) {
    const grid = document.getElementById("apps-grid");
    if (!items.length) { grid.innerHTML = ""; return; }
    grid.innerHTML = items.map(cardHTML).join("");
    grid.querySelectorAll("[data-view]").forEach((btn) =>
      btn.addEventListener("click", () => openDetail(btn.dataset.view)));
    grid.querySelectorAll("[data-approve]").forEach((btn) =>
      btn.addEventListener("click", () => approve(btn.dataset.approve)));
    grid.querySelectorAll("[data-reject]").forEach((btn) =>
      btn.addEventListener("click", () => openReject(btn.dataset.reject)));
  }

  function cardHTML(a) {
    const esc = UI.escapeHtml;
    const statusClass = "chip-" + (a.application_status || "pending").toLowerCase();
    return (
      '<article class="app-card">' +
        '<div class="app-card-head">' +
          '<span class="app-avatar">' + UI.initials(a.full_name) + "</span>" +
          '<span class="chip ' + statusClass + '">' + I18n.t((a.application_status || "pending").toLowerCase()) + "</span>" +
        "</div>" +
        '<div class="app-meta">' +
          '<span class="mono-id">' + esc(a.application_id) + "</span>" +
          "<b>" + esc(a.full_name) + "</b>" +
          "<span>" + esc(a.email) + " · " + I18n.t("role_" + a.role_requested) + "</span>" +
          "<span>" + I18n.t("department") + ": " + esc(a.department || "—") + " · " + I18n.t("employee_id") + ": " + esc(a.employee_id || "—") + "</span>" +
          "<span>" + I18n.t("office_name") + ": " + esc(a.office_name || "—") + "</span>" +
          "<span>" + I18n.t("face_status") + ": " +
            (a.face_registered ? I18n.t("face_registered_yes") : I18n.t("face_registered_no")) + "</span>" +
          "<span>" + I18n.t("applied_on") + ": " + UI.formatDate(a.applied_on) + "</span>" +
        "</div>" +
        '<div class="app-docs">' +
          docThumb(a.government_id_document, "id") +
          docThumb(a.employee_card, "card") +
          docThumb(a.profile_photo, "photo") +
        "</div>" +
        '<div class="app-actions">' +
          '<button class="btn btn-ghost btn-sm" data-view="' + esc(a.application_id) + '" data-i18n="view_complete_details">View Details</button>' +
          (a.application_status === "PENDING"
            ? '<button class="btn btn-primary btn-sm" data-approve="' + esc(a.application_id) + '" data-i18n="approve">Approve</button>' +
              '<button class="btn btn-danger-ghost btn-sm" data-reject="' + esc(a.application_id) + '" data-i18n="reject_with_reason">Reject</button>'
            : "") +
        "</div>" +
      "</article>"
    );
  }

  function docThumb(url, kind) {
    const esc = UI.escapeHtml;
    if (!url) return '<div class="doc-thumb"><svg class="icon"><use href="/static/icons.svg#icon-doc"/></svg></div>';
    return '<a class="doc-thumb" href="' + esc(url) + '" target="_blank" rel="noopener" title="' + kind + '">' +
      '<img src="' + esc(url) + '" alt="' + kind + '">' +
      "</a>";
  }

  // ------------------------------------------------------------------ detail
  async function openDetail(applicationId) {
    UI.showLoading();
    try {
      const a = await Api.get("/admin/applications/" + applicationId + "/");
      UI.hideLoading();
      renderDetail(a);
    } catch (err) {
      UI.hideLoading();
      UI.toast(err.message, "error");
    }
  }

  function renderDetail(a) {
    const esc = UI.escapeHtml;
    const status = document.getElementById("detail-status");
    status.textContent = I18n.t((a.application_status || "pending").toLowerCase());
    status.className = "chip chip-" + (a.application_status || "pending").toLowerCase();

    document.getElementById("detail-body").innerHTML =
      '<div class="detail-grid">' +
        detailItem("application_id", a.application_id) +
        detailItem("applicant_name", a.full_name) +
        detailItem("applicant_email", a.email) +
        detailItem("applicant_phone", a.phone) +
        detailItem("user_role", a.role_requested) +
        detailItem("department", a.department) +
        detailItem("employee_id", a.employee_id) +
        detailItem("office_name", a.office_name) +
        detailItem("face_status", a.face_registered ? I18n.t("face_registered_yes") : I18n.t("face_registered_no")) +
        detailItem("applied_on", UI.formatDate(a.applied_on)) +
        (a.reviewed_on ? detailItem("reviewed_on", UI.formatDate(a.reviewed_on)) : "") +
        (a.remarks ? detailItem("review_note", a.remarks) : "") +
        detailItem("office_address", a.office_address, true) +
      "</div>" +
      '<div class="doc-grid">' +
        docFull(a.government_id_document, "government_id") +
        docFull(a.employee_card, "employee_card") +
        docFull(a.profile_photo, "profile_photo") +
      "</div>";

    const actions = document.getElementById("detail-actions");
    if (a.application_status === "PENDING") {
      actions.innerHTML =
        '<div style="display:flex;gap:10px;">' +
          '<button class="btn btn-danger-ghost grow" id="detail-reject" data-i18n="reject_with_reason">Reject</button>' +
          '<button class="btn btn-primary grow" id="detail-approve" data-i18n="approve">Approve</button>' +
        "</div>";
      document.getElementById("detail-approve").addEventListener("click", () => approve(a.application_id));
      document.getElementById("detail-reject").addEventListener("click", () => { UI.closeModal("detail-modal"); openReject(a.application_id); });
    } else {
      actions.innerHTML = '<button class="btn btn-ghost btn-block" data-close-modal data-i18n="ok">OK</button>';
    }
    UI.openModal("detail-modal");
  }

  function detailItem(key, value, wide) {
    const esc = UI.escapeHtml;
    return '<div class="detail-item' + (wide ? " wide" : "") + '">' +
      "<span>" + I18n.t(key) + "</span><strong>" + (value == null || value === "" ? "—" : esc(String(value))) + "</strong></div>";
  }

  function docFull(url, label) {
    const esc = UI.escapeHtml;
    if (!url) return "";
    return '<a class="doc-card" href="' + esc(url) + '" target="_blank" rel="noopener">' +
      '<img src="' + esc(url) + '" alt="' + label + '"><span>' + I18n.t(label) + "</span></a>";
  }

  // ----------------------------------------------------------------- approve
  async function approve(applicationId) {
    if (!window.confirm(I18n.t("confirm_action") + " (" + I18n.t("approve") + ")")) return;
    UI.showLoading();
    try {
      const data = await Api.patch("/admin/applications/" + applicationId + "/approve/", {});
      UI.hideLoading();
      UI.toast(data.message || "Application approved.", "success");
      UI.closeAllModals();
      load(state.page);
    } catch (err) {
      UI.hideLoading();
      UI.toast(err.message, "error");
    }
  }

  // ----------------------------------------------------------------- reject
  function openReject(applicationId) {
    document.getElementById("reject-remarks").value = "";
    document.getElementById("reject-error").textContent = "";
    const btn = document.getElementById("reject-confirm-btn");
    btn.onclick = () => reject(applicationId);
    UI.openModal("reject-modal");
  }

  async function reject(applicationId) {
    const remarks = document.getElementById("reject-remarks").value.trim();
    const errorEl = document.getElementById("reject-error");
    errorEl.textContent = "";
    if (remarks.length < 5) {
      errorEl.textContent = I18n.t("rejection_reason_ph").replace(" (required)", "");
      return;
    }
    UI.showLoading();
    try {
      const data = await Api.patch("/admin/applications/" + applicationId + "/reject/", { remarks });
      UI.hideLoading();
      UI.toast(data.message || "Application rejected.", "success");
      UI.closeAllModals();
      load(state.page);
    } catch (err) {
      UI.hideLoading();
      errorEl.textContent = err.message;
    }
  }

  return { init };
})();
