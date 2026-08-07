/**
 * Super Admin — complaint registry (every complaint in the system).
 */
document.addEventListener("DOMContentLoaded", () => {
  UI.bindModalClose();
  AdminComplaints.init();
});

const AdminComplaints = (() => {
  const state = { status: "", q: "", page: 1 };

  function init() {
    const q = document.getElementById("search-input");
    const status = document.getElementById("status-filter");
    if (q) q.addEventListener("input", UI.debounce(() => { state.q = q.value.trim(); load(1); }, 350));
    if (status) status.addEventListener("change", () => { state.status = status.value; load(1); });
    load(1);
  }

  async function load(page) {
    const body = document.getElementById("complaints-body");
    body.innerHTML = "<tr><td colspan='7'><div class='skeleton-card'></div></td></tr>";
    const params = new URLSearchParams({ page: String(page) });
    if (state.status) params.set("status", state.status);
    if (state.q) params.set("q", state.q);

    try {
      const data = await Api.get("/admin/complaints/?" + params.toString());
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

  function render(items) {
    const body = document.getElementById("complaints-body");
    if (!items.length) { body.innerHTML = ""; return; }
    body.innerHTML = items.map((c) => {
      const esc = UI.escapeHtml;
      return (
        "<tr data-id='" + esc(c.complaint_id) + "'>" +
          '<td class="mono">' + esc(c.complaint_id) + "</td>" +
          "<td>" + esc(c.category) + "</td>" +
          "<td>" + esc(c.citizen_name || "—") + "</td>" +
          '<td><span class="badge ' + UI.statusClass(c.status) + '">' + UI.statusLabel(c.status) + "</span></td>" +
          '<td><span class="urgency-pill ' + UI.urgencyClass(c.urgency_score) + '">' + c.urgency_score + "/10</span></td>" +
          "<td>" + UI.formatDate(c.created_at, false) + "</td>" +
          '<td><button class="btn btn-ghost btn-sm" data-view="' + esc(c.complaint_id) + '" data-i18n="view_complaint">View</button></td>' +
        "</tr>"
      );
    }).join("");

    body.querySelectorAll("[data-view]").forEach((btn) =>
      btn.addEventListener("click", () => openDetail(btn.dataset.view)));
  }

  async function openDetail(id) {
    UI.showLoading();
    try {
      const c = await Api.get("/admin/complaints/" + id + "/");
      UI.hideLoading();
      renderDetail(c);
    } catch (err) {
      UI.hideLoading();
      UI.toast(err.message, "error");
    }
  }

  function renderDetail(c) {
    const esc = UI.escapeHtml;
    const timeline = (c.timeline || []).map((t) =>
      '<div class="feed-item">' +
        "<b>" + esc(t.action) + "</b>" +
        "<p>" + esc(t.remarks || "") + "</p>" +
        "<time>" + UI.formatDate(t.timestamp) + " · " + esc(t.actor_name || t.actor_role || "") + "</time>" +
      "</div>"
    ).join("");

    document.getElementById("complaint-body").innerHTML =
      '<div class="detail-grid">' +
        detailItem("complaint_id", c.complaint_id) +
        detailItem("category", c.category) +
        detailItem("submitted_by", c.citizen_name) +
        detailItem("status", UI.statusLabel(c.status)) +
        detailItem("urgency", c.urgency_score + "/10") +
        detailItem("submitted_on", UI.formatDate(c.created_at)) +
        (c.address ? detailItem("location_col", c.address, true) : "") +
      "</div>" +
      '<div class="detail-item wide" style="margin-top:12px;"><span>Summary</span><p>' + esc(c.summary || "—") + "</p></div>" +
      '<div class="detail-item wide"><span>Transcript</span><p>' + esc(c.transcript || "—") + "</p></div>" +
      '<div class="doc-grid">' +
        (c.photo_url
          ? '<a class="doc-card" href="' + esc(c.photo_url) + '" target="_blank" rel="noopener"><img src="' + esc(c.photo_url) + '" alt="photo"><span>Photo</span></a>'
          : "") +
        (c.audio_url
          ? '<div class="doc-card" style="padding:12px;"><audio controls preload="none" src="' + esc(c.audio_url) + '"></audio></div>'
          : "") +
      "</div>" +
      '<div style="margin-top:14px;"><h3 class="section-title-sm">' + I18n.t("timeline") + "</h3>" + timeline + "</div>";

    UI.openModal("complaint-modal");
  }

  function detailItem(key, value, wide) {
    const esc = UI.escapeHtml;
    return '<div class="detail-item' + (wide ? " wide" : "") + '">' +
      "<span>" + I18n.t(key) + "</span><strong>" + (value == null || value === "" ? "—" : esc(String(value))) + "</strong></div>";
  }

  return { init };
})();
