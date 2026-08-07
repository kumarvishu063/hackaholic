/**
 * Citizen dashboard.
 *
 * - Overview statistics (from /api/analytics/)
 * - Complaint submission with microphone recording (MediaRecorder),
 *   photo capture (MediaDevices + canvas) or upload, and GPS geolocation
 *   with reverse geocoding.
 * - My complaints list with search, status filter and pagination.
 */
document.addEventListener("DOMContentLoaded", () => {
  UI.bindModalClose();
  Citizen.init();
});

const Citizen = (() => {
  const state = {
    page: 1,
    audioBlob: null,
    audioExt: "webm",
    photoBlob: null,
    photoExt: "jpg",
    recording: false,
    mediaRecorder: null,
    chunks: [],
    stream: null,
    timerInterval: null,
    seconds: 0,
    cameraStream: null,
  };

  // ------------------------------------------------------------- bootstrap
  function init() {
    loadStats();
    loadComplaints(1);
    bindSubmitForm();
    bindRecording();
    bindCamera();
    bindPhotoUpload();
    bindLocation();
    bindListControls();
  }

  // ---------------------------------------------------------------- stats
  async function loadStats() {
    try {
      const data = await Api.get("/analytics/");
      const by = data.by_status || {};
      setText("stat-total", data.total || 0);
      setText("stat-pending", by.PENDING_VALIDATION || 0);
      setText("stat-verified", by.VERIFIED || 0);
      setText("stat-resolved", by.RESOLVED || 0);
    } catch (err) {
      console.warn("Stats unavailable:", err.message);
    }
  }

  // --------------------------------------------------------- complaint list
  async function loadComplaints(page = 1) {
    const q = document.getElementById("search-input").value.trim();
    const status = document.getElementById("status-filter").value;
    const params = new URLSearchParams({ page: String(page) });
    if (q) params.set("q", q);
    if (status) params.set("status", status);

    const listEl = document.getElementById("complaints-list");
    listEl.innerHTML = '<div class="skeleton-card"></div><div class="skeleton-card"></div>';

    try {
      const data = await Api.get("/complaints/?" + params.toString());
      renderList(data.results || []);
      const totalPages = data.total_pages || 1;
      document.getElementById("empty-state").classList.toggle("hidden", (data.results || []).length > 0);
      UI.renderPagination(document.getElementById("pagination"), {
        page, totalPages, total: data.count,
        onPage: (p) => { state.page = p; loadComplaints(p); },
      });
    } catch (err) {
      listEl.innerHTML = "";
      UI.toast(err.message, "error");
    }
  }

  function renderList(items) {
    const listEl = document.getElementById("complaints-list");
    if (!items.length) { listEl.innerHTML = ""; return; }
    listEl.innerHTML = items.map((c) => {
      const thumb = c.photo_url
        ? '<img class="complaint-thumb" src="' + UI.escapeHtml(c.photo_url) + '" alt="Evidence">'
        : '<div class="complaint-no-media"><svg class="icon"><use href="/static/icons.svg#icon-camera"/></svg></div>';
      return (
        '<article class="complaint-item" data-id="' + c.complaint_id + '">' +
          thumb +
          '<div class="complaint-item-main">' +
            '<div class="complaint-item-top">' +
              '<span class="mono-id">' + c.complaint_id + "</span>" +
              '<span class="chip">' + UI.escapeHtml(c.category) + "</span>" +
              '<span class="badge ' + UI.statusClass(c.status) + '">' + UI.statusLabel(c.status) + "</span>" +
              '<span class="urgency-pill ' + UI.urgencyClass(c.urgency_score) + '">' + c.urgency_score + "/10</span>" +
            "</div>" +
            "<p>" + UI.escapeHtml(c.description || c.summary || "(no description)") + "</p>" +
            '<div class="complaint-item-foot">' +
              (c.address ? '<span class="chip"><svg class="icon"><use href="/static/icons.svg#icon-map-pin"/></svg>' + UI.escapeHtml(c.address) + "</span>" : "") +
              '<span class="chip"><svg class="icon"><use href="/static/icons.svg#icon-clock"/></svg>' + UI.timeAgo(c.created_at) + "</span>" +
            "</div>" +
          "</div>" +
        "</article>"
      );
    }).join("");
    listEl.querySelectorAll(".complaint-item").forEach((el) => {
      el.addEventListener("click", () => {
        window.location.href = "/complaint/?id=" + el.dataset.id;
      });
    });
  }

  function bindListControls() {
    const q = document.getElementById("search-input");
    const status = document.getElementById("status-filter");
    if (q) q.addEventListener("input", UI.debounce(() => { state.page = 1; loadComplaints(1); }, 350));
    if (status) status.addEventListener("change", () => { state.page = 1; loadComplaints(1); });
  }

  // -------------------------------------------------------- submit workflow
  function bindSubmitForm() {
    document.getElementById("complaint-form").addEventListener("submit", submitComplaint);
    document.getElementById("result-another").addEventListener("click", () => {
      UI.closeModal("result-modal");
    });
  }

  async function submitComplaint(e) {
    e.preventDefault();
    const category = document.getElementById("category").value;
    const description = document.getElementById("description").value.trim();

    document.querySelectorAll(".field-error").forEach((el) => (el.textContent = ""));
    const categoryField = document.getElementById("category");
    const descriptionField = document.getElementById("description");

    if (!category) {
      categoryField.classList.add("invalid");
      document.querySelector('[data-error-for="category"]').textContent = I18n.t("required_category");
      categoryField.focus();
      return;
    }
    if (!description && !state.audioBlob) {
      descriptionField.classList.add("invalid");
      document.querySelector('[data-error-for="description"]').textContent = I18n.t("required_content");
      descriptionField.focus();
      return;
    }

    const formData = new FormData();
    formData.append("category", category);
    formData.append("description", description);
    formData.append("address", document.getElementById("address").value.trim());
    const lat = document.getElementById("latitude").value;
    const lng = document.getElementById("longitude").value;
    if (lat && lng) { formData.append("latitude", lat); formData.append("longitude", lng); }
    if (state.audioBlob) formData.append("audio", state.audioBlob, "complaint." + state.audioExt);
    if (state.photoBlob) formData.append("photo", state.photoBlob, "evidence." + state.photoExt);

    UI.showLoading(I18n.t("ai_analysing"));
    try {
      const data = await Api.post("/complaints/", formData, true);
      UI.hideLoading();
      document.getElementById("result-id").textContent = data.complaint_id;
      document.getElementById("result-pin").textContent = data.complaint_pin;
      document.getElementById("result-hash").textContent = data.sha256_hash;
      document.getElementById("result-track").setAttribute("href", "/complaint/?id=" + data.complaint_id);
      UI.openModal("result-modal");
      resetForm();
      loadStats();
      loadComplaints(1);
    } catch (err) {
      UI.hideLoading();
      UI.toast(err.message, "error");
    }
  }

  function resetForm() {
    document.getElementById("complaint-form").reset();
    state.audioBlob = null; state.photoBlob = null; state.photoExt = "jpg";
    const audio = document.getElementById("audio-preview");
    audio.src = ""; audio.hidden = true;
    document.getElementById("record-timer").classList.add("hidden");
    document.getElementById("record-btn").classList.remove("recording");
    const preview = document.getElementById("photo-preview");
    preview.src = ""; preview.classList.add("hidden");
    document.getElementById("photo-name").textContent = "";
    document.getElementById("gps-hint").textContent = "";
    document.getElementById("latitude").value = "";
    document.getElementById("longitude").value = "";
    document.querySelectorAll(".field-error").forEach((el) => (el.textContent = ""));
  }

  // --------------------------------------------------------------- recording
  function bindRecording() {
    const btn = document.getElementById("record-btn");
    btn.addEventListener("click", toggleRecording);
  }

  async function toggleRecording() {
    const btn = document.getElementById("record-btn");
    const timer = document.getElementById("record-timer");
    if (!state.recording) {
      try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        state.stream = stream;
        const recorder = new MediaRecorder(stream);
        state.mediaRecorder = recorder;
        state.chunks = [];
        recorder.ondataavailable = (ev) => { if (ev.data && ev.data.size) state.chunks.push(ev.data); };
        recorder.onstop = handleRecordingStop;
        recorder.start();
        state.recording = true;
        btn.classList.add("recording");
        startTimer();
        UI.toast(I18n.t("recording"), "info");
      } catch (err) {
        UI.toast(I18n.t("recording_unavailable"), "error");
      }
    } else {
      state.recording = false;
      if (state.mediaRecorder) state.mediaRecorder.stop();
      if (state.stream) state.stream.getTracks().forEach((t) => t.stop());
      stopTimer();
      btn.classList.remove("recording");
    }
  }

  async function handleRecordingStop() {
    const blob = new Blob(state.chunks, { type: "audio/webm" });
    state.audioExt = "webm";
    try {
      const wav = await UI.webmToWav(blob);
      if (wav && wav.size > 100) { state.audioBlob = wav; state.audioExt = "wav"; }
      else state.audioBlob = blob;
    } catch {
      state.audioBlob = blob; // Gemini accepts webm too
    }
    const audio = document.getElementById("audio-preview");
    audio.src = URL.createObjectURL(state.audioBlob);
    audio.hidden = false;
    UI.toast(I18n.t("audio_attached"), "success");
  }

  function startTimer() {
    state.seconds = 0;
    state.timerInterval = setInterval(() => {
      state.seconds += 1;
      const m = String(Math.floor(state.seconds / 60)).padStart(2, "0");
      const s = String(state.seconds % 60).padStart(2, "0");
      document.getElementById("record-timer").textContent = m + ":" + s;
      document.getElementById("record-timer").classList.remove("hidden");
    }, 1000);
  }
  function stopTimer() {
    clearInterval(state.timerInterval);
  }

  // ------------------------------------------------------------------ camera
  function bindCamera() {
    document.getElementById("photo-btn").addEventListener("click", async () => {
      try {
        const stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment" }, audio: false });
        state.cameraStream = stream;
        const video = document.getElementById("camera-preview");
        video.srcObject = stream;
        UI.openModal("camera-modal");
      } catch {
        // Fall back to file upload directly.
        document.getElementById("photo-file").click();
      }
    });
    // Always release the camera when the modal is closed (X button or Escape).
    document.querySelectorAll("#camera-modal [data-close-modal]").forEach((btn) => {
      btn.addEventListener("click", stopCamera);
    });
    document.addEventListener("keydown", (ev) => {
      if (ev.key === "Escape" && !document.getElementById("camera-modal").classList.contains("hidden")) {
        stopCamera();
      }
    });

    document.getElementById("camera-shoot").addEventListener("click", () => {
      const video = document.getElementById("camera-preview");
      const canvas = document.getElementById("camera-canvas");
      canvas.width = video.videoWidth || 1280;
      canvas.height = video.videoHeight || 720;
      canvas.getContext("2d").drawImage(video, 0, 0, canvas.width, canvas.height);
      canvas.toBlob((blob) => {
        if (blob) {
          state.photoBlob = blob;
          state.photoExt = "jpg";
          const preview = document.getElementById("photo-preview");
          preview.src = URL.createObjectURL(blob);
          preview.classList.remove("hidden");
          document.getElementById("photo-name").textContent = I18n.t("photo_captured");
          UI.toast(I18n.t("photo_captured"), "success");
        }
      }, "image/jpeg", 0.82);
      stopCamera();
      UI.closeModal("camera-modal");
    });
  }

  function bindPhotoUpload() {
    const fileInput = document.getElementById("photo-file");
    fileInput.addEventListener("change", () => {
      const file = fileInput.files && fileInput.files[0];
      if (!file) return;
      state.photoBlob = file;
      state.photoExt = (file.name.split(".").pop() || "jpg").toLowerCase();
      const preview = document.getElementById("photo-preview");
      preview.src = URL.createObjectURL(file);
      preview.classList.remove("hidden");
      document.getElementById("photo-name").textContent = file.name;
    });
  }

  function stopCamera() {
    if (state.cameraStream) {
      state.cameraStream.getTracks().forEach((t) => t.stop());
      state.cameraStream = null;
    }
    const video = document.getElementById("camera-preview");
    if (video) video.srcObject = null;
  }

  // --------------------------------------------------------------- location
  function bindLocation() {
    document.getElementById("locate-btn").addEventListener("click", detectLocation);
  }

  function detectLocation() {
    const hint = document.getElementById("gps-hint");
    hint.textContent = I18n.t("locating");
    if (!navigator.geolocation) {
      hint.textContent = I18n.t("geolocation_unavailable");
      return;
    }
    navigator.geolocation.getCurrentPosition(
      async (pos) => {
        const { latitude, longitude } = pos.coords;
        document.getElementById("latitude").value = latitude.toFixed(6);
        document.getElementById("longitude").value = longitude.toFixed(6);
        document.getElementById("address").value = latitude.toFixed(4) + ", " + longitude.toFixed(4);
        hint.textContent = I18n.t("location_detected");
        // Best-effort reverse geocoding (OpenStreetMap Nominatim).
        try {
          const res = await fetch(
            "https://nominatim.openstreetmap.org/reverse?format=jsonv2&lat=" + latitude + "&lon=" + longitude,
            { headers: { "Accept": "application/json" } }
          );
          if (res.ok) {
            const geo = await res.json();
            const addr = geo.display_name || geo.address;
            if (addr) {
              document.getElementById("address").value = addr;
              hint.textContent = I18n.t("location_detected");
            }
          }
        } catch {
          hint.textContent = I18n.t("reverse_geo_failed");
        }
      },
      () => { hint.textContent = I18n.t("location_failed"); },
      { enableHighAccuracy: true, timeout: 10000, maximumAge: 60000 }
    );
  }

  // ---------------------------------------------------------------- helpers
  function setText(id, value) {
    const el = document.getElementById(id);
    if (el) el.textContent = value;
  }

  return { init };
})();
