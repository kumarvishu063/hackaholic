"""
Thin wrapper around the modern `google-genai` SDK.

Every public method returns `None` on failure (missing key, network error,
model error …) so the caller can fall back to the mock AI pipeline. This
guarantees complaint processing never breaks the API.
"""

import logging

from django.conf import settings

logger = logging.getLogger(__name__)

try:
    from google import genai  # modern SDK (google-genai)
    from google.genai import types as genai_types
except ImportError:  # pragma: no cover
    genai = None
    genai_types = None


class GeminiClient:
    """Stateless facade over the Gemini generative models."""

    def __init__(self):
        self.api_key = settings.GEMINI_API_KEY
        self.available = bool(self.api_key and genai is not None)
        self.model_name = settings.GEMINI_MODEL
        self.fallback_models = list(settings.GEMINI_FALLBACK_MODELS or [])
        self._client = None

    # ------------------------------------------------------------------
    def _get_client(self):
        """Lazily build the SDK client (no network call happens here)."""
        if self._client is None and self.available:
            self._client = genai.Client(api_key=self.api_key)
        return self._client

    def _generate(self, prompt: str, audio_path: str | None = None, temperature: float = 0.3):
        """Ask Gemini; try each configured model in order; return text or None."""
        if not self.available:
            return None
        client = self._get_client()
        if client is None:
            return None

        config = genai_types.GenerateContentConfig(temperature=temperature)
        uploaded = None

        for model_name in [self.model_name, *self.fallback_models]:
            try:
                contents = []
                if audio_path:
                    # Upload audio (webm/wav/mp3/ogg all supported) and attach it.
                    with open(audio_path, "rb") as handle:
                        uploaded = client.files.upload(file=handle)
                    contents.append(uploaded)
                contents.append(prompt)

                response = client.models.generate_content(
                    model=model_name,
                    contents=contents,
                    config=config,
                )
                text = (response.text or "").strip()
                if text:
                    return text
            except Exception as exc:
                logger.warning("Gemini model '%s' failed: %s", model_name, exc)
            finally:
                if uploaded is not None:
                    try:
                        client.files.delete(name=uploaded.name)
                    except Exception:
                        pass
                    uploaded = None
        return None

    # ------------------------------------------------------------------
    # High-level operations used by the complaint pipeline
    # ------------------------------------------------------------------
    def transcribe_audio(self, audio_path: str):
        """Transcribe a citizen's audio recording (verbatim)."""
        return self._generate(
            "Transcribe the following citizen complaint audio recording verbatim. "
            "Return only the transcript text, without any preamble.",
            audio_path=audio_path,
            temperature=0.1,
        )

    def remove_pii(self, text: str):
        """Redact personally identifiable information from text."""
        prompt = (
            "Remove all personally identifiable information from this citizen complaint: "
            "names, phone numbers, email addresses, government ID numbers and exact home "
            "addresses. Replace each item with [REDACTED]. Return only the cleaned text.\n\n"
            f"{text}"
        )
        return self._generate(prompt, temperature=0.1)

    def generate_summary(self, text: str):
        """Produce a concise 2–3 sentence summary of the complaint."""
        prompt = (
            "Summarise this citizen complaint in 2-3 concise sentences, keeping the key "
            "problem, location and requested action. Return only the summary.\n\n"
            f"{text}"
        )
        return self._generate(prompt)

    def validate_category(self, text: str, suggested: str):
        """Confirm the best category from the official list, else None."""
        from apps.complaints.models import CATEGORY_CHOICES

        prompt = (
            "Choose the single most accurate category for this complaint from this exact "
            f"list: {', '.join(CATEGORY_CHOICES)}. Return only the category name.\n\n{text}"
        )
        result = self._generate(prompt, temperature=0.1)
        if result and result.strip() in CATEGORY_CHOICES:
            return result.strip()
        return None

    def assess_urgency(self, text: str):
        """Return an urgency integer 1–10, or None on any failure."""
        prompt = (
            "Score the urgency of this citizen complaint from 1 (low priority) to "
            "10 (critical emergency). Consider safety, health and number of people affected. "
            "Return only the integer.\n\n"
            f"{text}"
        )
        result = self._generate(prompt, temperature=0.1)
        try:
            score = int(str(result).strip())
            return max(1, min(10, score))
        except (TypeError, ValueError):
            return None

    # ------------------------------------------------------------------
    # Chat (JanSetu Assistant)
    # ------------------------------------------------------------------
    def chat(self, message: str, history: list | None = None, language: str = "en"):
        """Answer a citizen's question about the JanSetu portal.

        A system prompt grounds the model in the real portal and forbids it from
        inventing complaint IDs, statuses, officers or account data. Real status
        data is always served by the database lookup (see chatbot.py), never by
        the model.
        """
        system = (
            "You are JanSetu Assistant, the official AI citizen-support assistant for the "
            "JanSetu grievance management portal. Help citizens understand and use the portal "
            f"in plain, friendly language. Answer in the citizen's language ({language or 'en'}).\n"
            "Key facts about the portal:\n"
            "- Workflow: Citizen submits -> Pending Validation -> Verified -> Resolved (or Rejected).\n"
            "- Complaint IDs look like JST-4K9XM2P7; every complaint has a 6-digit PIN and a SHA-256 hash.\n"
            "- Categories: Roads & Transport, Water Supply, Electricity, Sanitation & Garbage, "
            "Public Health, Education, Police & Safety, Environment, Other.\n"
            "- AI transcribes audio, removes personal information, summarises, validates the "
            "category and scores urgency 1-10.\n"
            "STRICT RULES:\n"
            "1. NEVER invent complaint IDs, statuses, officer names, department contacts, "
            "resolution dates or any user account information.\n"
            "2. For complaint status questions, ask the citizen for their Complaint ID or PIN. "
            "Status data comes from a secure database lookup, not from you.\n"
            "3. Never reveal other users' private data.\n"
            "4. Keep answers short and citizen-friendly (2-4 sentences).\n"
        )
        parts = [system]
        for turn in (history or [])[-6:]:
            role = "User" if turn.get("role") == "user" else "Assistant"
            parts.append(f"{role}: {str(turn.get('content', ''))[:2000]}")
        parts.append(f"User: {str(message)[:2000]}")
        parts.append("Assistant:")
        return self._generate("\n\n".join(parts), temperature=0.4)
