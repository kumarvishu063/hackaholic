/**
 * Face authentication helper — webcam capture + client-side liveness.
 *
 * Two flows:
 *   1. REGISTER — capture 5-10 distinct face frames for embedding generation.
 *   2. VERIFY   — run liveness challenges (blink + head-turn), capture a burst
 *                 of frames, and produce the payload the server verifies.
 *
 * Face detection & landmarks use face-api.js (loaded lazily from a CDN). When
 * the library cannot load (offline, blocked CDN) the code degrades to a manual
 * flow: the user captures frames and acknowledges the challenges, which keeps
 * the demo usable. The server still enforces its own liveness thresholds and —
 * outside FACE_DEMO_MODE — the real biometric match.
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
  // VERIFY flow — liveness challenges + burst capture
  // ----------------------------------------------------------------------
  /**
   * @param {Object} opts
   *   video      HTMLElement
   *   onStatus   (msg, ok)
   *   onChallenge (text) — show the current challenge to the user
   *   onResult   ({image, liveness_score, blink_count, head_turn_done, samples})
   *   onError    (err)
   */
  async function startVerify(opts) {
    const { video, onStatus, onChallenge, onResult, onError, onDegraded } = opts;
    try {
      await startCamera(video, "user");
      await ensureFaceApi();
      if (apiStatus === "degraded" && onDegraded) onDegraded();
    } catch (err) {
      stopCamera();
      return onError && onError(err);
    }

    let blinks = 0;
    let lastBlinkState = false; // true = eyes currently closed
    let blinkCooldown = 0;
    let samples = 0;
    let bestFrame = null;

    let yawBaseline = 0;
    let yawSamples = 0;
    let headLeftDone = false;
    let headRightDone = false;
    let phase = "blink";        // blink → left → right → done

    // Challenge state machine (degraded mode skips the detection phases).
    let degradedBlinkAck = false;
    let degradedLeftAck = false;
    let degradedRightAck = false;

    const challenge = () => {
      if (api) {
        if (phase === "blink") onChallenge && onChallenge(I18n.t("face_blink_prompt"));
        else if (phase === "left") onChallenge && onChallenge(I18n.t("face_turn_left_prompt"));
        else if (phase === "right") onChallenge && onChallenge(I18n.t("face_turn_right_prompt"));
        else onChallenge && onChallenge(I18n.t("face_look_at_camera"));
      } else {
        if (!degradedBlinkAck) onChallenge && onChallenge(I18n.t("face_blink_manual"));
        else if (!degradedLeftAck) onChallenge && onChallenge(I18n.t("face_turn_left_manual"));
        else if (!degradedRightAck) onChallenge && onChallenge(I18n.t("face_turn_right_manual"));
        else onChallenge && onChallenge(I18n.t("face_look_at_camera"));
      }
    };

    const tick = async () => {
      if (!isCameraActive()) return;
      rafId = requestAnimationFrame(tick);
      samples += 1;

      let box = null;
      let face = null;
      if (api) {
        try { face = await detectWithLandmarks(); } catch (e) { face = null; }
        if (face && face.detection) box = face.detection.box;
        if (face && face.landmarks) {
          // --- blink detection via EAR --------------------------------
          const earL = eyeAspectRatio(face.landmarks, LEFT_EYE);
          const earR = eyeAspectRatio(face.landmarks, RIGHT_EYE);
          const ear = (earL + earR) / 2;
          const closed = ear < 0.21;
          if (closed && !lastBlinkState && now() > blinkCooldown) {
            blinks += 1;
            blinkCooldown = now() + 1200;
          }
          lastBlinkState = closed;

          // --- head-turn detection (yaw) -----------------------------
          const yaw = headYawMetric(face.landmarks);
          if (yawSamples < 12) { yawBaseline += yaw; yawSamples += 1; }
          else {
            const base = yawBaseline / 12;
            if (!headLeftDone && yaw < base - 0.22) headLeftDone = true;
            else if (headLeftDone && !headRightDone && yaw > base + 0.22) headRightDone = true;
          }
        }
      }

      // Keep the most recent frame for the final submission.
      const frame = grabFrame(box);
      if (frame) bestFrame = frame;

      // Phase transitions.
      if (api && face && blinks >= 2 && phase === "blink") phase = "left";
      if (api && face && headLeftDone && phase === "left") phase = "right";
      if (api && face && headRightDone && phase === "right") phase = "done";
      if (api && !face && samples % 90 === 0) {
        onStatus && onStatus(I18n.t("face_look_at_camera"), false);
      }

      const allDone = api
        ? phase === "done"
        : (degradedBlinkAck && degradedLeftAck && degradedRightAck);

      if (allDone && samples >= 6) {
        finish();
        return;
      }
    };

    function finish() {
      const payload = {
        image: bestFrame || grabFrame(),
        liveness_score: computeLivenessScore(),
        blink_count: api ? blinks : (degradedBlinkAck ? 2 : 0),
        head_turn_done: api ? (headLeftDone && headRightDone) : (degradedLeftAck && degradedRightAck),
        samples,
      };
      setTimeout(() => { stopCamera(); onResult(payload); }, 250);
    }

    function computeLivenessScore() {
      const blinkPart = api ? Math.min(blinks, 2) / 2 : (degradedBlinkAck ? 1 : 0);
      const headPart = api
        ? (headLeftDone && headRightDone ? 1 : (headLeftDone ? 0.5 : 0))
        : (degradedLeftAck && degradedRightAck ? 1 : 0);
      const framePart = Math.min(samples, 8) / 8;
      return Math.round((blinkPart * 40) + (headPart * 40) + (framePart * 20));
    }

    loopFn = tick;
    challenge();
    rafId = requestAnimationFrame(tick);

    // Expose manual acknowledgements for the degraded mode.
    FaceAuth._degradedAck = (kind) => {
      if (kind === "blink") degradedBlinkAck = true;
      if (kind === "left") degradedLeftAck = true;
      if (kind === "right") degradedRightAck = true;
      challenge();
    };
  }

  function now() { return Date.now(); }

  return {
    startRegister,
    startVerify,
    stop: stopCamera,
    isActive: isCameraActive,
    ensureLoaded: ensureFaceApi,
    dataUriToBlob,
    isDegraded: () => apiStatus === "degraded",
    status: () => apiStatus,
    READY_EVENT: FACE_READY_EVENT,
  };
})();
