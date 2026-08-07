"""
JanSetu Assistant chat endpoint.

POST /api/chat/   { message, history?, language? }  →  { reply, source }

Resolution order (never fabricates system data):
  1. If the message contains a Complaint ID (JST-XXXXXXXX) the reply is built
     from the real database record — status is NEVER invented.
  2. Otherwise Google Gemini answers with the JanSetu system prompt.
  3. If Gemini is unavailable or fails, the multilingual knowledge base replies.

The endpoint is anonymous-friendly (auth is optional): when the caller is an
authenticated citizen who owns the complaint, the status reply includes the AI
summary; otherwise only public tracking fields are returned.
"""

import os
import re
import tempfile
import time

from django.conf import settings
from rest_framework import exceptions as drf_exceptions
from rest_framework import status
from rest_framework.exceptions import Throttled, ValidationError
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.ai_services.chatbot import (
    extract_complaint_id,
    mock_chat_response,
    status_ask_id_reply,
    status_found_reply,
    status_not_found_reply,
)
from apps.ai_services.gemini_client import GeminiClient
from apps.ai_services.mock_ai import mock_chat_transcript
from apps.authentication.authentication import JWTAuthentication
from apps.complaints.models import Complaint

# Audio formats accepted by the voice-input transcribe endpoint.
AUDIO_EXTENSIONS = (".webm", ".wav", ".mp3", ".ogg", ".m4a", ".mp4")
_AUDIO_MAGIC = (b"RIFF", b"OggS", b"ID3", b"\x1aE\xdf\xa3", b"fLaC", b"\xff\xfb", b"\xff\xf3", b"\xff\xf2")

MAX_MESSAGE_LENGTH = 2000
MAX_HISTORY_TURNS = 12

# Guard: messages that clearly ask about *their own* complaint but give no
# ID/PIN get prompted for one. Scoped to personal-tracking intents so general
# questions like "what does a status mean" still reach the knowledge base.
_TRACK_INTENT = re.compile(
    r"(where is my|my complaint|status of my|track my|update on my|"
    r"मेरी शिकायत|माझी तक्रार|ನನ್ನ ದೂರು|আমার অভিযোগ)",
    re.IGNORECASE,
)

# Simple in-memory throttle for this public endpoint (per client IP).
_RATE_WINDOW_SECONDS = 60
_RATE_MAX_REQUESTS = 30
_rate_tracker = {}


def _rate_limited(ip: str) -> bool:
    from collections import deque

    now = time.monotonic()
    queue = _rate_tracker.get(ip)
    if queue is None:
        _rate_tracker[ip] = deque([now], maxlen=_RATE_MAX_REQUESTS)
        return False
    while queue and now - queue[0] > _RATE_WINDOW_SECONDS:
        queue.popleft()
    if len(queue) >= _RATE_MAX_REQUESTS:
        return True
    queue.append(now)
    return False


class OptionalJWTAuthentication(JWTAuthentication):
    """JWT auth that treats an invalid/expired token as anonymous.

    The assistant is a public widget: a stale or unknown token in the user's
    browser must never produce a 401 (which would force a logout redirect).
    An optional identity simply makes status replies owner-aware when valid.
    """

    def authenticate(self, request):
        try:
            return super().authenticate(request)
        except drf_exceptions.AuthenticationFailed:
            return None


class ChatbotView(APIView):
    """One endpoint powering the whole floating JanSetu Assistant."""

    permission_classes = [AllowAny]
    authentication_classes = [OptionalJWTAuthentication]

    def post(self, request):
        client_ip = request.META.get("REMOTE_ADDR", "")
        if _rate_limited(client_ip):
            raise Throttled(detail="Too many requests. Please wait a moment and try again.")

        message = (request.data.get("message") or "").strip()
        if not message:
            raise ValidationError({"message": "Message is required."})
        if len(message) > MAX_MESSAGE_LENGTH:
            raise ValidationError({"message": "Message is too long."})

        language = (request.data.get("language") or "en").strip().lower()[:2]
        history = request.data.get("history") or []
        if not isinstance(history, list):
            history = []
        # Keep only well-formed turns and cap the window.
        history = [
            {"role": "user" if t.get("role") == "user" else "assistant",
             "content": str(t.get("content", ""))[:MAX_MESSAGE_LENGTH]}
            for t in history if isinstance(t, dict)
        ][-MAX_HISTORY_TURNS:]

        source = "mock"
        reply = None

        # 1) Live complaint-status lookup (deterministic, never invented).
        complaint_id = extract_complaint_id(message)
        if complaint_id:
            complaint = Complaint.objects(complaint_id=complaint_id).first()
            if complaint is not None:
                is_owner = bool(
                    request.user is not None
                    and getattr(request.user, "is_authenticated", False)
                    and str(request.user.id) == str(complaint.citizen_id)
                )
                reply = status_found_reply(complaint, is_owner=is_owner, language=language)
                source = "data"
            else:
                reply = status_not_found_reply(complaint_id, language=language)
                source = "data"

        # 2) Gemini (grounded in the JanSetu system prompt).
        if reply is None:
            client = GeminiClient()
            reply = client.chat(message, history, language) if client.available else None
            if reply:
                source = "gemini"

        # 3) Ask for an ID when the citizen clearly wants a status update.
        if reply is None and _TRACK_INTENT.search(message):
            reply = status_ask_id_reply(language)

        # 4) Multilingual knowledge base fallback.
        if reply is None:
            reply = mock_chat_response(message, language)

        return Response(
            {"reply": reply, "source": source},
            status=status.HTTP_200_OK,
        )


class ChatbotTranscribeView(APIView):
    """Convert a spoken question into text for the assistant.

    POST /api/chat/transcribe/   (multipart: audio=file)

    Uses the same Gemini transcription pipeline as complaint audio and falls
    back to a realistic mock transcript when the API key is unavailable.
    """

    permission_classes = [AllowAny]
    authentication_classes = [OptionalJWTAuthentication]

    def post(self, request):
        client_ip = request.META.get("REMOTE_ADDR", "")
        if _rate_limited(client_ip):
            raise Throttled(detail="Too many requests. Please wait a moment and try again.")

        audio_file = request.FILES.get("audio")
        if audio_file is None:
            raise ValidationError({"audio": "Audio file is required."})

        # Extension + magic-byte checks (a renamed file cannot sneak in).
        filename = (audio_file.name or "").lower()
        if not filename.endswith(AUDIO_EXTENSIONS):
            raise ValidationError({"audio": "Unsupported audio format."})
        if audio_file.size > settings.MAX_AUDIO_SIZE:
            raise ValidationError({"audio": "Audio file is too large."})
        audio_file.seek(0)
        head = audio_file.read(12)
        audio_file.seek(0)
        if not head:
            raise ValidationError({"audio": "Empty audio file."})
        if not head.startswith(_AUDIO_MAGIC):
            raise ValidationError({"audio": "The file does not look like audio."})

        # Persist to a temp file so Gemini can read it from disk.
        suffix = filename[filename.rfind("."):] or ".webm"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            for chunk in audio_file.chunks():
                tmp.write(chunk)
            tmp_path = tmp.name

        try:
            client = GeminiClient()
            text = client.transcribe_audio(tmp_path) if client.available else None
            source = "gemini" if text else "mock"
            if not text:
                text = mock_chat_transcript()
        finally:
            try:
                os.remove(tmp_path)
            except OSError:
                pass

        return Response({"text": text, "source": source}, status=status.HTTP_200_OK)
