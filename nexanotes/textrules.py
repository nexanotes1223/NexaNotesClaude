"""Clasificación del texto leído en la línea del nickname."""
from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

NAME = "name"            # nickname válido
TIMEBANK = "timebank"    # contador numérico temporal
ACTION = "action"        # All in, Fold, Check... (temporal)
TRUNCATED = "truncated"  # nombre cortado con puntos suspensivos
NOISE = "noise"          # ilegible, cantidades, etc.

MIN_SCORE = 0.60

_ACTIONS = {
    "ALLIN", "FOLD", "CHECK", "CALL", "BET", "RAISE", "SITOUT", "SITTINGOUT", "AWAY",
    "WAITING", "DISCONNECTED", "THINKING", "SHOW", "MUCK", "STRADDLE", "POST",
    "SMALLBLIND", "BIGBLIND", "ANTE", "BB", "SB", "LEAVE", "SEATOPEN", "EMPTY",
    "RESERVED", "TAKESEAT", "SITHERE", "OFFLINE", "TIMEBANK",
}
_TIMEBANK_RE = re.compile(r"^\d{1,3}\s*[sS]?$|^\d{1,2}[:：.]\d{2}$")
_AMOUNT_RE = re.compile(r"^[¥$€£]?[\d.,]*\d[\d.,]*(K|M|BB)?$", re.IGNORECASE)
_ELLIPSIS_RE = re.compile(r"(\.{2,}|…|。。+|··+)\s*$")


def normalize(text: str) -> str:
    t = unicodedata.normalize("NFKC", text or "")
    t = re.sub(r"\s+", " ", t).strip()
    return t


def classify(text: str, score: float) -> tuple[str, str]:
    """Devuelve (tipo, texto_normalizado). Para TRUNCATED el texto es el prefijo visible."""
    t = normalize(text)
    if not t or score < MIN_SCORE:
        return NOISE, t
    m = _ELLIPSIS_RE.search(t)
    if m:
        prefix = t[: m.start()].strip()
        return (TRUNCATED, prefix) if len(prefix) >= 2 else (NOISE, t)
    compact = re.sub(r"[\s\-_!.]", "", t).upper()
    if compact in _ACTIONS:
        return ACTION, t
    if _TIMEBANK_RE.match(t):
        return TIMEBANK, t
    if _AMOUNT_RE.match(t.replace(" ", "")) and not t.isdigit():
        return NOISE, t  # cantidad de fichas, BB o importe (p. ej. 9.8BB, ¥1,372)
    if len(t) < 2 and not _is_cjk(t):
        return NOISE, t
    return NAME, t


def _is_cjk(t: str) -> bool:
    return any("一" <= ch <= "鿿" or "㐀" <= ch <= "䶿" for ch in t)


def similar(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def same_player_text(confirmed: str, read: str) -> bool:
    """¿El texto leído es el mismo nombre con un posible error menor de OCR?"""
    if confirmed == read:
        return True
    if min(len(confirmed), len(read)) >= 5 and similar(confirmed, read) >= 0.86:
        return True
    return False
