/**
 * Complaint detail page.
 *
 * Renders the complete complaint record — description, AI output, evidence,
 * remarks, integrity artefacts and the lifecycle timeline — and wires up
 * role-aware actions (validator verify/reject, official resolve).
 */
document.addEventListener("DOMContentLoaded", () => {
  UI.bindModalClose();
  Details.init();
});

const Details = (() => {
  let complaint = null;
  let actionType = null; // "verify" | "reject" | "resolve"

  async function init() {
    const id = new URLSearchParams(window.location.search).get("id");
    if (!id) { renderError("Missing complaint id."); return; }
    try {
      complaint = await Api.get("/complaints/" + encodeURIComponent(id) + "/");
      render(complaint);
    } catch (err) {
      renderError(err.message);
    }
    bindActionModal();
  }

  function renderError(message) {
    const root = document.getElementById("detail-root");
    root.innerHTML =
      '<section class="card empty-state">' +
        '<svg class="icon icon-xl"><use href="/static/icons.svg#icon-warning"/></svg>' +
        "<p>" + UI.escapeHtml(message) + "</p>" +
        '<a class="btn btn-primary" href="/dashboard/" style="margin-top:14px">' + I18n.t("dashboard") + "</a>" +
      "</section>";
  }

  function render(c) {
    const esc = UI.escapeHtml;
    const user = Api.getUser() || {};
    const mapLink = c.latitude && c.longitude
      ? '<a class="map-link" target="_blank" rel="noopener" href="https://maps.google.com/?q=' + c.latitude + "," + c.longitude + '">' +
        '<svg class="icon"><use href="/static/icons.svg#icon-map-pin"/></svg>' + esc(c.address || c.latitude + ", " + c.longitude) + "</a>"
      : (c.address ? '<svg class="icon"><use href="/static/icons.svg#icon-map-pin"/></svg> ' + esc(c.address) : "");

    const audioBlock = c.audio_url
      ? '<audio controls preload="none" src="' + esc(c.audio_url) + '"></audio>'
      : '<span class="muted">' + I18n.t("no_audio") + "</span>";

    const photoBlock = c.photo_url
      ? '<img class="evidence-img" style="max-height:280px" src="' + esc(c.photo_url) + '" alt="Photo evidence">'
      : '<span class="muted">' + I18n.t("no_photo") + "</span>";

    const aiSource = c.ai_source === "gemini" ? I18n.t("ai_source_gemini") : I18n.t("ai_source_mock");

    const integrity =
      '<div class="detail-section">' +
        "<h3>" + I18n.t("sha256_hash") + "</h3>" +
        '<span class="hash-text">' + c.sha256_hash + "</span>" +
      "</div>" +
      (c.complaint_pin
        ? '<div class="detail-section"><h3>' + I18n.t("complaint_pin") + "</h3><span class=\"mono-id\">" + c.complaint_pin + "</span></div>"
        : "");

    const actions = buildActions(c, user);

    const root = document.getElementById("detail-root");
    root.innerHTML =
      '<section class="card">' +
        '<div class="detail-head">' +
          "<div>" +
            "<h2>" + I18n.t("complaint_details") + "</h2>" +
            '<div class="complaint-item-top">' +
              '<span class="mono-id">' + c.complaint_id + "</span>" +
              '<span class="chip">' + esc(c.category) + "</span>" +
              '<span class="badge ' + UI.statusClass(c.status) + '">' + UI.statusLabel(c.status) + "</span>" +
              '<span class="urgency-pill ' + UI.urgencyClass(c.urgency_score) + '">' + c.urgency_score + "/10</span>" +
            "</div>" +
          "</div>" +
          '<div class="complaint-item-top">' +
            '<span class="chip">' + I18n.t("submitted_by") + " " + esc(c.citizen_name || "—") + "</span>" +
            '<span class="chip"><svg class="icon"><use href="/static/icons.svg#icon-clock"/></svg>' + UI.formatDate(c.created_at) + "</span>" +
          "</div>" +
        "</div>" +
        actions +
      "</section>" +

      '<div class="detail-grid">' +
        "<div>" +
          '<section class="card">' +
            (c.description
              ? '<div class="detail-section"><h3>' + I18n.t("description") + "</h3><p>" + esc(c.description) + "</p></div>"
              : "") +
            '<div class="ai-box">' +
              '<span class="ai-tag"><svg class="icon"><use href="/static/icons.svg#icon-spark"/></svg>' +
                I18n.t("summary") + " · " + esc(aiSource) + "</span>" +
              "<p>" + esc(c.summary || "—") + "</p>" +
            "</div>" +
            '<div class="detail-section"><h3>' + I18n.t("transcript") + "</h3><p>" + esc(c.transcript || "—") + "</p></div>" +
            '<div class="detail-section">' +
              "<h3>" + I18n.t("evidence") + "</h3>" +
              "<p><strong>" + I18n.t("audio_recording") + "</strong><br>" + audioBlock + "</p>" +
              "<p><strong>" + I18n.t("photo_evidence") + "</strong><br>" + photoBlock + "</p>" +
              "<p>" + mapLink + "</p>" +
            "</div>" +
          "</section>" +

          '<section class="card">' +
            '<div class="detail-section">' +
              "<h3>" + I18n.t("remarks") + "</h3>" +
              "<p><strong>" + I18n.t("role_validator") + ":</strong> " + esc(c.validator_remarks || "—") + "</p>" +
              "<p><strong>" + I18n.t("role_official") + ":</strong> " + esc(c.official_remarks || "—") + "</p>" +
            "</div>" +
            integrity +
          "</section>" +
        "</div>" +

        '<section class="card">' +
          '<div class="detail-section"><h3>' + I18n.t("timeline") + "</h3>" + timelineHTML(c) + "</div>" +
        "</section>" +
      "</div>";
  }

  function timelineHTML(c) {
    const order = ["SUBMITTED", "VERIFIED", "REJECTED", "RESOLVED"];
    const currentIndex = order.indexOf(c.status);
    if (!c.timeline || !c.timeline.length) return '<p class="muted">—</p>';
    return (
      '<div class="timeline">' +
      c.timeline.map((entry) => {
        const idx = order.indexOf(entry.action);
        const cls = idx === currentIndex ? "current" : (idx !== -1 && idx < currentIndex ? "done" : "");
        return (
          '<div class="timeline-item ' + cls + '">' +
            '<span class="timeline-dot"></span>' +
            '<div class="timeline-action">' + UI.escapeHtml(UI.statusLabel(entry.action === "SUBMITTED" ? "PENDING_VALIDATION" : entry.action)) +
              ' <span class="chip">' + UI.formatDate(entry.timestamp) + "</span></div>" +
            (entry.actor_name ? '<div class="timeline-actor">' + UI.escapeHtml(entry.actor_name) + " (" + UI.escapeHtml(entry.actor_role) + ")</div>" : "") +
            (entry.remarks ? '<div class="timeline-remarks">' + UI.escapeHtml(entry.remarks) + "</div>" : "") +
          "</div>"
        );
      }).join("") +
      "</div>"
    );
  }

  function buildActions(c, user) {
    if (!user || !user.role) return "";
    let html = "";
    if (user.role === "validator" && c.status === "PENDING_VALIDATION") {
      html =
        '<div class="review-actions" style="border-top:none;border-radius:10px">' +
          '<span class="muted" style="flex:1">' + I18n.t("add_remarks") + "</span>" +
          '<button class="btn btn-danger-ghost" id="act-reject">' + I18n.t("reject") + "</button>" +
          '<button class="btn btn-primary" id="act-verify">' + I18n.t("verify") + "</button>" +
        "</div>";
    } else if (user.role === "official" && c.status === "VERIFIED") {
      html =
        '<div class="review-actions" style="border-top:none;border-radius:10px">' +
          '<span class="muted" style="flex:1">' + I18n.t("mark_resolved") + "</span>" +
          '<button class="btn btn-primary" id="act-resolve">' + I18n.t("mark_resolved") + "</button>" +
        "</div>";
    }
    return html;
  }

  // ---------------------------------------------------------------- actions
  function bindActionModal() {
    const verifyBtn = document.getElementById("act-verify");
    const rejectBtn = document.getElementById("act-reject");
    const resolveBtn = document.getElementById("act-resolve");
    const confirmBtn = document.getElementById("action-confirm");

    if (verifyBtn) verifyBtn.addEventListener("click", () => openAction("verify"));
    if (rejectBtn) rejectBtn.addEventListener("click", () => openAction("reject"));
    if (resolveBtn) resolveBtn.addEventListener("click", () => openAction("resolve"));
    if (confirmBtn) confirmBtn.addEventListener("click", confirmAction);
  }

  function openAction(type) {
    actionType = type;
    const title = document.getElementById("action-modal-title");
    const confirmBtn = document.getElementById("action-confirm");
    if (type === "verify") { title.textContent = I18n.t("verify"); confirmBtn.textContent = I18n.t("verify"); }
    if (type === "reject") { title.textContent = I18n.t("reject"); confirmBtn.textContent = I18n.t("reject"); }
    if (type === "resolve") { title.textContent = I18n.t("mark_resolved"); confirmBtn.textContent = I18n.t("mark_resolved"); }
    document.getElementById("action-remarks").value = "";
    UI.openModal("action-modal");
  }

  async function confirmAction() {
    if (!actionType || !complaint) return;
    const remarks = document.getElementById("action-remarks").value.trim();
    UI.showLoading();
    try {
      if (actionType === "resolve") {
        await Api.post("/complaints/" + complaint.complaint_id + "/resolve/", { remarks });
      } else {
        await Api.post("/complaints/" + complaint.complaint_id + "/validate/", { action: actionType, remarks });
      }
      UI.hideLoading();
      UI.closeModal("action-modal");
      UI.toast(
        actionType === "verify" ? I18n.t("verify_success") :
        actionType === "reject" ? I18n.t("reject_success") : I18n.t("resolve_success"),
        "success"
      );
      setTimeout(() => window.location.reload(), 600);
    } catch (err) {
      UI.hideLoading();
      UI.toast(err.message, "error");
    }
  }

  return { init };
})();
