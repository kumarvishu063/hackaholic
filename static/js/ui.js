/**
 * Shared UI helpers — toasts, modals, loading states, formatting and
 * small DOM utilities used by every page.
 */
const UI = (() => {

  // ---------------------------------------------------------------- toasts
  function toast(message, type = "info", duration = 3800) {
    const container = document.getElementById("toast-container");
    if (!container) return;
    const icons = {
      success: "icon-check-circle",
      error: "icon-x-circle",
      warning: "icon-warning",
      info: "icon-spark",
    };
    const el = document.createElement("div");
    el.className = "toast toast-" + type;
    el.innerHTML =
      '<svg class="icon"><use href="/static/icons.svg#' + (icons[type] || icons.info) + '"/></svg>' +
      "<span></span>";
    el.querySelector("span").textContent = message;
    container.appendChild(el);
    setTimeout(() => {
      el.classList.add("out");
      setTimeout(() => el.remove(), 260);
    }, duration);
  }

  // ---------------------------------------------------------------- loading
  function showLoading(text) {
    const overlay = document.getElementById("loading-overlay");
    if (!overlay) return;
    const label = overlay.querySelector("p");
    if (label && text) label.textContent = text;
    overlay.classList.remove("hidden");
  }
  function hideLoading() {
    const overlay = document.getElementById("loading-overlay");
    if (overlay) overlay.classList.add("hidden");
  }

  // ---------------------------------------------------------------- modals
  function openModal(id) {
    const el = document.getElementById(id);
    if (el) el.classList.remove("hidden");
  }
  function closeModal(id) {
    const el = document.getElementById(id);
    if (el) el.classList.add("hidden");
  }
  function closeAllModals() {
    document.querySelectorAll(".modal").forEach((m) => m.classList.add("hidden"));
  }
  function bindModalClose() {
    document.querySelectorAll("[data-close-modal]").forEach((btn) => {
      btn.addEventListener("click", () => closeAllModals());
    });
  }

  // ---------------------------------------------------------------- format
  function escapeHtml(value) {
    return String(value == null ? "" : value)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }

  function formatDate(iso, withTime = true) {
    if (!iso) return "—";
    const d = new Date(iso);
    if (isNaN(d)) return String(iso);
    const datePart = d.toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" });
    if (!withTime) return datePart;
    const timePart = d.toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", hour12: true });
    return datePart + ", " + timePart;
  }

  function timeAgo(iso) {
    if (!iso) return "";
    const then = new Date(iso).getTime();
    const diff = Date.now() - then;
    const mins = Math.floor(diff / 60000);
    if (mins < 1) return "just now";
    if (mins < 60) return mins + "m ago";
    const hrs = Math.floor(mins / 60);
    if (hrs < 24) return hrs + "h ago";
    const days = Math.floor(hrs / 24);
    if (days < 30) return days + "d ago";
    return formatDate(iso, false);
  }

  function initials(name) {
    return String(name || "?").trim().split(/\s+/).map((w) => w[0]).slice(0, 2).join("").toUpperCase() || "?";
  }

  // ---------------------------------------------------------------- badges
  function statusClass(status) {
    return {
      PENDING_VALIDATION: "badge-pending",
      VERIFIED: "badge-verified",
      RESOLVED: "badge-resolved",
      REJECTED: "badge-rejected",
    }[status] || "badge-info";
  }

  function urgencyClass(score) {
    if (score >= 7) return "urgency-high";
    if (score >= 4) return "urgency-mid";
    return "urgency-low";
  }

  function statusLabel(status) {
    // Translated via the i18n module (falls back to English keys).
    const keys = { PENDING_VALIDATION: "pending", VERIFIED: "verified", RESOLVED: "resolved", REJECTED: "rejected" };
    return keys[status] ? I18n.t(keys[status]) : status;
  }

  // ---------------------------------------------------------------- audio
  // Convert a recorded webm blob into a 16 kHz mono WAV blob so backend
  // transcription (Gemini) receives a broadly-supported format.
  function webmToWav(webmBlob) {
    return new Promise((resolve, reject) => {
      const AudioCtx = window.AudioContext || window.webkitAudioContext;
      const audioCtx = new AudioCtx();
      const reader = new FileReader();
      reader.onerror = () => { audioCtx.close(); reject(reader.error); };
      reader.onload = async () => {
        try {
          const decoded = await audioCtx.decodeAudioData(reader.result);
          const sampleRate = 16000;
          const offline = new OfflineAudioContext(1, Math.ceil(decoded.duration * sampleRate), sampleRate);
          const source = offline.createBufferSource();
          source.buffer = decoded;
          source.connect(offline.destination);
          source.start(0);
          const rendered = await offline.startRendering();
          audioCtx.close();
          resolve(encodeWav(rendered));
        } catch (err) {
          audioCtx.close();
          reject(err);
        }
      };
      reader.readAsArrayBuffer(webmBlob);
    });
  }

  function encodeWav(buffer) {
    const channels = 1;
    const sampleRate = buffer.sampleRate;
    const samples = buffer.getChannelData(0);
    const dataSize = samples.length * 2;
    const bufferOut = new ArrayBuffer(44 + dataSize);
    const view = new DataView(bufferOut);
    const writeString = (offset, str) => {
      for (let i = 0; i < str.length; i++) view.setUint8(offset + i, str.charCodeAt(i));
    };
    writeString(0, "RIFF");
    view.setUint32(4, 36 + dataSize, true);
    writeString(8, "WAVE");
    writeString(12, "fmt ");
    view.setUint32(16, 16, true);
    view.setUint16(20, 1, true);
    view.setUint16(22, channels, true);
    view.setUint32(24, sampleRate, true);
    view.setUint32(28, sampleRate * channels * 2, true);
    view.setUint16(32, channels * 2, true);
    view.setUint16(34, 16, true);
    writeString(36, "data");
    view.setUint32(40, dataSize, true);
    let offset = 44;
    for (let i = 0; i < samples.length; i++) {
      const s = Math.max(-1, Math.min(1, samples[i]));
      view.setInt16(offset, s < 0 ? s * 0x8000 : s * 0x7fff, true);
      offset += 2;
    }
    return new Blob([bufferOut], { type: "audio/wav" });
  }

  // ---------------------------------------------------------------- misc
  function debounce(fn, wait = 350) {
    let timer;
    return function (...args) {
      clearTimeout(timer);
      timer = setTimeout(() => fn.apply(this, args), wait);
    };
  }

  function renderPagination(container, { page, totalPages, total, onPage }) {
    if (!container) return;
    if (totalPages <= 1) { container.innerHTML = ""; return; }
    const prevLabel = I18n.t("previous");
    const nextLabel = I18n.t("next");
    const pageInfo = I18n.t("page_of") + " " + page + " " + I18n.t("of") + " " + totalPages +
      (total != null ? " · " + total : "");
    container.innerHTML =
      '<button class="page-btn" data-page="' + (page - 1) + '" ' + (page <= 1 ? "disabled" : "") + ">" + prevLabel + "</button>" +
      '<span class="page-info">' + pageInfo + "</span>" +
      '<button class="page-btn" data-page="' + (page + 1) + '" ' + (page >= totalPages ? "disabled" : "") + ">" + nextLabel + "</button>";
    container.querySelectorAll("[data-page]").forEach((btn) => {
      btn.addEventListener("click", () => { if (!btn.disabled) onPage(Number(btn.dataset.page)); });
    });
  }

  return {
    toast, showLoading, hideLoading,
    openModal, closeModal, closeAllModals, bindModalClose,
    escapeHtml, formatDate, timeAgo, initials,
    statusClass, urgencyClass, statusLabel,
    debounce, renderPagination,
    webmToWav,
  };
})();
