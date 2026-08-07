/**
 * Validator dashboard.
 *
 * - Workload statistics (pending / verified / rejected / avg urgency)
 * - Pending complaints with full evidence: transcript, summary, photo,
 *   audio player and map link.
 * - Verify or reject actions with optional remarks.
 */
document.addEventListener("DOMContentLoaded", () => {
  Validator.init();
});

const Validator = (() => {
  const state = { page: 1 };

  function init() {
    loadStats();
    loadPending(1);
    bindControls();
  }

  // ---------------------------------------------------------------- stats
  async function loadStats() {
    try {
      const data = await Api.get("/analytics/");
      const by = data.by_status || {};
      setText("stat-pending", by.PENDING_VALIDATION || 0);
      setText("stat-verified", by.VERIFIED || 0);
      setText("stat-rejected", by.REJECTED || 0);
      setText("stat-avg", data.avg_urgency || 0);
    } catch (err) {
      console.warn("Stats unavailable:", err.message);
    }
  }

  // -------------------------------------------------------------- pending
  async function loadPending(page = 1) {
    const q = document.getElementById("search-input").value.trim();
    const category = document.getElementById("category-filter").value;
    const minUrgency = document.getElementById("urgency-filter").value;
    const params = new URLSearchParams({ page: String(page), status: "PENDING_VALIDATION" });
    if (q) params.set("q", q);
    if (category) params.set("category", category);
    if (minUrgency) params.set("min_urgency", minUrgency);

    const listEl = document.getElementById("review-list");
    listEl.innerHTML = '<div class="skeleton-card"></div><div class="skeleton-card"></div>';

    try {
      const data = await Api.get("/complaints/?" + params.toString());
      renderCards(data.results || []);
      document.getElementById("empty-state").classList.toggle("hidden", (data.results || []).length > 0);
      UI.renderPagination(document.getElementById("pagination"), {
        page, totalPages: data.total_pages || 1, total: data.count,
        onPage: (p) => { state.page = p; loadPending(p); },
      });
    } catch (err) {
      listEl.innerHTML = "";
      UI.toast(err.message, "error");
    }
  }

  function renderCards(items) {
    const listEl = document.getElementById("review-list");
    if (!items.length) { listEl.innerHTML = ""; return; }
    listEl.innerHTML = items.map((c) => cardHTML(c)).join("");
    listEl.querySelectorAll("[data-verify]").forEach((btn) =>
      btn.addEventListener("click", () => review("verify", btn.dataset.id))
    );
    listEl.querySelectorAll("[data-reject]").forEach((btn) =>
      btn.addEventListener("click", () => review("reject", btn.dataset.id))
    );
  }

  function cardHTML(c) {
    const esc = UI.escapeHtml;
    const mapLink = c.latitude && c.longitude
      ? '<a class="map-link" target="_blank" rel="noopener" href="https://maps.google.com/?q=' + c.latitude + "," + c.longitude + '">' +
        '<svg class="icon"><use href="/static/icons.svg#icon-map-pin"/></svg>' + esc(c.address || c.latitude + ", " + c.longitude) + "</a>"
      : (c.address ? esc(c.address) : "");

    const audioBlock = c.audio_url
      ? '<audio controls preload="none" src="' + esc(c.audio_url) + '"></audio>'
      : '<span class="muted">' + I18n.t("no_audio") + "</span>";

    const photoBlock = c.photo_url
      ? '<img class="evidence-img" src="' + esc(c.photo_url) + '" alt="Photo evidence">'
      : '<span class="muted">' + I18n.t("no_photo") + "</span>";

    return (
      '<article class="review-card">' +
        '<div class="review-card-head">' +
          '<div>' +
            '<div class="complaint-item-top">' +
              '<span class="mono-id">' + c.complaint_id + "</span>" +
              '<span class="chip">' + esc(c.category) + "</span>" +
              '<span class="urgency-pill ' + UI.urgencyClass(c.urgency_score) + '">' + c.urgency_score + "/10</span>" +
            "</div>" +
            "<p class=\"desc\">" + esc(c.description || "(no typed description)") + "</p>" +
            "<div>" + mapLink + "</div>" +
          "</div>" +
          '<div class="complaint-thumb-wrap">' + photoBlock + "</div>" +
        "</div>" +
        '<div class="review-evidence">' +
          '<div class="evidence-block"><strong>' + I18n.t("transcript") + "</strong><p>" + esc(c.transcript || "—") + "</p></div>" +
          '<div class="evidence-block"><strong>' + I18n.t("audio_recording") + "</strong>" + audioBlock + "</div>" +
        "</div>" +
        '<div class="review-actions">' +
          '<textarea data-remarks="' + c.complaint_id + '" rows="2" placeholder="' + I18n.t("remarks_placeholder") + '" maxlength="2000"></textarea>' +
          '<button class="btn btn-danger-ghost" data-reject data-id="' + c.complaint_id + '">' + I18n.t("reject") + "</button>" +
          '<button class="btn btn-primary" data-verify data-id="' + c.complaint_id + '">' + I18n.t("verify") + "</button>" +
        "</div>" +
      "</article>"
    );
  }

  // ---------------------------------------------------------------- review
  async function review(action, complaintId) {
    const remarksEl = document.querySelector('[data-remarks="' + complaintId + '"]');
    const remarks = remarksEl ? remarksEl.value.trim() : "";
    const confirmMsg = action === "verify" ? I18n.t("confirm_verify") : I18n.t("confirm_reject");
    if (!window.confirm(confirmMsg)) return;

    UI.showLoading();
    try {
      await Api.post("/complaints/" + complaintId + "/validate/", { action, remarks });
      UI.hideLoading();
      UI.toast(action === "verify" ? I18n.t("verify_success") : I18n.t("reject_success"), "success");
      loadStats();
      loadPending(state.page);
    } catch (err) {
      UI.hideLoading();
      UI.toast(err.message, "error");
    }
  }

  function bindControls() {
    const q = document.getElementById("search-input");
    const category = document.getElementById("category-filter");
    const urgency = document.getElementById("urgency-filter");
    if (q) q.addEventListener("input", UI.debounce(() => { state.page = 1; loadPending(1); }, 350));
    if (category) category.addEventListener("change", () => { state.page = 1; loadPending(1); });
    if (urgency) urgency.addEventListener("change", () => { state.page = 1; loadPending(1); });
  }

  function setText(id, value) {
    const el = document.getElementById(id);
    if (el) el.textContent = value;
  }

  return { init };
})();
