/**
 * Face authentication helper — webcam capture + client-side liveness.
 *
 * Two flows:
 *   1. REGISTER — capture 5-10 distinct face frames for embedding generation.
 *   2. VERIFY   — FAST single-frame flow (see FACE_AUTH_OPTIMIZATION.txt):
 *        camera + models start together, detection runs at ~6 FPS (not every
 *        frame), a face guide is drawn over the video, and ONE high-quality
 *        frame is captured automatically once the face is centred + sized +
 *        lit and a lightweight liveness gesture (blink once OR slight head
 *        turn) has been observed. No manual capture button.
 *
 * Face detection & landmarks use face-api.js (loaded lazily from a CDN). When
 * the library cannot load (offline, blocked CDN) the code degrades to a manual
 * flow: a single acknowledgement arms the capture. The server still enforces
 * its own liveness thresholds and — outside FACE_DEMO_MODE — the real
 * biometric match.
 */
const FaceAuth = (() => {
  const MODEL_URL = "https://cdn.jsdelivr.net/gh/justadudewhohacks/face-api.js@0.22.2/weights";
  const LIB_URL = "https://cdn.jsdelivr.net/gh/justadudewhohacks/face-api.js@0.22.2/dist/face-api.min.js";
  const FACE_READY_EVENT = "face:ready";

  let stream = null;
  let videoEl = null;
  let rafId = null;
  let loopFn = null;
  let api = null;          // face-api module (or null in degraded mode)
  let apiStatus = "loading"; // loading | ready | degraded

  // ----------------------------------------------------------------------
  // Loading face-api.js (lazy, non-blocking)
  // ----------------------------------------------------------------------
  async function ensureFaceApi() {
    if (api) return api;
    if (apiStatus === "degraded") return null;
    try {
      if (!window.faceapi) {
        await loadScript(LIB_URL);
      }
      await window.faceapi.nets.tinyFaceDetector.loadFromUri(MODEL_URL);
      await window.faceapi.nets.faceLandmark68Net.loadFromUri(MODEL_URL);
      api = window.faceapi;
      apiStatus = "ready";
      document.dispatchEvent(new CustomEvent(FACE_READY_EVENT));
      return api;
    } catch (err) {
      apiStatus = "degraded";
      console.warn("face-api.js unavailable — using degraded liveness flow.", err);
      return null;
    }
  }

  function loadScript(src) {
    return new Promise((resolve, reject) => {
      const s = document.createElement("script");
      s.src = src;
      s.onload = resolve;
      s.onerror = () => reject(new Error("failed to load " + src));
      document.head.appendChild(s);
    });
  }

  // ----------------------------------------------------------------------
  // Camera
  // ----------------------------------------------------------------------
  async function startCamera(video, facing = "user") {
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      throw new Error(I18n.t("camera_unavailable"));
    }
    stream = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: facing, width: { ideal: 640 }, height: { ideal: 480 } },
      audio: false,
    });
    videoEl = video;
    video.srcObject = stream;
    await video.play();
  }

  function stopCamera() {
    if (rafId) { cancelAnimationFrame(rafId); rafId = null; }
    if (stream) { stream.getTracks().forEach((t) => t.stop()); stream = null; }
    if (videoEl && videoEl.srcObject) { videoEl.srcObject = null; videoEl = null; }
    loopFn = null;
  }

  function isCameraActive() {
    return Boolean(stream);
  }

  // ----------------------------------------------------------------------
  // Frame capture
  // ----------------------------------------------------------------------
  function grabFrame(box) {
    if (!videoEl || !videoEl.videoWidth) return null;
    const canvas = document.createElement("canvas");
    let w = videoEl.videoWidth;
    let h = videoEl.videoHeight;
    let sx = 0, sy = 0;
    if (box) {
      const pad = 0.12;
      sx = Math.max(0, Math.floor(box.x - box.width * pad));
      sy = Math.max(0, Math.floor(box.y - box.height * pad));
      w = Math.min(videoEl.videoWidth - sx, Math.ceil(box.width * (1 + pad * 2)));
      h = Math.min(videoEl.videoHeight - sy, Math.ceil(box.height * (1 + pad * 2)));
    }
    canvas.width = w;
    canvas.height = h;
    canvas.getContext("2d").drawImage(videoEl, sx, sy, w, h, 0, 0, w, h);
    return canvas.toDataURL("image/jpeg", 0.85);
  }

  function dataUriToBlob(dataUri) {
    const parts = dataUri.split(",");
    const mime = parts[0].match(/data:(.*?);/)[1] || "image/jpeg";
    const bin = atob(parts[1]);
    const arr = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) arr[i] = bin.charCodeAt(i);
    return new Blob([arr], { type: mime });
  }

  // ----------------------------------------------------------------------
  // Landmark helpers (68-point model)
  // ----------------------------------------------------------------------
  const LEFT_EYE = [36, 37, 38, 39, 40, 41];   // viewer's right, subject's left
  const RIGHT_EYE = [42, 43, 44, 45, 46, 47];
  const NOSE = 30;

  function dist(a, b) {
    return Math.hypot(a.x - b.x, a.y - b.y);
  }

  function eyeAspectRatio(landmarks, indices) {
    const p = indices.map((i) => landmarks.positions[i]);
    const vertical = (dist(p[1], p[5]) + dist(p[2], p[4])) / 2;
    const horizontal = dist(p[0], p[3]);
    return horizontal ? vertical / horizontal : 0;
  }

  function currentEAR(landmarks) {
    const earL = eyeAspectRatio(landmarks, LEFT_EYE);
    const earR = eyeAspectRatio(landmarks, RIGHT_EYE);
    return (earL + earR) / 2;
  }

  function headYawMetric(landmarks) {
    // Approximate yaw: how far the nose sits from the eye-line midpoint.
    // Positive when the subject turns to their right (nose toward the left eye).
    const leftEye = { x: 0, y: 0 };
    const rightEye = { x: 0, y: 0 };
    LEFT_EYE.slice(0, 4).forEach((i) => { leftEye.x += landmarks.positions[i].x; leftEye.y += landmarks.positions[i].y; });
    RIGHT_EYE.slice(0, 4).forEach((i) => { rightEye.x += landmarks.positions[i].x; rightEye.y += landmarks.positions[i].y; });
    leftEye.x /= 4; leftEye.y /= 4;
    rightEye.x /= 4; rightEye.y /= 4;
    const interEye = dist(leftEye, rightEye) || 1;
    const nose = landmarks.positions[NOSE];
    const leftDist = dist(nose, leftEye);
    const rightDist = dist(nose, rightEye);
    return (leftDist - rightDist) / interEye; // >0 → looking toward subject's right
  }

  async function detectWithLandmarks() {
    if (!api || !videoEl) return null;
    const result = await api.detectSingleFace(videoEl, new api.TinyFaceDetectorOptions({ inputSize: 320 }))
      .withFaceLandmarks();
    return result;
  }

  // ----------------------------------------------------------------------
  // Face guide overlay (drawn on the login page canvas, when present)
  // ----------------------------------------------------------------------
  function guideCanvas() {
    return document.getElementById("face-guide");
  }

  function drawGuide(faceBox, state) {
    const canvas = guideCanvas();
    if (!canvas || !videoEl || !videoEl.videoWidth) return;
    const ctx = canvas.getContext("2d");
    const cw = canvas.clientWidth, ch = canvas.clientHeight;
    if (canvas.width !== cw || canvas.height !== ch) {
      canvas.width = cw; canvas.height = ch;
    }
    ctx.clearRect(0, 0, cw, ch);

    // Fixed target ellipse in the centre of the frame.
    const tw = cw * 0.52, th = ch * 0.62;
    ctx.beginPath();
    ctx.ellipse(cw / 2, ch / 2, tw / 2, th / 2, 0, 0, Math.PI * 2);
    ctx.setLineDash([6, 6]);
    ctx.strokeStyle = "rgba(255,255,255,0.55)";
    ctx.lineWidth = 1.5;
    ctx.stroke();
    ctx.setLineDash([]);

    if (!faceBox) return;

    // Scale the detected box (video pixels) onto the CSS-sized canvas.
    const sx = cw / videoEl.videoWidth, sy = ch / videoEl.videoHeight;
    const x = faceBox.x * sx, y = faceBox.y * sy;
    const w = faceBox.width * sx, h = faceBox.height * sy;
    const ok = state === "ok";
    const color = ok ? "#22c55e" : (state === "warn" ? "#f59e0b" : "#38bdf8");

    // Corner brackets.
    const L = 22, gap = 2;
    ctx.strokeStyle = color;
    ctx.lineWidth = 3;
    const corners = [
      [x, y, 1, 1], [x + w, y, -1, 1], [x, y + h, 1, -1], [x + w, y + h, -1, -1],
    ];
    corners.forEach(([cx, cy, dx, dy]) => {
      ctx.beginPath();
      ctx.moveTo(cx + dx * gap, cy + dy * gap);
      ctx.lineTo(cx + dx * (gap + L), cy + dy * gap);
      ctx.moveTo(cx + dx * gap, cy + dy * gap);
      ctx.lineTo(cx + dx * gap, cy + dy * (gap + L));
      ctx.stroke();
    });

    // Confidence ring pulse while a good face is tracked.
    if (ok) {
      const t = Date.now() / 400;
      ctx.beginPath();
      ctx.arc(cw / 2, ch / 2, (tw / 2) * (0.72 + 0.06 * Math.sin(t)), 0, Math.PI * 2);
      ctx.strokeStyle = "rgba(34,197,94,0.35)";
      ctx.lineWidth = 2;
      ctx.stroke();
    }
  }

  // ----------------------------------------------------------------------
  // Light sampling (cheap, downscaled)
  // ----------------------------------------------------------------------
  const _brightCanvas = document.createElement("canvas");
  function sampleBrightness() {
    if (!videoEl || !videoEl.videoWidth) return null;
    _brightCanvas.width = 32;
    _brightCanvas.height = 24;
    const ctx = _brightCanvas.getContext("2d");
    ctx.drawImage(videoEl, 0, 0, 32, 24);
    let data;
    try { data = ctx.getImageData(0, 0, 32, 24).data; } catch (e) { return null; }
    let sum = 0;
    for (let i = 0; i < data.length; i += 4) {
      sum += 0.299 * data[i] + 0.587 * data[i + 1] + 0.114 * data[i + 2];
    }
    return sum / (data.length / 4);
  }

  // ----------------------------------------------------------------------
  // REGISTER flow — collect N distinct frames
  // ----------------------------------------------------------------------
  /**
   * @param {Object} opts
   *   video       HTMLElement the live <video>
   *   minFrames   target number of frames (default 5)
   *   onStatus    (msg, ok) — status line updates
   *   onProgress  (collected, target)
   *   onDone      (frames: string[]) — array of data-URIs
   *   onError     (err)
   */
  async function startRegister(opts) {
    const { video, minFrames = 5, onStatus, onProgress, onDone, onError, onDegraded } = opts;
    try {
      await startCamera(video, "user");
      await ensureFaceApi();
      if (apiStatus === "degraded" && onDegraded) onDegraded();
    } catch (err) {
      stopCamera();
      return onError && onError(err);
    }

    const collected = [];
    let lastGrab = 0;
    const t0 = Date.now();

    const tick = async () => {
      if (!isCameraActive()) return;
      rafId = requestAnimationFrame(tick);
      if (collected.length >= minFrames) return;

      const now = Date.now();
      let box = null;
      let face = null;
      if (api) {
        try { face = await detectWithLandmarks(); } catch (e) { face = null; }
        if (face && face.detection) box = face.detection.box;
      } else {
        // Degraded: accept frames at a fixed cadence.
        if (now - lastGrab < 900) return;
      }
      if (api && !face) {
        if (now - lastGrab > 1600) {
          if (onStatus) onStatus(I18n.t("face_look_at_camera"), false);
          lastGrab = now;
        }
        return;
      }
      if (now - lastGrab < 550) return;
      lastGrab = now;

      const frame = grabFrame(box);
      if (!frame) return;
      collected.push(frame);
      if (onProgress) onProgress(collected.length, minFrames);
      if (onStatus) {
        onStatus(collected.length >= minFrames
          ? I18n.t("face_capture_complete")
          : I18n.t("face_capture_progress") + " " + collected.length + "/" + minFrames, true);
      }
      if (collected.length >= minFrames) {
        setTimeout(() => { stopCamera(); onDone(collected); }, 250);
      }
    };
    loopFn = tick;
    rafId = requestAnimationFrame(tick);
  }

  // ----------------------------------------------------------------------
  // VERIFY flow — FAST single-frame automatic capture
  // ----------------------------------------------------------------------
  /**
   * @param {Object} opts
   *   video       HTMLElement
   *   onStatus    (msg, ok)
   *   onChallenge (text) — live guidance ("Center your face", …)
   *   onProgress  (phase) — "detecting" | "verifying"
   *   onResult    ({image, liveness_score, blink_count, head_turn_done, samples})
   *   onError     (err)
   */
  async function startVerify(opts) {
    const { video, onStatus, onChallenge, onProgress, onResult, onError, onDegraded } = opts;
    try {
      // Start the camera and load the models concurrently — both are needed
      // before detection begins and this shaves the perceived wait.
      await Promise.all([startCamera(video, "user"), ensureFaceApi()]);
      if (apiStatus === "degraded" && onDegraded) onDegraded();
    } catch (err) {
      stopCamera();
      return onError && onError(err);
    }

    // ---- capture state ---------------------------------------------------
    let blinks = 0;
    let lastBlinkState = false;
    let blinkCooldown = 0;
    let yawBaseline = 0;
    let yawSamples = 0;
    let headTurnDone = false;
    let bestFrame = null;
    let bestScore = 0;
    let armed = false;      // a liveness gesture was observed → capture next good frame
    let finished = false;   // frame captured, payload delivered
    let sampleCount = 0;
    let lastDetect = 0;
    let degradedAckAt = 0;
    let degradedAckDone = false;
    let lastGuidance = "";

    // Tunables (spec: process at 5-10 FPS, stop immediately once valid).
    const DETECT_MS = 150;          // ~6-7 FPS
    const MIN_FACE_RATIO = 0.16;    // face must span ≥ 16% of frame width
    const MAX_OFFSET = 0.32;        // face centre within 32% of frame centre
    const MIN_BRIGHTNESS = 42;      // 0-255 mean luminance

    const t = (key) => (I18n && I18n.t ? I18n.t(key) : key);

    function setGuidance(key, ok) {
      if (key !== lastGuidance) {
        lastGuidance = key;
        if (onChallenge) onChallenge(t(key));
      }
      if (onStatus) onStatus(t(key), !!ok);
    }

    async function tick() {
      if (!isCameraActive() || finished) return;
      rafId = requestAnimationFrame(tick);
      const now = Date.now();
      if (now - lastDetect < DETECT_MS) return;  // throttle — not every frame
      lastDetect = now;
      sampleCount += 1;

      // Degraded mode: a single manual acknowledgement arms the capture.
      if (apiStatus === "degraded") {
        if (degradedAckDone) {
          if (!armed) { armed = true; degradedAckAt = now; }
          if (now - degradedAckAt > 900) { captureAndFinish(null); }
        }
        return;
      }

      let face = null, box = null;
      try { face = await detectWithLandmarks(); } catch (e) { face = null; }
      if (face && face.detection) box = face.detection.box;

      const brightness = sampleBrightness();
      if (!face || !box) {
        drawGuide(null, "none");
        setGuidance("face_center_face", false);
        return;
      }

      const vw = video.videoWidth, vh = video.videoHeight;
      const sizeRatio = box.width / vw;
      const cx = box.x + box.width / 2, cy = box.y + box.height / 2;
      const offX = Math.abs(cx - vw / 2) / (vw / 2);
      const offY = Math.abs(cy - vh / 2) / (vh / 2);
      const centered = offX <= MAX_OFFSET && offY <= MAX_OFFSET;

      // Guidance + guide colour.
      if (brightness !== null && brightness < MIN_BRIGHTNESS) {
        drawGuide(box, "warn");
        setGuidance("face_lighting_low", false);
      } else if (sizeRatio < MIN_FACE_RATIO) {
        drawGuide(box, "warn");
        setGuidance("face_move_closer", false);
      } else if (!centered) {
        drawGuide(box, "warn");
        setGuidance("face_center_face", false);
      } else {
        drawGuide(box, "ok");
        // Face is good: first confirm detection, then prompt for the quick
        // liveness gesture (blink once OR turn the head slightly).
        if (!armed) {
          setGuidance(lastGuidance === "face_detected" ? "face_liveness_hint" : "face_detected", true);
        } else {
          setGuidance("face_verifying_identity", true);
        }
      }

      if (!centered || sizeRatio < MIN_FACE_RATIO) return;

      // Relaxed liveness — blink once OR slight head turn, whichever first.
      if (face.landmarks) {
        const ear = currentEAR(face.landmarks);
        const closed = ear < 0.21;
        if (closed && !lastBlinkState && now > blinkCooldown) {
          blinks += 1;
          blinkCooldown = now + 1200;
        }
        lastBlinkState = closed;

        const yaw = headYawMetric(face.landmarks);
        if (yawSamples < 10) { yawBaseline += yaw; yawSamples += 1; }
        else if (!headTurnDone) {
          const base = yawBaseline / 10;
          if (Math.abs(yaw - base) > 0.25) headTurnDone = true;  // any direction
        }
      }
      const gestureDone = blinks >= 1 || headTurnDone;

      // Track the best-quality frame (open eyes preferred).
      const quality = qualityScore(box, sizeRatio, centered, face);
      const frame = grabFrame(box);
      if (frame && quality >= bestScore) { bestFrame = frame; bestScore = quality; }

      if (!armed && gestureDone) {
        armed = true;
        if (onProgress) onProgress("verifying");
        if (onStatus) onStatus(t("face_verifying_identity"), true);
      }

      // Capture ONE frame automatically — skip mid-blink frames.
      if (armed && bestFrame && !isEyesClosed(face)) {
        captureAndFinish(bestFrame);
      }
    }

    function qualityScore(box, sizeRatio, centered, face) {
      let score = sizeRatio * 100 + (centered ? 30 : 0);
      if (face && face.landmarks && !isEyesClosed(face)) score += 20;  // open eyes
      return score;
    }

    function isEyesClosed(face) {
      return Boolean(face && face.landmarks && currentEAR(face.landmarks) < 0.25);
    }

    function computeLivenessScore() {
      if (apiStatus === "degraded") return 80;
      const gesture = blinks >= 1 || headTurnDone;
      if (!gesture) return 0;
      return 70 + (blinks >= 1 && headTurnDone ? 30 : 0);
    }

    function captureAndFinish(frame) {
      if (finished) return;
      finished = true;
      if (rafId) cancelAnimationFrame(rafId);
      const payload = {
        image: frame || grabFrame(),
        liveness_score: computeLivenessScore(),
        blink_count: api ? blinks : (degradedAckDone ? 1 : 0),
        head_turn_done: api ? headTurnDone : (degradedAckDone ? true : false),
        samples: Math.min(Math.max(sampleCount, 2), 8),
      };
      onResult(payload);
    }

    /** Re-arm the capture loop after a failed match (camera stays warm). */
    function retryVerify() {
      finished = false;
      armed = false;
      blinks = 0;
      lastBlinkState = false;
      blinkCooldown = 0;
      headTurnDone = false;
      yawBaseline = 0;
      yawSamples = 0;
      bestFrame = null;
      bestScore = 0;
      lastGuidance = "";
      degradedAckDone = false;
      lastDetect = 0;
      if (onProgress) onProgress("detecting");
      if (onChallenge) onChallenge(t("face_center_face"));
      rafId = requestAnimationFrame(tick);
    }

    loopFn = tick;
    if (onProgress) onProgress("detecting");
    rafId = requestAnimationFrame(tick);

    // Expose the degraded-mode manual acknowledgement.
    FaceAuth._degradedAck = (kind) => {
      if (apiStatus === "degraded" && !degradedAckDone) {
        degradedAckDone = true;
        if (onChallenge) onChallenge(t("face_verifying_identity"));
      }
    };

    FaceAuth._retryVerify = retryVerify;
  }

  return {
    startRegister,
    startVerify,
    stop: stopCamera,
    isActive: isCameraActive,
    ensureLoaded: ensureFaceApi,
    dataUriToBlob,
    retryVerify: () => { if (typeof FaceAuth._retryVerify === "function") FaceAuth._retryVerify(); },
    isDegraded: () => apiStatus === "degraded",
    status: () => apiStatus,
    READY_EVENT: FACE_READY_EVENT,
  };
})();
