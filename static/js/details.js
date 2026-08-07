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
      loadFeedback(complaint);
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

        '<div class="detail-aside">' +
          '<section class="card">' +
            '<div class="detail-section"><h3>' + I18n.t("timeline") + "</h3>" + timelineHTML(c) + "</div>" +
          "</section>" +
          feedbackCardSlot(c, user) +
        "</div>" +
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

  // ============================================================ citizen feedback
  // The Citizen Feedback card renders below the timeline, only for the
  // complaint owner. It loads asynchronously so it never blocks the page.
  let feedbackRating = 0;

  function feedbackCardSlot(c, user) {
    if (!user || user.role !== "citizen") return "";
    return (
      '<section class="card" id="feedback-slot">' +
        '<div class="skeleton-card feedback-skeleton"></div>' +
      "</section>"
    );
  }

  function feedbackCardInner(content) {
    return (
      '<div class="detail-section">' +
        "<h3>" + I18n.t("citizen_feedback") + "</h3>" +
        content +
      "</div>"
    );
  }

  function feedbackEmptyHTML(status) {
    if (status === "RESOLVED") return feedbackFormHTML();
    const msg = status === "VERIFIED"
      ? I18n.t("feedback_verified_msg")
      : I18n.t("feedback_pending_msg");
    return feedbackCardInner(
      '<div class="feedback-note">' +
        '<svg class="icon icon-accent"><use href="/static/icons.svg#icon-warning"/></svg>' +
        "<p>" + UI.escapeHtml(msg) + "</p>" +
      "</div>"
    );
  }

  function feedbackFormHTML() {
    const stars = [1, 2, 3, 4, 5].map(function (n) {
      return '<button type="button" class="star-btn" data-rating="' + n + '" aria-label="' + n + ' star">★</button>';
    }).join("");
    const satisfactionOptions = ["Excellent", "Good", "Average", "Poor", "Very Poor"]
      .map(function (v) { return '<option value="' + v + '">' + v + "</option>"; })
      .join("");
    return feedbackCardInner(
      '<div class="field fb-field">' +
        '<label>' + I18n.t("feedback_overall_rating") + ' <span class="req">*</span></label>' +
        '<div class="star-input" data-rating="0">' + stars + "</div>" +
        '<p class="field-error hidden" id="fb-rating-err">' + I18n.t("feedback_rating_required") + "</p>" +
      "</div>" +
      '<div class="field fb-field">' +
        '<label>' + I18n.t("feedback_satisfaction") + "</label>" +
        '<select id="fb-satisfaction">' + satisfactionOptions + "</select>" +
      "</div>" +
      '<div class="field fb-field">' +
        '<label>' + I18n.t("feedback_comment") + ' <span class="req">*</span></label>' +
        '<textarea id="fb-comment" rows="4" maxlength="500" placeholder="' + UI.escapeHtml(I18n.t("description_placeholder")) + '"></textarea>' +
        '<p class="hint"><span id="fb-comment-count">0</span>/500 ' + I18n.t("feedback_char_hint") + "</p>" +
        '<p class="field-error hidden" id="fb-comment-err">' + I18n.t("feedback_comment_required") + "</p>" +
      "</div>" +
      feedbackQuestionHTML("fb-resolved", I18n.t("feedback_question_resolved")) +
      feedbackQuestionHTML("fb-again", I18n.t("feedback_question_again")) +
      '<div class="form-actions">' +
        '<button type="button" class="btn btn-primary" id="fb-submit">' + I18n.t("feedback_submit") + "</button>" +
        '<button type="button" class="btn btn-ghost" id="fb-reset">' + I18n.t("feedback_reset") + "</button>" +
      "</div>"
    );
  }

  function feedbackQuestionHTML(name, label) {
    return (
      '<div class="field fb-field">' +
        "<label>" + label + "</label>" +
        '<div class="fb-questions">' +
          '<label class="fb-radio"><input type="radio" name="' + name + '" value="yes"><span>' + I18n.t("yes") + "</span></label>" +
          '<label class="fb-radio"><input type="radio" name="' + name + '" value="no"><span>' + I18n.t("no") + "</span></label>" +
        "</div>" +
      "</div>"
    );
  }

  function feedbackSubmittedHTML(fb) {
    const stars = [1, 2, 3, 4, 5].map(function (n) {
      return '<span class="star-read' + (n <= fb.rating ? " on" : "") + '">★</span>';
    }).join("");
    return feedbackCardInner(
      '<div class="feedback-success">' +
        '<svg class="icon icon-success"><use href="/static/icons.svg#icon-check-circle"/></svg>' +
        "<span>" + I18n.t("feedback_submitted") + "</span>" +
      "</div>" +
      '<div class="fb-readonly">' +
        '<div class="fb-detail"><span class="muted">' + I18n.t("feedback_overall_rating") + ':</span><span class="fb-stars-read">' + stars + "</span></div>" +
        '<div class="fb-detail"><span class="muted">' + I18n.t("feedback_satisfaction") + ':</span> ' + UI.escapeHtml(fb.satisfaction) + "</div>" +
        '<div class="fb-detail"><span class="muted">' + I18n.t("feedback_question_resolved") + ':</span> ' + (fb.issue_resolved ? I18n.t("yes") : I18n.t("no")) + "</div>" +
        '<div class="fb-detail"><span class="muted">' + I18n.t("feedback_question_again") + ':</span> ' + (fb.use_again ? I18n.t("yes") : I18n.t("no")) + "</div>" +
        '<div class="fb-detail"><span class="muted">' + I18n.t("feedback_submitted_on") + ':</span> ' + UI.formatDate(fb.created_at) + "</div>" +
        '<div class="fb-comment"><strong>' + I18n.t("feedback_comment") + "</strong><p>" + UI.escapeHtml(fb.comment) + "</p></div>" +
      "</div>"
    );
  }

  async function loadFeedback(c) {
    const slot = document.getElementById("feedback-slot");
    if (!slot) return;
    let fb = null;
    try {
      const data = await Api.get("/feedback/" + encodeURIComponent(c.complaint_id) + "/");
      fb = data && data.feedback ? data.feedback : null;
    } catch (_e) {
      fb = null; // can't confirm a submission — the POST guard prevents duplicates
    }
    slot.innerHTML = fb ? feedbackSubmittedHTML(fb) : feedbackEmptyHTML(c.status);
    if (!fb) bindFeedbackForm(c.complaint_id);
  }

  function bindFeedbackForm(complaintId) {
    const slot = document.getElementById("feedback-slot");
    if (!slot) return;
    const starInput = slot.querySelector(".star-input");
    const stars = slot.querySelectorAll(".star-btn");
    const commentInput = document.getElementById("fb-comment");
    const submitBtn = document.getElementById("fb-submit");
    const resetBtn = document.getElementById("fb-reset");

    if (resetBtn) resetBtn.addEventListener("click", resetFeedbackForm);

    if (starInput && stars.length) {
      stars.forEach(function (btn) {
        btn.addEventListener("click", function () {
          const rating = Number(btn.dataset.rating);
          feedbackRating = rating;
          starInput.setAttribute("data-rating", String(rating));
          stars.forEach(function (s) {
            s.classList.toggle("active", Number(s.dataset.rating) <= rating);
          });
          const err = document.getElementById("fb-rating-err");
          if (err) err.classList.add("hidden");
        });
      });
    }

    if (commentInput) {
      commentInput.addEventListener("input", function () {
        const count = document.getElementById("fb-comment-count");
        if (count) count.textContent = String(commentInput.value.length);
        const err = document.getElementById("fb-comment-err");
        if (err) err.classList.add("hidden");
      });
    }

    if (submitBtn) submitBtn.addEventListener("click", function () { submitFeedback(complaintId); });
  }

  function resetFeedbackForm() {
    const slot = document.getElementById("feedback-slot");
    if (!slot) return;
    feedbackRating = 0;
    const starInput = slot.querySelector(".star-input");
    if (starInput) starInput.setAttribute("data-rating", "0");
    slot.querySelectorAll(".star-btn").forEach(function (s) { s.classList.remove("active"); });
    const comment = document.getElementById("fb-comment");
    if (comment) comment.value = "";
    const count = document.getElementById("fb-comment-count");
    if (count) count.textContent = "0";
    slot.querySelectorAll('input[type="radio"]').forEach(function (r) { r.checked = false; });
    slot.querySelectorAll(".field-error").forEach(function (e) { e.classList.add("hidden"); });
  }

  async function submitFeedback(complaintId) {
    const slot = document.getElementById("feedback-slot");
    if (!slot) return;
    const commentInput = document.getElementById("fb-comment");
    const comment = commentInput ? commentInput.value.trim() : "";
    let valid = true;

    const ratingErr = document.getElementById("fb-rating-err");
    if (!feedbackRating) { if (ratingErr) ratingErr.classList.remove("hidden"); valid = false; }
    const commentErr = document.getElementById("fb-comment-err");
    if (comment.length < 20) { if (commentErr) commentErr.classList.remove("hidden"); valid = false; }
    if (!valid) return;

    const satisfactionEl = document.getElementById("fb-satisfaction");
    const resolvedEl = slot.querySelector('input[name="fb-resolved"]:checked');
    const againEl = slot.querySelector('input[name="fb-again"]:checked');

    const payload = {
      complaint_id: complaintId,
      rating: feedbackRating,
      satisfaction: satisfactionEl ? satisfactionEl.value : "Good",
      comment: comment,
      issue_resolved: resolvedEl ? resolvedEl.value === "yes" : false,
      use_again: againEl ? againEl.value === "yes" : false,
    };

    const submitBtn = document.getElementById("fb-submit");
    if (submitBtn) { submitBtn.disabled = true; submitBtn.textContent = I18n.t("loading") + "…"; }
    try {
      const fb = await Api.post("/feedback/", payload);
      slot.innerHTML = feedbackSubmittedHTML(fb);
      UI.toast(I18n.t("feedback_submitted"), "success");
    } catch (err) {
      UI.toast(err.message, "error");
      if (submitBtn) { submitBtn.disabled = false; submitBtn.textContent = I18n.t("feedback_submit"); }
    }
  }

  return { init };
})();
