"""
AI orchestration for complaint processing.

Pipeline:  audio → transcript → PII removal → summary → category → urgency.
Each stage attempts Google Gemini first and automatically falls back to the
mock implementation, so the application never breaks when the key is missing.

`ai_source` reports which engine produced the primary content: it is "gemini"
when the transcript or the summary actually came from Gemini, otherwise "mock".
"""

import logging

from apps.ai_services.gemini_client import GeminiClient
from apps.ai_services.mock_ai import (
    mock_remove_pii,
    mock_summary,
    mock_transcript,
    mock_urgency,
    mock_validate_category,
)

logger = logging.getLogger(__name__)


def process_complaint(description: str, category: str, audio_path: str | None = None) -> dict:
    """
    Run the full AI pipeline over a new complaint.

    Returns a dict with `transcript`, `cleaned_text`, `summary`, `category`,
    `urgency_score` and `ai_source` ("gemini" or "mock"). Never raises.
    """
    client = GeminiClient()
    ai_source = "mock"

    # 1. Transcription (from audio, else the typed description)
    transcript = ""
    if audio_path:
        transcript = client.transcribe_audio(audio_path) or ""
    if transcript.strip():
        ai_source = "gemini"
    else:
        transcript = mock_transcript(category, description or "")

    # 2. PII removal (mock redaction is the baseline; Gemini improves it)
    raw = transcript.strip()
    cleaned = mock_remove_pii(raw) or raw
    if client.available and raw:
        gemini_cleaned = client.remove_pii(raw)
        if gemini_cleaned:
            cleaned = gemini_cleaned

    # 3. Summary
    summary = client.generate_summary(cleaned) if client.available and cleaned else ""
    if summary.strip():
        ai_source = "gemini"
    else:
        summary = mock_summary(cleaned, category)

    # 4. Category validation
    validated_category = category
    if client.available and cleaned:
        validated_category = client.validate_category(cleaned, category) or category
    if not validated_category:
        validated_category = mock_validate_category(cleaned or description or "", category)

    # 5. Urgency score (1–10)
    urgency = client.assess_urgency(cleaned) if client.available and cleaned else None
    if urgency is None:
        urgency = mock_urgency(cleaned or description or "", validated_category)

    return {
        "transcript": transcript,
        "cleaned_text": cleaned,
        "summary": summary,
        "category": validated_category,
        "urgency_score": urgency,
        "ai_source": ai_source,
    }
