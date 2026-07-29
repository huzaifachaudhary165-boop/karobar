"""Text helpers: slugs, fuzzy matching (for AI name resolution) and language detection."""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

_SLUG_RE = re.compile(r"[^a-z0-9]+")
_URDU_RANGE = re.compile(r"[؀-ۿݐ-ݿ]")
_DEVANAGARI_RANGE = re.compile(r"[ऀ-ॿ]")


def slugify(value: str, max_length: int = 60) -> str:
    normalised = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return _SLUG_RE.sub("-", normalised.lower()).strip("-")[:max_length] or "item"


def normalise(value: str | None) -> str:
    """Lowercase, strip punctuation and collapse whitespace — for comparisons."""
    if not value:
        return ""
    text = unicodedata.normalize("NFKC", value).lower().strip()
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s؀-ۿऀ-ॿ]", " ", text)).strip()


def similarity(a: str, b: str) -> float:
    """0..1 similarity, with a bonus for substring containment.

    Used to match 'ahmad traders' typed by the AI against 'Ahmed Traders (Lahore)'.
    """
    na, nb = normalise(a), normalise(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    base = SequenceMatcher(None, na, nb).ratio()
    if na in nb or nb in na:
        base = max(base, 0.88)
    tokens_a, tokens_b = set(na.split()), set(nb.split())
    if tokens_a and tokens_b:
        jaccard = len(tokens_a & tokens_b) / len(tokens_a | tokens_b)
        base = max(base, jaccard * 0.95)
    return round(base, 4)


def best_match(query: str, candidates: list[tuple[str, str]], threshold: float = 0.62) -> tuple[str, float] | None:
    """candidates = [(id, name)]. Returns (id, score) of the best hit above threshold."""
    scored = [(cid, similarity(query, name)) for cid, name in candidates]
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[0] if scored and scored[0][1] >= threshold else None


def rank_matches(query: str, candidates: list[tuple[str, str]], limit: int = 5, threshold: float = 0.35):
    scored = [(cid, name, similarity(query, name)) for cid, name in candidates]
    scored = [s for s in scored if s[2] >= threshold]
    scored.sort(key=lambda x: x[2], reverse=True)
    return scored[:limit]


def detect_language(text: str) -> str:
    """Returns 'ur', 'hi', or 'en'. Roman-Urdu is reported as 'ur' so the assistant replies in kind."""
    if not text:
        return "en"
    if _URDU_RANGE.search(text):
        return "ur"
    if _DEVANAGARI_RANGE.search(text):
        return "hi"
    roman_markers = {
        "kitna", "kitne", "kya", "hai", "hain", "kar", "karo", "kardo", "mujhe", "mera", "meri",
        "banao", "bana", "dedo", "diya", "liya", "paisa", "paise", "rupay", "udhaar", "udhar",
        "bech", "becha", "kharid", "kharida", "stock", "bill", "kal", "aaj", "abhi", "nahi",
        "wala", "wale", "se", "ko", "ka", "ki", "ke", "bhai", "sahab", "jama", "baqi", "kitna",
    }
    words = set(normalise(text).split())
    return "ur" if len(words & roman_markers) >= 2 else "en"


def truncate(value: str | None, length: int = 120, suffix: str = "…") -> str:
    if not value:
        return ""
    return value if len(value) <= length else value[: length - len(suffix)].rstrip() + suffix


def initials(name: str, count: int = 2) -> str:
    parts = [p for p in normalise(name).split() if p]
    return "".join(p[0].upper() for p in parts[:count]) or "?"


def mask_email(email: str | None) -> str:
    if not email or "@" not in email:
        return email or ""
    local, _, domain = email.partition("@")
    visible = local[:2] if len(local) > 3 else local[:1]
    return f"{visible}{'*' * max(3, len(local) - len(visible))}@{domain}"


_NUM_WORDS = {
    "ek": 1, "do": 2, "teen": 3, "char": 4, "chaar": 4, "panch": 5, "paanch": 5,
    "che": 6, "chhe": 6, "saat": 7, "aath": 8, "nau": 9, "das": 10, "bees": 20,
    "pachas": 50, "sau": 100, "hazar": 1000, "hazaar": 1000, "lakh": 100_000, "crore": 10_000_000,
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "hundred": 100, "thousand": 1000,
}


def extract_number(text: str) -> float | None:
    """Pulls a quantity out of free speech: '2 hazaar ka bill' → 2000."""
    if not text:
        return None
    digits = re.findall(r"\d+(?:\.\d+)?", text.replace(",", ""))
    words = normalise(text).split()
    multiplier = 1
    for w in words:
        if w in ("hazar", "hazaar", "thousand", "k"):
            multiplier = max(multiplier, 1000)
        elif w in ("lakh", "lac"):
            multiplier = max(multiplier, 100_000)
        elif w in ("crore", "cr"):
            multiplier = max(multiplier, 10_000_000)
    if digits:
        return float(digits[0]) * multiplier
    for w in words:
        if w in _NUM_WORDS:
            return float(_NUM_WORDS[w]) * (multiplier if multiplier > 1 else 1)
    return None
