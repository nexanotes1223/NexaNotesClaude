"""Seguimiento de la identidad de cada asiento de una mesa.

Distingue entre:
  * nombre temporalmente oculto (timebank, All in, Fold...): se conserva la identidad;
  * asiento vacío: la etiqueta desaparece en varios análisis seguidos -> se retira;
  * cambio real de jugador: se lee otro nombre de forma consistente (dos lecturas
    seguidas) o se lee otro nombre y además cambia el avatar -> identidad nueva.
Mientras hay dudas, el asiento queda "en duda" y NO se dibuja ningún color,
para que un jugador nuevo nunca herede el color del anterior.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable

import numpy as np

from . import textrules as tr
from .detector import Detection, Label, avatar_signature, crop, signature_distance

CONFIRMED = "confirmado"
READING = "leyendo"
UNCERTAIN = "en duda"
TRUNCATED_ST = "truncado"

MATCH_DIST = 0.06           # distancia normalizada máx. para considerar el mismo asiento
EMPTY_AFTER_MISSES = 2      # análisis seguidos sin etiqueta -> asiento vacío
AVATAR_CHANGE = 0.55        # distancia de firma de avatar que indica avatar distinto
HIGH_SCORE = 0.85           # una lectura con esta confianza confirma un asiento vacío
MAX_OCR_PER_PASS = 9


@dataclass
class Seat:
    sid: int
    cx: float
    cy: float
    label: Label
    name: str | None = None          # identidad confirmada
    manual_name: str | None = None   # nombre completo indicado por el usuario (truncados)
    status: str = READING
    candidate: str | None = None
    candidate_hits: int = 0
    truncated_prefix: str | None = None
    avatar_sig: np.ndarray | None = None
    misses: int = 0
    last_ocr: float = 0.0
    force_ocr: bool = True
    last_text: str = ""
    last_score: float = 0.0
    last_kind: str = ""
    history: list[str] = field(default_factory=list)  # eventos (diagnóstico)

    @property
    def display_name(self) -> str | None:
        """Nombre con el que se busca el color en la base de datos."""
        if self.status == UNCERTAIN:
            return None
        return self.manual_name or self.name

    def _event(self, msg: str):
        self.history.append(time.strftime("%H:%M:%S ") + msg)
        del self.history[:-12]


class TableTracker:
    def __init__(self, ocr_interval_s: float = 30.0):
        self.seats: list[Seat] = []
        self._next_id = 1
        self.ocr_interval_s = ocr_interval_s
        self.events: list[str] = []

    def _log(self, msg):
        self.events.append(time.strftime("%H:%M:%S ") + msg)
        del self.events[:-40]

    def update(self, frame: np.ndarray, det: Detection, ocr: Callable[[np.ndarray], tuple[str, float]] | None,
               now: float | None = None) -> int:
        """Actualiza con un nuevo análisis. Devuelve cuántos OCR se han hecho."""
        now = time.monotonic() if now is None else now
        W, H = det.size
        if W <= 0 or H <= 0:
            return 0
        # --- emparejar etiquetas con asientos conocidos (por posición relativa)
        pts = []
        for lab in det.labels:
            x, y, w, h = lab.rect
            pts.append(((x + w / 2) / W, (y + h / 2) / H, lab))
        unmatched_seats = set(range(len(self.seats)))
        pairs = []
        for li, (cx, cy, _lab) in enumerate(pts):
            for si in range(len(self.seats)):
                s = self.seats[si]
                d = ((s.cx - cx) ** 2 + (s.cy - cy) ** 2) ** 0.5
                if d <= MATCH_DIST:
                    pairs.append((d, li, si))
        pairs.sort()
        used_l, matched = set(), {}
        for d, li, si in pairs:
            if li in used_l or si not in unmatched_seats:
                continue
            used_l.add(li)
            unmatched_seats.discard(si)
            matched[si] = li

        matched_obj = {li: self.seats[si] for si, li in matched.items()}

        # --- asientos sin etiqueta: posible asiento vacío
        for si in sorted(unmatched_seats):
            self.seats[si].misses += 1
        for s in self.seats:
            if s.misses >= EMPTY_AFTER_MISSES:
                self._log(f"asiento {s.sid} vacío: se retira {s.name or '(sin nombre)'}")
        self.seats = [s for s in self.seats if s.misses < EMPTY_AFTER_MISSES]

        # --- actualizar asientos emparejados y crear nuevos
        n_ocr = 0
        for li, (cx, cy, lab) in enumerate(pts):
            seat = matched_obj.get(li)
            if seat is None:
                seat = Seat(self._next_id, cx, cy, lab)
                self._next_id += 1
                self.seats.append(seat)
                self._log(f"asiento {seat.sid} nuevo en ({cx:.2f},{cy:.2f})")
            seat.cx, seat.cy, seat.label, seat.misses = cx, cy, lab, 0
            sig = avatar_signature(frame, lab)
            dist = signature_distance(seat.avatar_sig, sig)
            avatar_changed = dist is not None and dist > AVATAR_CHANGE
            if seat.avatar_sig is None or not avatar_changed:
                # actualización suave de la firma (tolera animaciones)
                seat.avatar_sig = sig if seat.avatar_sig is None or sig is None else 0.7 * seat.avatar_sig + 0.3 * sig
            needs = (seat.force_ocr or avatar_changed or seat.status in (READING, UNCERTAIN)
                     or now - seat.last_ocr >= self.ocr_interval_s)
            if ocr is not None and needs and n_ocr < MAX_OCR_PER_PASS:
                text, score = ocr(crop(frame, lab.name_rect))
                n_ocr += 1
                seat.last_ocr = now
                seat.force_ocr = False
                self._apply_reading(seat, text, score, avatar_changed, sig)
        return n_ocr

    # ------------------------------------------------------------------
    def _apply_reading(self, seat: Seat, text: str, score: float, avatar_changed: bool, sig):
        kind, t = tr.classify(text, score)
        seat.last_text, seat.last_score, seat.last_kind = t, score, kind
        if kind in (tr.TIMEBANK, tr.ACTION):
            seat._event(f"{kind} '{t}': se mantiene {seat.name}")
            return
        if kind == tr.NOISE:
            return
        if kind == tr.TRUNCATED:
            known = seat.manual_name or seat.name
            if known and known.startswith(t):
                seat._event(f"truncado '{t}…' coincide con {known}")
                return
            if known and not avatar_changed:
                # prefijo distinto: tratar como posible cambio
                self._candidate(seat, t + "…", avatar_changed, sig)
                return
            self._reset_identity(seat, f"truncado '{t}…'")
            seat.truncated_prefix = t
            seat.status = TRUNCATED_ST
            return
        # kind == NAME
        if seat.name is None:
            if score >= HIGH_SCORE or (seat.candidate and tr.same_player_text(seat.candidate, t)):
                self._confirm(seat, t)
            else:
                seat.candidate, seat.candidate_hits = t, 1
                seat.force_ocr = True
            return
        if tr.same_player_text(seat.name, t):
            seat.status = CONFIRMED
            seat.candidate, seat.candidate_hits = None, 0
            if avatar_changed:
                seat.avatar_sig = sig  # mismo nombre: el avatar cambió de aspecto
            return
        self._candidate(seat, t, avatar_changed, sig)

    def _candidate(self, seat: Seat, t: str, avatar_changed: bool, sig=None):
        if avatar_changed and not t.endswith("…"):
            self._log(f"asiento {seat.sid}: cambio de jugador {seat.name} -> {t} (avatar distinto)")
            self._reset_identity(seat, "cambio con avatar distinto")
            self._confirm(seat, t)
            seat.avatar_sig = sig
            return
        if seat.candidate and tr.same_player_text(seat.candidate, t):
            seat.candidate_hits += 1
        else:
            seat.candidate, seat.candidate_hits = t, 1
        if seat.candidate_hits >= 2:
            self._log(f"asiento {seat.sid}: cambio de jugador {seat.name} -> {t} (2 lecturas)")
            self._reset_identity(seat, "cambio confirmado por 2 lecturas")
            seat.avatar_sig = sig if sig is not None else seat.avatar_sig
            if t.endswith("…"):
                seat.truncated_prefix = t[:-1]
                seat.status = TRUNCATED_ST
            else:
                self._confirm(seat, t)
        else:
            seat.status = UNCERTAIN  # sin color hasta resolver
            seat.force_ocr = True
            seat._event(f"lectura distinta '{t}' (en duda)")

    def _confirm(self, seat: Seat, t: str):
        seat.name = t
        seat.status = CONFIRMED
        seat.candidate, seat.candidate_hits = None, 0
        seat.truncated_prefix = None
        seat._event(f"confirmado {t}")

    def _reset_identity(self, seat: Seat, why: str):
        seat.name = None
        seat.manual_name = None
        seat.candidate, seat.candidate_hits = None, 0
        seat.truncated_prefix = None
        seat.status = READING
        seat._event(f"identidad borrada: {why}")

    def set_manual_name(self, sid: int, name: str):
        for s in self.seats:
            if s.sid == sid:
                s.manual_name = name
                if s.status == TRUNCATED_ST:
                    s.status = CONFIRMED
                return
