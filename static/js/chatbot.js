/**
 * JanSetu Assistant — floating AI citizen-support chatbot.
 *
 * - Closed state is a small circular gradient button (bottom-right).
 * - Clicking it opens a glassmorphism chat panel without reloading.
 * - Conversation is preserved for the whole page session: closing the panel
 *   only hides it, it never wipes the messages.
 * - The welcome message is shown once per session (not on every reopen).
 * - Respects the JanSetu language switcher (I18n module).
 * - Auth is optional: Api.post attaches the JWT when present, so a logged-in
 *   citizen gets owner-level complaint status lookups.
 */
document.addEventListener("DOMContentLoaded", () => {
  const Chatbot = (() => {

    // ------------------------------------------------------------ state
    const root = document.getElementById("chatbot-root");
    const toggleBtn = document.getElementById("chatbot-toggle");
    const panel = document.getElementById("chatbot-panel");
    const messagesEl = document.getElementById("chatbot-messages");
    const inputEl = document.getElementById("chatbot-input");
    const sendBtn = document.getElementById("chatbot-send");
    const closeBtn = document.getElementById("chatbot-close");
    const micBtn = document.getElementById("chatbot-mic");
    const vtEl = document.getElementById("chatbot-vt");
    const typingEl = document.getElementById("chatbot-typing");

    let opened = false;
    let greeted = false;          // welcome message shown once this session
    let busy = false;             // a reply is in flight
    let lastSentAt = 0;           // client-side spam guard
    const history = [];           // [{ role, content }] sent to the backend

    const MIN_INTERVAL_MS = 600;

    // ------------------------------------------------------------ voice state
    const SpeechRecognitionCtor = window.SpeechRecognition || window.webkitSpeechRecognition;
    const SR_LANGS = { en: "en-IN", hi: "hi-IN", mr: "mr-IN", kn: "kn-IN", bn: "bn-IN" };
    let recognition = null;       // Web Speech API instance (primary path)
    let listening = false;        // SR active
    let autoSendQueued = false;   // send the final transcript once
    let mediaRecorder = null;     // MediaRecorder fallback
    let recorderStream = null;
    let recorderChunks = [];
    let recording = false;
    let timerInterval = null;
    let recordSeconds = 0;

    // ------------------------------------------------------------ TTS state
    const TTS = window.speechSynthesis || null;
    let currentUtterance = null;  // utterance currently playing
    let speakingBtn = null;       // speaker button whose reply is playing

    // ------------------------------------------------------------ helpers
    function t(key) {
      return typeof I18n !== "undefined" ? I18n.t(key) : "";
    }

    function scrollToBottom() {
      if (messagesEl) messagesEl.scrollTop = messagesEl.scrollHeight;
    }

    function setBusy(value) {
      busy = value;
      if (typingEl) typingEl.classList.toggle("hidden", !value);
      if (sendBtn) sendBtn.disabled = value;
      if (inputEl) inputEl.disabled = value;
      if (micBtn) micBtn.disabled = value;
      if (value) scrollToBottom();
    }

    // ------------------------------------------------------------ rendering
    function addMessage(role, content, opts = {}) {
      const row = document.createElement("div");
      row.className = "chatbot-row " + role;

      const avatar = document.createElement("span");
      avatar.className = "chatbot-avatar-mini";
      avatar.setAttribute("aria-hidden", "true");
      avatar.textContent = role === "bot" ? "🤖" : "👤";

      const bubble = document.createElement("div");
      bubble.className = "chatbot-bubble";
      bubble.textContent = content; // textContent only — no HTML injection

      row.appendChild(avatar);
      row.appendChild(bubble);

      // Assistant replies get a speaker button for text-to-speech.
      let speakBtn = null;
      if (role === "bot" && opts.speakable !== false && TTS) {
        speakBtn = document.createElement("button");
        speakBtn.type = "button";
        speakBtn.className = "chatbot-speak";
        speakBtn.setAttribute("aria-label", t("chatbot_speak_aria"));
        speakBtn.innerHTML =
          '<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">' +
            '<path d="M11 5 6 9H2v6h4l5 4V5z"/><path d="M15.5 8.5a5 5 0 0 1 0 7"/><path d="M18.5 5.5a9 9 0 0 1 0 13"/>' +
          "</svg>" +
          '<span class="chatbot-bars" aria-hidden="true"><i></i><i></i><i></i></span>';
        speakBtn.addEventListener("click", () => toggleSpeak(speakBtn, content));
        row.appendChild(speakBtn);
      }

      messagesEl.appendChild(row);

      // Quick-question chips sit directly under the welcome message.
      if (opts.quick) {
        const quick = document.createElement("div");
        quick.className = "chatbot-quick";
        quick.id = "chatbot-quick";
        opts.quick.forEach((label) => {
          const chip = document.createElement("button");
          chip.type = "button";
          chip.className = "chatbot-chip";
          chip.textContent = label;
          chip.addEventListener("click", () => {
            hideQuickQuestions();
            sendMessage(label);
          });
          quick.appendChild(chip);
        });
        messagesEl.appendChild(quick);
      }
      scrollToBottom();
      return speakBtn;
    }

    function hideQuickQuestions() {
      const quick = document.getElementById("chatbot-quick");
      if (quick) quick.classList.add("hide");
    }

    function showWelcome() {
      if (greeted) return;
      greeted = true;
      const user = (typeof Api !== "undefined" && Api.getUser && Api.getUser()) || null;
      const parts = [t("chatbot_welcome_1"), t("chatbot_welcome_2"), t("chatbot_welcome_3")];
      if (user && user.full_name) {
        // Personalise the greeting while keeping a single emoji.
        parts[0] = parts[0].replace("👋", "👋 " + user.full_name + ",");
      }
      addMessage("bot", parts.join("\n\n"), {
        quick: [
          t("chatbot_quick_file"),
          t("chatbot_quick_track"),
          t("chatbot_quick_pin"),
          t("chatbot_quick_status"),
          t("chatbot_quick_validate"),
        ],
      });
    }

    // Re-translate the static chrome when the interface language changes.
    function translate() {
      if (!panel) return;
      panel.querySelectorAll("[data-chat-i18n]").forEach((el) => {
        el.textContent = t(el.dataset.chatI18n);
      });
      if (toggleBtn) toggleBtn.setAttribute("aria-label", t("chatbot_toggle_aria"));
      if (closeBtn) closeBtn.setAttribute("aria-label", t("chatbot_close_aria"));
      if (inputEl) {
        inputEl.setAttribute("aria-label", t("chatbot_input_placeholder"));
        if (!listening && !recording) inputEl.setAttribute("placeholder", t("chatbot_input_placeholder"));
      }
      if (sendBtn) sendBtn.setAttribute("aria-label", t("chatbot_send_aria"));
      if (micBtn) micBtn.setAttribute("aria-label", t("chatbot_mic_aria"));
      if (panel) panel.setAttribute("aria-label", t("chatbot_title"));
      // Keep speaker-button labels translated (the playing one stays as-is).
      panel.querySelectorAll(".chatbot-speak").forEach((btn) => {
        if (btn !== speakingBtn) btn.setAttribute("aria-label", t("chatbot_speak_aria"));
      });
    }

    // ------------------------------------------------------------ open/close
    function open() {
      if (opened) return;
      opened = true;
      panel.classList.add("open");
      panel.setAttribute("aria-hidden", "false");
      if (toggleBtn) toggleBtn.setAttribute("aria-expanded", "true");
      showWelcome();
      translate();
      scrollToBottom();
      if (inputEl) setTimeout(() => inputEl.focus(), 260);
    }

    function close() {
      if (!opened) return;
      // Stop any active voice input. A MediaRecorder capture that is already
      // stopping will finish in the background and append to the preserved
      // conversation — messages are never lost when the panel is minimised.
      stopVoice();
      stopSpeaking();
      opened = false;
      panel.classList.remove("open");
      panel.setAttribute("aria-hidden", "true");
      if (toggleBtn) toggleBtn.setAttribute("aria-expanded", "false");
      // Return focus so keyboard users land back on the launcher.
      if (toggleBtn) toggleBtn.focus();
    }

    function toggle() { opened ? close() : open(); }

    // ------------------------------------------------------------ messaging
    async function sendMessage(rawText, opts = {}) {
      const text = String(rawText || "").trim();
      if (!text || busy) return;

      // Client-side spam guard.
      const now = Date.now();
      if (now - lastSentAt < MIN_INTERVAL_MS) return;
      lastSentAt = now;

      addMessage("user", text);
      history.push({ role: "user", content: text });
      hideQuickQuestions();
      inputEl.value = "";
      setBusy(true);

      let reply = t("chatbot_error");
      try {
        const language = typeof I18n !== "undefined" ? I18n.current() : "en";
        const data = await Api.post("/chat/", {
          message: text,
          history: history.slice(-12),
          language: language,
        });
        if (data && data.reply) reply = data.reply;
      } catch {
        /* reply stays the friendly error message */
      }

      const speakBtn = addMessage("bot", reply);
      history.push({ role: "assistant", content: reply });

      setBusy(false);
      // Voice questions get a spoken answer (full-duplex conversation) — but
      // only while the panel is open so audio never plays invisibly.
      if (opts.speakReply && speakBtn && opened) toggleSpeak(speakBtn, reply);
      inputEl.focus();
    }

    // ------------------------------------------------------------ text to speech
    function cleanForSpeech(text) {
      // Strip emoji, decorative bullets and markdown so the voice reads cleanly.
      return String(text || "")
        .replace(/[\u{1F000}-\u{1FAFF}\u{2600}-\u{27BF}\u{FE0F}\u{200D}]/gu, " ")
        .replace(/[•·▪●]/g, ",")
        .replace(/[_*#`>|~]/g, " ")
        .replace(/\s+/g, " ")
        .trim();
    }

    function pickVoice(lang) {
      if (!TTS) return null;
      const voices = TTS.getVoices();
      const base = (lang || "en-IN").split("-")[0];
      return (
        voices.find((v) => v.lang === lang) ||
        voices.find((v) => v.lang && v.lang.split("-")[0] === base) ||
        null
      );
    }

    function stopSpeaking() {
      if (TTS) TTS.cancel();
      if (speakingBtn) {
        speakingBtn.classList.remove("speaking");
        speakingBtn.setAttribute("aria-label", t("chatbot_speak_aria"));
      }
      currentUtterance = null;
      speakingBtn = null;
    }

    function toggleSpeak(btn, text) {
      if (!TTS) return;
      // Clicking the active button stops playback; anything else switches to it.
      if (speakingBtn === btn) { stopSpeaking(); return; }
      stopSpeaking();

      const utterance = new SpeechSynthesisUtterance(cleanForSpeech(text));
      utterance.lang = langTag();
      const voice = pickVoice(utterance.lang);
      if (voice) utterance.voice = voice;
      utterance.rate = 1;

      speakingBtn = btn;
      currentUtterance = utterance;
      btn.classList.add("speaking");
      btn.setAttribute("aria-label", t("chatbot_stop_aria"));

      // Only clean up if this exact utterance finished — guards against
      // speechSynthesis.cancel() inside its own callback re-firing events.
      utterance.onend = () => { if (currentUtterance === utterance) stopSpeaking(); };
      utterance.onerror = () => { if (currentUtterance === utterance) stopSpeaking(); };
      TTS.speak(utterance);
    }

    // ------------------------------------------------------------ voice input
    function langTag() {
      const code = typeof I18n !== "undefined" ? I18n.current() : "en";
      return SR_LANGS[code] || "en-IN";
    }

    function setVoiceUi(active, labelKey) {
      if (micBtn) micBtn.classList.toggle("listening", active);
      if (vtEl) vtEl.classList.toggle("hidden", !active);
      if (inputEl) {
        if (active && labelKey) inputEl.setAttribute("placeholder", t(labelKey));
        else if (!active) inputEl.setAttribute("placeholder", t("chatbot_input_placeholder"));
      }
    }

    function startTimer() {
      recordSeconds = 0;
      if (vtEl) vtEl.textContent = "00:00";
      timerInterval = setInterval(() => {
        recordSeconds += 1;
        const m = String(Math.floor(recordSeconds / 60)).padStart(2, "0");
        const s = String(recordSeconds % 60).padStart(2, "0");
        if (vtEl) vtEl.textContent = m + ":" + s;
      }, 1000);
    }
    function stopTimer() {
      clearInterval(timerInterval);
      timerInterval = null;
    }

    // --- primary path: Web Speech API (instant live transcription) ---------
    function startListening() {
      if (!SpeechRecognitionCtor) return false;
      recognition = new SpeechRecognitionCtor();
      recognition.lang = langTag();
      recognition.interimResults = true;
      recognition.continuous = false;
      recognition.maxAlternatives = 1;
      let finalText = "";
      autoSendQueued = false;

      recognition.onresult = (ev) => {
        let interim = "";
        for (let i = ev.resultIndex; i < ev.results.length; i++) {
          const chunk = ev.results[i][0].transcript;
          if (ev.results[i].isFinal) finalText += chunk;
          else interim += chunk;
        }
        if (finalText) inputEl.value = finalText;
        // Interim words are surfaced in the placeholder for live feedback.
        if (inputEl && interim) inputEl.setAttribute("placeholder", interim + "…");
      };
      recognition.onerror = (ev) => {
        if (ev.error === "not-allowed" || ev.error === "service-not-allowed") {
          if (typeof UI !== "undefined") UI.toast(t("chatbot_voice_unavailable"), "error");
        } else if (ev.error === "no-speech") {
          if (typeof UI !== "undefined") UI.toast(t("chatbot_voice_error"), "warning");
        }
        listening = false;
        setVoiceUi(false);
      };
      recognition.onend = () => {
        listening = false;
        setVoiceUi(false);
        if (finalText.trim() && !autoSendQueued) {
          autoSendQueued = true;
          sendMessage(finalText.trim(), { speakReply: true });
        }
      };
      recognition.start();
      listening = true;
      setVoiceUi(true, "chatbot_listening");
      // The live timer belongs to the MediaRecorder fallback only.
      if (vtEl) vtEl.classList.add("hidden");
      return true;
    }

    function stopListening() {
      if (recognition && listening) {
        try { recognition.stop(); } catch { /* already stopped */ }
      }
      listening = false;
      setVoiceUi(false);
    }

    // --- fallback path: MediaRecorder → backend transcription --------------
    async function startRecording() {
      if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia || !window.MediaRecorder) {
        if (typeof UI !== "undefined") UI.toast(t("chatbot_voice_unavailable"), "error");
        return;
      }
      try {
        recorderStream = await navigator.mediaDevices.getUserMedia({ audio: true });
        recorderChunks = [];
        mediaRecorder = new MediaRecorder(recorderStream);
        mediaRecorder.ondataavailable = (ev) => { if (ev.data && ev.data.size) recorderChunks.push(ev.data); };
        mediaRecorder.onstop = sendRecording;
        mediaRecorder.start();
        recording = true;
        startTimer();
        setVoiceUi(true, "chatbot_listening");
      } catch {
        if (typeof UI !== "undefined") UI.toast(t("chatbot_voice_unavailable"), "error");
      }
    }

    async function sendRecording() {
      recording = false;
      stopTimer();
      setVoiceUi(false);
      if (recorderStream) {
        recorderStream.getTracks().forEach((tr) => tr.stop());
        recorderStream = null;
      }
      const blob = new Blob(recorderChunks, { type: "audio/webm" });
      if (blob.size < 100) return;
      if (typeof UI !== "undefined") UI.toast(t("chatbot_voice_transcribing"), "info", 2000);

      try {
        let wav = blob;
        if (typeof UI !== "undefined" && UI.webmToWav) {
          try {
            const converted = await UI.webmToWav(blob);
            if (converted && converted.size > 100) wav = converted;
          } catch { /* keep webm — Gemini accepts it too */ }
        }
        const fd = new FormData();
        fd.append("audio", wav, wav.type === "audio/wav" ? "voice.wav" : "voice.webm");
        const data = await Api.post("/chat/transcribe/", fd, true);
        const text = (data && data.text || "").trim();
        if (text) sendMessage(text, { speakReply: true });
        else if (typeof UI !== "undefined") UI.toast(t("chatbot_voice_error"), "error");
      } catch {
        if (typeof UI !== "undefined") UI.toast(t("chatbot_voice_error"), "error");
      }
    }

    function stopRecording() {
      if (mediaRecorder && recording) {
        recording = false;
        mediaRecorder.stop();
      }
    }

    function toggleVoice() {
      if (busy) return;
      if (listening) { stopListening(); return; }
      if (recording) { stopRecording(); return; }
      // Prefer instant speech-to-text; fall back to audio recording.
      if (!startListening()) startRecording();
    }

    function stopVoice() {
      stopListening();
      if (recording) stopRecording();
      stopTimer();
      setVoiceUi(false);
    }

    // ------------------------------------------------------------ wiring
    function init() {
      if (!root || !panel || !messagesEl || !inputEl || !sendBtn) return;

      toggleBtn.addEventListener("click", toggle);
      closeBtn.addEventListener("click", close);

      const doSend = () => sendMessage(inputEl.value);
      sendBtn.addEventListener("click", doSend);
      inputEl.addEventListener("keydown", (e) => {
        if (e.key === "Enter") {
          e.preventDefault();
          doSend();
        }
      });
      if (micBtn) micBtn.addEventListener("click", toggleVoice);

      // Escape minimises the panel (accessibility requirement).
      document.addEventListener("keydown", (e) => {
        if (e.key === "Escape" && opened) close();
      });

      // Keep the interface translated when the language switcher changes.
      document.addEventListener("i18n:change", translate);

      // Warm up the voice list (Chrome loads voices asynchronously) and, once
      // voices arrive, apply the best match to a reply that is queued but not
      // yet speaking (pickVoice may have returned null on the first call).
      if (TTS && TTS.getVoices) TTS.getVoices();
      if (TTS && TTS.onvoiceschanged) {
        TTS.onvoiceschanged = () => {
          if (currentUtterance && !TTS.speaking) {
            const voice = pickVoice(currentUtterance.lang);
            if (voice) currentUtterance.voice = voice;
          }
        };
      }

      // Panel starts closed — the button is the only visible element.
      translate();
    }

    return { init };
  })();

  Chatbot.init();
});
