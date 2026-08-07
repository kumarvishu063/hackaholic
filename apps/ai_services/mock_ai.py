"""
Realistic mock AI responses.

Used automatically whenever the Gemini API key is missing or a Gemini call
fails, so the application stays fully functional offline. Every function here
is deterministic where possible (based on input hashing) so tests are stable.
"""

import hashlib
import re

# ---------------------------------------------------------------------------
# Sample transcripts per complaint category (in the complainant's voice).
# ---------------------------------------------------------------------------
MOCK_TRANSCRIPTS = {
    "Roads & Transport": (
        "Hello, I am reporting a big pothole near the MG Road junction. Many two-wheelers "
        "have had accidents here in the evening. Please get it fixed as soon as possible."
    ),
    "Water Supply": (
        "There has been no water supply in our area for the last three days. Residents are "
        "facing great difficulty for drinking and cooking water. Please restore supply immediately."
    ),
    "Electricity": (
        "The street light near the children's park has not worked for two weeks. The road is "
        "completely dark at night and unsafe, especially for women and children."
    ),
    "Sanitation & Garbage": (
        "Garbage has not been collected from our street for over a week. The dustbins are "
        "overflowing and there is a bad smell everywhere. Please arrange daily collection."
    ),
    "Public Health": (
        "There is stagnant water in the open drain near our street and mosquitoes are breeding "
        "there. We are worried about dengue in the area. Please clear the drain and spray."
    ),
    "Education": (
        "The roof of the government primary school leaks heavily during rain. Classes get "
        "cancelled and the children suffer. Please repair the school building."
    ),
    "Police & Safety": (
        "An abandoned vehicle has been parked in our narrow lane for a month. It blocks the way "
        "and is a safety hazard. Please have it removed."
    ),
    "Environment": (
        "Someone is illegally cutting trees near the lake. This is harming the environment. "
        "Please stop the cutting and take action."
    ),
    "Other": (
        "I would like to register a complaint about an issue in my area and request the "
        "authorities to take the necessary action at the earliest."
    ),
}

# Phrases that should push the urgency score up.
URGENCY_BOOSTERS = [
    "accident", "dengue", "leak", "no water", "unsafe", "safety hazard", "emergency",
    "mosquito", "fire", "collapse", "bleeding", "children", "dark at night",
    "no electricity", "stagnant water", "severe",
]

# ---------------------------------------------------------------------------
# PII removal — conservative redaction of common identifiers.
# ---------------------------------------------------------------------------
_PII_PATTERNS = [
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"), "[EMAIL]"),          # email addresses
    (re.compile(r"(?<!\d)(?:\+?91[- ]?)?[6-9]\d{9}(?!\d)"), "[PHONE]"),  # Indian mobiles
    (re.compile(r"(?<!\d)\d{12}(?!\d)"), "[AADHAAR]"),            # 12-digit Aadhaar-like
    (re.compile(r"my name is ([A-Z][a-z]+(?:\s[A-Z][a-z]+){0,2})", re.I), "my name is [NAME]"),
]


def mock_transcript(category: str = "", description: str = "") -> str:
    """Return a realistic spoken-style transcript for the category."""
    if category in MOCK_TRANSCRIPTS:
        return MOCK_TRANSCRIPTS[category]
    return description.strip() or MOCK_TRANSCRIPTS["Other"]


def mock_chat_transcript() -> str:
    """Mock voice-to-text for the chatbot assistant (offline fallback).

    Used when Gemini is unavailable so the voice-input flow still completes.
    """
    return "How do I track the status of my complaint?"


def mock_remove_pii(text: str) -> str:
    """Redact common PII markers from text (emails, phones, Aadhaar, name)."""
    if not text:
        return text
    cleaned = text
    for pattern, replacement in _PII_PATTERNS:
        cleaned = pattern.sub(replacement, cleaned)
    return cleaned


def mock_summary(text: str, category: str = "") -> str:
    """Generate a concise two-sentence summary from the transcript."""
    first_sentence = (text or "").strip().split(".")[0].strip()
    subject = category.lower() if category else "the reported issue"
    return (
        f"The complainant reports a {subject} concern: {first_sentence}. "
        "They request prompt action from the concerned department to resolve the issue."
    )


def mock_validate_category(text: str, suggested: str = "") -> str:
    """Return a category from the known list, preferring the suggested one."""
    from apps.complaints.models import CATEGORY_CHOICES

    lowered = (text or "").lower()
    for category in CATEGORY_CHOICES:
        keyword = category.split(" &")[0].lower()
        if keyword in lowered:
            return category
    return suggested if suggested in CATEGORY_CHOICES else "Other"


def mock_urgency(text: str, category: str = "") -> int:
    """Deterministic urgency score (1–10) with keyword boosters."""
    if not text:
        return 5
    digest = hashlib.md5(f"{category}:{text}".encode("utf-8")).hexdigest()
    base = (int(digest[:4], 16) % 6) + 2  # 2..7
    boosted = base + sum(1 for word in URGENCY_BOOSTERS if word in text.lower())
    return max(1, min(10, boosted))
