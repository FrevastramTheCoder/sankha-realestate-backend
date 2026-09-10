"""Kiswahili/English natural-language parsers for housing chat slots."""

from __future__ import annotations

import re
from typing import Optional, Tuple

from app.services.geo_knowledge import normalize


SWAHILI_UNITS = {
    "sifuri": 0,
    "moja": 1,
    "mbili": 2,
    "tatu": 3,
    "nne": 4,
    "tano": 5,
    "sita": 6,
    "saba": 7,
    "nane": 8,
    "tisa": 9,
    "kumi": 10,
    "ishirini": 20,
    "thelathini": 30,
    "arobaini": 40,
    "arubaini": 40,
    "hamsini": 50,
    "sitini": 60,
    "sabini": 70,
    "themanini": 80,
    "tisini": 90,
    "mia": 100,
}

SWAHILI_TEENS = {
    "kumi na moja": 11,
    "kumi na mbili": 12,
    "kumi na tatu": 13,
    "kumi na nne": 14,
    "kumi na tano": 15,
    "kumi na sita": 16,
    "kumi na saba": 17,
    "kumi na nane": 18,
    "kumi na tisa": 19,
    "kuminamoja": 11,
    "kuminambili": 12,
    "kuminatatu": 13,
    "kuminanne": 14,
    "kuminatano": 15,
    "kuminasita": 16,
    "kuminasaba": 17,
    "kuminanane": 18,
    "kuminatisa": 19,
}

LAKI_WORDS = {
    "moja": 100_000,
    "mbili": 200_000,
    "tatu": 300_000,
    "nne": 400_000,
    "tano": 500_000,
    "sita": 600_000,
    "saba": 700_000,
    "nane": 800_000,
    "tisa": 900_000,
    "kumi": 1_000_000,
}

ELFU_WORDS = {
    "moja": 1_000,
    "mbili": 2_000,
    "tatu": 3_000,
    "nne": 4_000,
    "tano": 5_000,
    "sita": 6_000,
    "saba": 7_000,
    "nane": 8_000,
    "tisa": 9_000,
    "kumi": 10_000,
    "ishirini": 20_000,
    "thelathini": 30_000,
    "arobaini": 40_000,
    "arubaini": 40_000,
    "hamsini": 50_000,
    "sitini": 60_000,
    "sabini": 70_000,
    "themanini": 80_000,
    "tisini": 90_000,
}

MIN_SUPPORTED_BUDGET = 50_000


def _parse_amount(raw: str, suffix: Optional[str] = None) -> int:
    value = float(raw.replace(",", ""))
    suffix = (suffix or "").casefold()
    if suffix == "k":
        value *= 1_000
    elif suffix == "m":
        value *= 1_000_000
    return int(value)


def _amount_pattern() -> str:
    return r"(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s*(k|m)?"


def _swahili_number(text: str) -> Optional[int]:
    cleaned = normalize(text)
    if not cleaned:
        return None
    if cleaned in SWAHILI_TEENS:
        return SWAHILI_TEENS[cleaned]
    if cleaned in SWAHILI_UNITS:
        return SWAHILI_UNITS[cleaned]

    match = re.fullmatch(
        r"(ishirini|thelathini|arobaini|arubaini|hamsini|sitini|sabini|themanini|tisini)"
        r"(?:\s+na\s+(moja|mbili|tatu|nne|tano|sita|saba|nane|tisa))?",
        cleaned,
    )
    if match:
        base = SWAHILI_UNITS[match.group(1)]
        extra = SWAHILI_UNITS.get(match.group(2) or "", 0)
        return base + extra

    match = re.fullmatch(r"kumi(?:\s+na\s+)?(moja|mbili|tatu|nne|tano|sita|saba|nane|tisa)?", cleaned)
    if match:
        if match.group(1):
            return 10 + SWAHILI_UNITS[match.group(1)]
        return 10

    glued = re.fullmatch(
        r"(ishirini|thelathini|arobaini|arubaini|hamsini|sitini|sabini|themanini|tisini|"
        r"kuminatano|kuminamoja|kuminambili|kuminatatu|kuminanne|kuminasita|kuminasaba|"
        r"kuminanane|kuminatisa)(\d+)?",
        cleaned,
    )
    if glued:
        word = glued.group(1)
        if word in SWAHILI_TEENS:
            return SWAHILI_TEENS[word]
        return SWAHILI_UNITS.get(word)

    return None


def parse_budget(message: str) -> Tuple[Optional[int], Optional[int]]:
    """Parse Tanzanian monthly budget expressions as (min, max)."""

    text = normalize(message)
    if not text:
        return None, None

    amount = _amount_pattern()
    range_match = re.search(rf"{amount}\s+(?:to|mpaka)\s+{amount}", text)
    if range_match:
        first = _parse_amount(range_match.group(1), range_match.group(2))
        second = _parse_amount(range_match.group(3), range_match.group(4))
        return min(first, second), max(first, second)

    value: Optional[int] = None
    value_start = 0

    elfu_match = re.search(
        r"\belfu\s+(moja|mbili|tatu|nne|tano|sita|saba|nane|tisa|kumi|"
        r"ishirini|thelathini|arobaini|arubaini|hamsini|sitini|sabini|themanini|tisini)\b",
        text,
    )
    if elfu_match:
        value = ELFU_WORDS.get(elfu_match.group(1))
        value_start = elfu_match.start()

    laki_match = re.search(
        r"\blaki\s+(moja|mbili|tatu|nne|tano|sita|saba|nane|tisa|kumi)"
        r"(?:\s+na\s+(hamsini|sitini|sabini|themanini|tisini|ishirini|thelathini|arobaini))?",
        text,
    )
    if laki_match and value is None:
        base = LAKI_WORDS.get(laki_match.group(1), 0)
        extra_word = laki_match.group(2)
        extra = ELFU_WORDS.get(extra_word, 0) if extra_word else 0
        value = base + extra
        value_start = laki_match.start()

    amount_matches = list(re.finditer(rf"\b{amount}\b", text))
    numeric_value: Optional[int] = None
    numeric_start = 0
    for amount_match in amount_matches:
        candidate = _parse_amount(amount_match.group(1), amount_match.group(2))
        if amount_match.group(2) or candidate >= 10_000:
            if numeric_value is None or candidate >= (numeric_value or 0):
                numeric_value = candidate
                numeric_start = amount_match.start()

    if numeric_value is not None:
        if value is None or numeric_value >= value:
            value = numeric_value
            value_start = numeric_start

    if value is None:
        return None, None

    qualifier = text[max(0, value_start - 80) : value_start]
    surrounding = text
    minimum_words = ("kuanzia", "starting", "from", "minimum", "above", "zaidi ya")
    maximum_words = (
        "chini ya",
        "less than",
        "under",
        "max",
        "maximum",
        "isizidi",
        "upto",
        "up to",
        "sitaki kuzidi",
        "kuzidi",
        "hadi",
        "si zaidi",
        "not more",
        "bajeti ya",
        "budget ya",
        "budget of",
    )
    if any(word in qualifier for word in minimum_words):
        return value, None
    if any(word in qualifier or word in surrounding for word in maximum_words):
        if any(word in qualifier for word in minimum_words):
            return value, None
        return None, value
    return None, value


def parse_travel_time(message: str) -> Optional[float]:
    """Parse travel-time constraints from Kiswahili/English."""

    text = normalize(message)
    if not text:
        return None

    glued = re.search(
        r"\b(?:dakika|minutes?|mins?)?\s*"
        r"(ishirini|thelathini|arobaini|arubaini|hamsini|sitini|sabini|themanini|tisini|"
        r"kuminatano|kuminamoja|kuminambili|kuminatatu|kuminanne|kuminasita|kuminasaba|"
        r"kuminanane|kuminatisa)(\d{1,3})?\b",
        text,
    )
    if glued:
        word = glued.group(1)
        digits = glued.group(2)
        if digits:
            return float(digits)
        word_value = _swahili_number(word)
        if word_value is not None:
            return float(word_value)

    match = re.search(r"\b(\d+(?:\.\d+)?)\s*(?:minutes?|mins?|dakika)\b", text)
    if match:
        return float(match.group(1))
    reverse_match = re.search(r"\b(?:dakika|minutes?|mins?)\s*(\d+(?:\.\d+)?)\b", text)
    if reverse_match:
        return float(reverse_match.group(1))

    word_match = re.search(
        r"\b(?:dakika|minutes?|mins?)\s+"
        r"((?:kumi(?:\s+na\s+)?(?:moja|mbili|tatu|nne|tano|sita|saba|nane|tisa)?|"
        r"kuminatano|kuminamoja|kuminambili|kuminatatu|kuminanne|kuminasita|kuminasaba|"
        r"kuminanane|kuminatisa|"
        r"(?:ishirini|thelathini|arobaini|arubaini|hamsini|sitini|sabini|themanini|tisini)"
        r"(?:\s+na\s+(?:moja|mbili|tatu|nne|tano|sita|saba|nane|tisa))?|"
        r"moja|mbili|tatu|nne|tano|sita|saba|nane|tisa))\b",
        text,
    )
    if word_match:
        value = _swahili_number(word_match.group(1))
        if value is not None:
            return float(value)

    if re.search(r"\b(ndani ya|within|kutoka chuoni|kutoka campus|safari)\b", text):
        bare = re.search(
            r"\b(ishirini|thelathini|arobaini|hamsini|sitini|kuminatano|kumi na tano)\b",
            text,
        )
        if bare and not re.search(r"\b(elfu|laki|bajeti|budget|tzs|tsh)\b", text):
            value = _swahili_number(bare.group(1))
            if value is not None and value <= 180:
                return float(value)

    return None


def parse_radius(message: str) -> Optional[float]:
    text = normalize(message)
    match = re.search(r"\b(?:within|inside|kwa|ndani ya)?\s*(\d+(?:\.\d+)?)\s*km\b", text)
    return float(match.group(1)) if match else None


def institution_override(message: str) -> bool:
    text = normalize(message)
    return bool(
        re.search(
            r"\b(hapana|siyo|sio|badala yake|badilisha|nataka|ninaenda|switch|instead|no[, ]|not )\b",
            text,
        )
    )
