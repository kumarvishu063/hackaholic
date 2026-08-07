/**
 * Login & registration forms.
 *
 * Registration branches by role:
 *   • Citizen         → name/email/username/password → instant login.
 *   • Validator/Official → application form + document uploads + 5-10 webcam
 *     face frames → submitted for Admin approval (no login until approved).
 *
 * Login is a two-step flow for approved staff:
 *   1. identifier + password   → face challenge token
 *   2. live webcam + liveness  → verified → dashboard
 * Citizens and Super Admins skip step 2.
 */
document.addEventListener("DOMContentLoaded", () => {
  const loginForm = document.getElementById("login-form");
  if (loginForm) loginForm.addEventListener("submit", handleLogin);

  const registerForm = document.getElementById("register-form");
  if (registerForm) registerForm.addEventListener("submit", handleRegister);

  const roleSelect = document.getElementById("role");
  if (roleSelect) roleSelect.addEventListener("change", toggleRegisterMode);

  // Segmented role control (register page).
  document.querySelectorAll("[data-seg]").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll("[data-seg]").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      if (roleSelect) roleSelect.value = btn.dataset.seg;
      toggleRegisterMode();
    });
  });

  // Show the chosen file name next to each upload field.
  document.querySelectorAll("input[type=file][id]").forEach((input) => {
    input.addEventListener("change", () => {
      const nameEl = document.getElementById(input.id + "-name");
      if (nameEl && input.files && input.files[0]) nameEl.textContent = input.files[0].name;
    });
  });

  bindFacePanel();
});

function redirectAfterLogin(user) {
  window.location.href = Common.dashboardPath(user.role);
}

/** The currently visible registration fieldset (citizen or staff). */
function activeScope() {
  return document.querySelector("#citizen-fields:not(.hidden)")
    || document.querySelector("#staff-fields:not(.hidden)")
    || document;
}

function showFieldErrors(data, scope) {
  const root = scope || document;
  root.querySelectorAll(".field-error").forEach((el) => (el.textContent = ""));
  root.querySelectorAll("input.invalid, select.invalid").forEach((el) => el.classList.remove("invalid"));
  if (!data || typeof data !== "object") return;
  Object.keys(data).forEach((key) => {
    const errEl = root.querySelector('[data-error-for="' + key + '"]');
    const input = root.querySelector('[name="' + key + '"]');
    const message = Array.isArray(data[key]) ? data[key].join(", ") : String(data[key]);
    if (errEl) errEl.textContent = message;
    if (input) input.classList.add("invalid");
  });
}

function clearFieldErrors(scope) {
  const root = scope || document;
  root.querySelectorAll(".field-error").forEach((el) => (el.textContent = ""));
}

/** Read a field value from within a specific scope. */
function val(id, scope) {
  const el = (scope || document).querySelector("#" + id);
  return el ? el.value.trim() : "";
}

// ===========================================================================
// REGISTRATION
// ===========================================================================
function toggleRegisterMode() {
  const role = document.getElementById("role").value;
  const citizenSection = document.getElementById("citizen-fields");
  const staffSection = document.getElementById("staff-fields");
  if (citizenSection) citizenSection.classList.toggle("hidden", role !== "citizen");
  if (staffSection) staffSection.classList.toggle("hidden", role === "citizen");
  const staffToggle = document.getElementById("staff-toggle");
  if (staffToggle) staffToggle.checked = role !== "citizen";
}

async function handleRegister(e) {
  e.preventDefault();
  const role = document.getElementById("role").value;

  if (role === "citizen") return submitCitizenRegistration();
  return submitStaffApplication(role);
}

async function submitCitizenRegistration() {
  const btn = document.getElementById("register-btn");
  const scope = document.getElementById("citizen-fields");
  const fullName = val("full_name", scope);
  const email = val("email", scope);
  const username = val("username", scope);
  const phone = val("phone", scope);
  const password = val("password", document);
  const confirmPassword = val("confirm_password", document);

  clearFieldErrors(scope);
  const errors = {};
  if (fullName.length < 2) errors.full_name = "Full name must be at least 2 characters.";
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) errors.email = "Enter a valid email address.";
  if (password.length < 8) errors.password = "Password must be at least 8 characters.";
  if (password !== confirmPassword) errors.confirm_password = "Passwords do not match.";
  if (Object.keys(errors).length) return showFieldErrors(errors, scope);

  btn.disabled = true;
  UI.showLoading();
  try {
    const data = await Api.register({
      full_name: fullName, email, username, phone, role: "citizen",
      password, confirm_password: confirmPassword,
    });
    const user = Api.saveSession(data);
    UI.hideLoading();
    UI.toast("Registration successful!", "success");
    redirectAfterLogin(user);
  } catch (err) {
    UI.hideLoading();
    btn.disabled = false;
    showFieldErrors(err.data || {}, scope);
    UI.toast(err.message, "error");
  }
}

async function submitStaffApplication(role) {
  const btn = document.getElementById("register-btn");
  const scope = document.getElementById("staff-fields");
  const values = {
    full_name: val("full_name", scope), email: val("email", scope), username: val("username", scope),
    phone: val("phone", scope), department: val("department", scope),
    office_name: val("office_name", scope),
    password: val("password", document), confirm_password: val("confirm_password", document),
  };

  clearFieldErrors(scope);
  const errors = {};
  if ((values.full_name || "").length < 2) errors.full_name = "Full name must be at least 2 characters.";
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(values.email)) errors.email = "Enter a valid email address.";
  if (!values.department) errors.department = "Department is required.";
  if (!values.office_name) errors.office_name = "Office name is required.";
  if ((values.password || "").length < 8) errors.password = "Password must be at least 8 characters.";
  if (values.password !== values.confirm_password) errors.confirm_password = "Passwords do not match.";

  const docEls = ["government_id_document", "employee_card", "profile_photo"];
  docEls.forEach((name) => {
    const file = document.getElementById(name);
    if (!file || !file.files || !file.files[0]) errors[name] = "This document is required.";
  });

  const frames = FaceCapture.getFrames();
  if (frames.length < 5) errors.face = "Capture at least 5 face images with your webcam.";

  if (Object.keys(errors).length) return showFieldErrors(errors, scope);

  // Build multipart payload.
  const formData = new FormData();
  Object.entries(values).forEach(([k, v]) => { if (v !== undefined && v !== null) formData.append(k, v); });
  formData.append("role", role);
  docEls.forEach((name) => {
    const file = document.getElementById(name);
    if (file && file.files && file.files[0]) formData.append(name, file.files[0]);
  });
  frames.forEach((dataUri, i) => formData.append("face_images", FaceAuth.dataUriToBlob(dataUri), "face_" + (i + 1) + ".jpg"));

  btn.disabled = true;
  UI.showLoading(I18n.t("submitting_application"));
  try {
    const data = await Api.register(formData, true);
    UI.hideLoading();
    showApplicationPending(data);
  } catch (err) {
    UI.hideLoading();
    btn.disabled = false;
    showFieldErrors(err.data || {}, scope);
    UI.toast(err.message, "error");
  }
}

function showApplicationPending(data) {
  const modal = document.getElementById("result-modal");
  if (!modal) {
    UI.toast(data.message || "Application submitted.", "success");
    return;
  }
  document.getElementById("result-application-id").textContent = data.application_id || "—";
  document.getElementById("result-message").textContent =
    data.message || "Your application has been submitted successfully. Please wait for Admin verification.";
  UI.openModal("result-modal");
  const form = document.getElementById("register-form");
  if (form) form.reset();
  FaceCapture.reset();
}

// ===========================================================================
// LOGIN — password step then (for staff) face step
// ===========================================================================
const faceState = { token: null, faceRegistered: true };

async function handleLogin(e) {
  e.preventDefault();
  const identifier = document.getElementById("identifier").value.trim();
  const password = document.getElementById("password").value;

  // Kick off the face-api model download in the background while the password
  // is being checked — by the time the face panel appears the models are warm.
  if (typeof FaceAuth.ensureLoaded === "function") FaceAuth.ensureLoaded();

  clearFieldErrors();
  if (!identifier || !password) {
    if (!identifier) showFieldErrors({ identifier: "Email or username is required." });
    if (!password) showFieldErrors({ password: "Password is required." });
    return;
  }

  const btn = document.getElementById("login-btn");
  btn.disabled = true;
  UI.showLoading();
  try {
    const data = await Api.login(identifier, password);
    UI.hideLoading();
    btn.disabled = false;

    if (data.requires_face) {
      faceState.token = data.face_token;
      faceState.faceRegistered = Boolean(data.face_registered);
      showFaceStep();
      return;
    }
    const user = Api.saveSession(data);
    UI.toast(I18n.t("welcome_back") + ", " + user.full_name + "!", "success");
    redirectAfterLogin(user);
  } catch (err) {
    UI.hideLoading();
    btn.disabled = false;
    showFieldErrors(err.data || {});
    UI.toast(err.message, "error");
  }
}

// --------------------------------------------------------------------------
// Face step
// --------------------------------------------------------------------------
function bindFacePanel() {
  const panel = document.getElementById("face-panel");
  if (!panel) return;

  const startBtn = document.getElementById("face-start-btn");
  if (startBtn) startBtn.addEventListener("click", startFaceFlow);

  const backBtn = document.getElementById("face-back-btn");
  if (backBtn) backBtn.addEventListener("click", () => {
    FaceAuth.stop();
    FaceCapture.reset();
    hideFaceStep();
  });

  const cancelBtn = document.getElementById("face-cancel-btn");
  if (cancelBtn) cancelBtn.addEventListener("click", () => {
    FaceAuth.stop();
    FaceCapture.reset();
    hideFaceStep();
  });

  // Degraded-mode manual acknowledgements.
  document.querySelectorAll("[data-ack]").forEach((btn) => {
    btn.addEventListener("click", () => {
      if (typeof FaceAuth._degradedAck === "function") FaceAuth._degradedAck(btn.dataset.ack);
    });
  });
}

function showFaceStep() {
  document.getElementById("face-panel").classList.remove("hidden");
  const formCard = document.getElementById("face-panel");
  const status = document.getElementById("face-status");
  const challenge = document.getElementById("face-challenge");
  const startBtn = document.getElementById("face-start-btn");
  const degraded = document.getElementById("face-degraded-actions");

  if (!faceState.faceRegistered) {
    // User must (re)register a face before verifying.
    if (status) status.textContent = I18n.t("face_need_register");
    if (startBtn) startBtn.textContent = I18n.t("face_register_now");
    startBtn.classList.remove("hidden");
    faceState.mode = "register";
  } else {
    if (status) status.textContent = I18n.t("face_verify_prompt");
    // Verify is fully automatic — no manual capture/start button needed.
    if (startBtn) startBtn.classList.add("hidden");
    faceState.mode = "verify";
  }
  if (challenge) challenge.textContent = "";
  if (degraded) degraded.classList.add("hidden");
  setFaceStep(1);
  document.getElementById("face-video").classList.add("hidden");
  document.getElementById("credentials-card").classList.add("hidden");
  formCard.scrollIntoView({ behavior: "smooth", block: "center" });

  // Show the webcam immediately after the password is verified — no click.
  if (faceState.mode === "verify") {
    setTimeout(startFaceFlow, 80);
  }
}

/** Highlight progress steps 1 (Detecting) / 2 (Verifying) / 3 (Success). */
function setFaceStep(n) {
  const steps = document.querySelectorAll("#face-progress .face-step");
  steps.forEach((el, i) => {
    const idx = i + 1;
    el.classList.toggle("active", idx === n);
    el.classList.toggle("done", idx < n);
    el.classList.toggle("success", idx === 3 && n === 3);
  });
}

function hideFaceStep() {
  document.getElementById("face-panel").classList.add("hidden");
  document.getElementById("face-video").classList.add("hidden");
  document.getElementById("credentials-card").classList.remove("hidden");
}

function showDegradedActions() {
  const degraded = document.getElementById("face-degraded-actions");
  if (degraded) degraded.classList.remove("hidden");
}

function startFaceFlow() {
  const video = document.getElementById("face-video");
  const status = document.getElementById("face-status");
  const challenge = document.getElementById("face-challenge");
  const startBtn = document.getElementById("face-start-btn");
  const degraded = document.getElementById("face-degraded-actions");
  video.classList.remove("hidden");
  startBtn.disabled = true;
  if (status) status.textContent = I18n.t("face_starting_camera");

  if (faceState.mode === "register") {
    FaceAuth.startRegister({
      video,
      minFrames: 5,
      onDegraded: showDegradedActions,
      onStatus: (msg, ok) => { if (status) { status.textContent = msg; status.classList.toggle("ok", !!ok); } },
      onProgress: (n, target) => { if (status) status.textContent = n + "/" + target + " " + I18n.t("face_frames"); },
      onDone: async (frames) => {
        if (degraded) degraded.classList.add("hidden");
        if (challenge) challenge.textContent = "";
        status.textContent = I18n.t("face_registering");
        try {
          const data = await Api.registerFace({ images: frames }, faceState.token);
          faceState.faceRegistered = true;
          status.textContent = I18n.t("face_registered_ok");
          UI.toast(I18n.t("face_registered_ok"), "success");
          // Proceed straight to verification.
          startBtn.textContent = I18n.t("face_start_verify");
          startBtn.disabled = false;
          faceState.mode = "verify";
        } catch (err) {
          startBtn.disabled = false;
          status.textContent = err.message;
          UI.toast(err.message, "error");
        }
      },
      onError: (err) => { startBtn.disabled = false; status.textContent = err.message; UI.toast(err.message, "error"); },
    });
    return;
  }

  // VERIFY flow — fully automatic, single-frame.
  let verifyRetries = 0;
  FaceAuth.startVerify({
    video,
    onDegraded: showDegradedActions,
    onStatus: (msg, ok) => { if (status) { status.textContent = msg; status.classList.toggle("ok", !!ok); } },
    onChallenge: (msg) => { if (challenge) challenge.textContent = msg; },
    onProgress: (phase) => {
      if (phase === "detecting") setFaceStep(1);
      else if (phase === "verifying") setFaceStep(2);
    },
    onResult: async (payload) => {
      if (degraded) degraded.classList.add("hidden");
      setFaceStep(2);
      status.textContent = I18n.t("face_verifying_identity");
      status.classList.remove("ok");
      try {
        const data = await Api.verifyFace({ face_token: faceState.token, ...payload });
        const user = Api.saveSession(data);
        setFaceStep(3);
        status.textContent = I18n.t("face_login_success");
        status.classList.add("ok");
        UI.hideLoading();
        UI.toast(data.message || "Face authentication successful!", "success");
        FaceAuth.stop();
        setTimeout(() => redirectAfterLogin(user), 650); // let the success step show
      } catch (err) {
        verifyRetries += 1;
        // Retryable: face mismatch (401) or a server-side frame rejection such
        // as "Multiple faces detected" / "Lighting too low" (400 + face field).
        const retryable = err && verifyRetries <= 3 &&
          (err.status === 401 || (err.status === 400 && err.data && err.data.face));
        if (retryable) {
          status.textContent = err.message;
          status.classList.remove("ok");
          UI.toast(err.message, "error");
          setFaceStep(1);
          setTimeout(() => FaceAuth.retryVerify(), 800);
        } else {
          // Terminal failure — stop the camera and offer a manual retry.
          FaceAuth.stop();
          startBtn.classList.remove("hidden");
          startBtn.disabled = false;
          startBtn.textContent = I18n.t("face_start_verify");
          status.textContent = err.message;
          UI.toast(err.message, "error");
        }
      }
    },
    onError: (err) => { startBtn.disabled = false; status.textContent = err.message; UI.toast(err.message, "error"); },
  });
}

// ===========================================================================
// Face capture state for the registration form
// ===========================================================================
const FaceCapture = (() => {
  let frames = [];

  function getFrames() { return frames.slice(); }

  function reset() {
    frames = [];
    FaceAuth.stop();
    const video = document.getElementById("face-video");
    if (video) video.classList.add("hidden");
    const count = document.getElementById("face-count");
    if (count) count.textContent = "0";
    const status = document.getElementById("face-status");
    if (status) status.textContent = "";
  }

  function attach() {
    const startBtn = document.getElementById("face-capture-btn");
    if (!startBtn) return;
    startBtn.addEventListener("click", () => {
      const video = document.getElementById("face-video");
      const status = document.getElementById("face-status");
      const count = document.getElementById("face-count");
      video.classList.remove("hidden");
      startBtn.disabled = true;

      FaceAuth.startRegister({
        video,
        minFrames: 5,
        onStatus: (msg) => { if (status) status.textContent = msg; },
        onProgress: (n) => { frames = frames.length ? frames : []; if (count) count.textContent = n; },
        onDone: (collected) => {
          frames = collected;
          if (count) count.textContent = collected.length;
          if (status) status.textContent = I18n.t("face_capture_complete");
          startBtn.disabled = false;
          startBtn.textContent = I18n.t("face_recapture");
        },
        onError: (err) => { startBtn.disabled = false; if (status) status.textContent = err.message; UI.toast(err.message, "error"); },
      });
    });
  }

  return { getFrames, reset, attach };
})();

// Attach the registration-form face capture once the page has loaded.
document.addEventListener("DOMContentLoaded", () => FaceCapture.attach());
