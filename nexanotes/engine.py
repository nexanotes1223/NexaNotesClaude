"""Planificación: búsqueda de mesas y análisis en segundo plano.

* Búsqueda de ventanas (hilo principal, cada 5 s): operación ligera de Win32.
* Un ÚNICO hilo de análisis. En cada "tick" (2 s por defecto) analiza UNA mesa
  visible, en turno rotatorio: captura del área cliente -> detección de
  etiquetas -> OCR solo de los asientos que lo necesitan. Nunca hay dos OCR a
  la vez ni trabajos acumulados: no existe cola, solo el turno siguiente.

Frecuencia efectiva con N mesas visibles (tick T = 2 s, OCR cada 30 s):
  * cada mesa se re-analiza (posición de etiquetas, asientos vacíos) cada N*T s;
  * cada asiento se relee por OCR cada max(30 s, N*T) s, y antes si aparece un
    asiento nuevo, cambia el avatar o hay una lectura dudosa.
  Ejemplos: 4 mesas -> etiquetas cada 8 s, OCR cada 30 s;
            12 mesas -> etiquetas cada 24 s, OCR cada ~30 s;
            20 mesas -> etiquetas cada 40 s, OCR cada ~40 s.
  El uso de CPU queda acotado por el tick, no por el número de mesas.
"""
from __future__ import annotations

import logging
import threading
import time
import traceback
from dataclasses import dataclass, field

from PySide6.QtCore import QObject, Signal

from . import winapi
from .detector import Detection, detect_labels
from .ocr import OcrEngine
from .tracker import TableTracker

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class SeatView:
    """Copia inmutable de un asiento para dibujar desde el hilo de la interfaz."""
    sid: int
    rect: tuple
    name_rect: tuple
    avatar_rect: tuple
    display_name: str | None
    name: str | None
    status: str
    last_text: str
    last_kind: str
    last_score: float
    truncated_prefix: str | None
    events: tuple


def build_view(tracker: TableTracker) -> tuple:
    return tuple(SeatView(s.sid, s.label.rect, s.label.name_rect, s.label.avatar_rect, s.display_name, s.name,
                          s.status, s.last_text, s.last_kind, s.last_score, s.truncated_prefix,
                          tuple(s.history[-5:])) for s in tracker.seats)


@dataclass
class TableState:
    hwnd: int
    title: str
    exe: str
    tracker: TableTracker
    frame_size: tuple[int, int] = (0, 0)
    detection: Detection | None = None
    last_analysis: float = 0.0
    timings: dict = field(default_factory=dict)
    method: str = ""
    error: str = ""
    skipped: str = ""
    view: tuple = ()          # tuple[SeatView]: lo que dibuja el overlay
    last_saved: float = 0.0


def match_tables(windows, process_keywords, title_keyword):
    """Filtro obligatorio: proceso de Nexa Y título con la palabra clave."""
    kws = [k.lower() for k in process_keywords if k]
    tables, rejected = [], []
    for w in windows:
        has_title = title_keyword.lower() in w.title.lower()
        has_proc = bool(w.exe) and any(k in w.exe.lower() for k in kws)
        if has_title and has_proc:
            tables.append(w)
        elif has_title:
            rejected.append((w, "el título contiene la palabra clave pero el proceso no es de Nexa"))
        elif has_proc:
            rejected.append((w, "ventana de Nexa sin la palabra clave (lobby u otra)"))
    return tables, rejected


class AnalysisWorker(QObject):
    """Bucle de análisis en un hilo de Python independiente (la interfaz nunca se bloquea)."""
    table_updated = Signal(int)   # hwnd
    status = Signal(str)

    def __init__(self, settings, ocr: OcrEngine):
        super().__init__()
        self.settings = settings
        self.ocr = ocr
        self.tables: dict[int, TableState] = {}
        self.lock = threading.Lock()
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread = threading.Thread(target=self._run, name="NexaNotes-analisis", daemon=True)
        self._rr = 0
        self.last_error = ""

    def start(self):
        self._thread.start()

    def stop(self):
        self._stop.set()
        self._wake.set()
        self._thread.join(timeout=5)

    def poke(self):
        self._wake.set()

    def set_tables(self, wins):
        with self.lock:
            alive = {w.hwnd for w in wins}
            for h in list(self.tables):
                if h not in alive:
                    del self.tables[h]  # libera capturas y seguimiento de mesas cerradas
            for w in wins:
                st = self.tables.get(w.hwnd)
                if st is None:
                    self.tables[w.hwnd] = TableState(w.hwnd, w.title, w.exe,
                                                     TableTracker(self.settings["ocr_interval_s"]))
                    self._wake.set()  # analizar pronto la mesa nueva
                else:
                    st.title = w.title

    def set_manual_name(self, hwnd: int, sid: int, name: str):
        with self.lock:
            t = self.tables.get(hwnd)
            if t:
                t.tracker.set_manual_name(sid, name)
                t.view = build_view(t.tracker)

    def snapshot(self, hwnd) -> TableState | None:
        with self.lock:
            return self.tables.get(hwnd)

    def _next_table(self) -> TableState | None:
        with self.lock:
            cands = [t for t in self.tables.values()
                     if winapi.is_window(t.hwnd) and not winapi.is_minimized(t.hwnd)
                     and winapi.is_visible(t.hwnd) and not winapi.is_cloaked(t.hwnd)]
            if not cands:
                return None
            # primero las que nunca se han analizado
            fresh = [t for t in cands if t.last_analysis == 0]
            if fresh:
                return fresh[0]
            cands.sort(key=lambda t: t.hwnd)
            self._rr = (self._rr + 1) % len(cands)
            return cands[self._rr]

    def _run(self):
        while not self._stop.is_set():
            self._wake.wait(timeout=float(self.settings["analysis_tick_s"]))
            self._wake.clear()
            if self._stop.is_set():
                break
            if not self.settings["recognition_enabled"]:
                continue
            t = self._next_table()
            if t is None:
                continue
            try:
                self._analyze(t)
            except Exception as e:
                self.last_error = f"{type(e).__name__}: {e}"
                t.error = self.last_error
                log.error("Error analizando mesa %s\n%s", t.hwnd, traceback.format_exc())
            self.table_updated.emit(t.hwnd)

    def _save_capture(self, t: TableState, img):
        """Modo diagnóstico: guarda la última captura de cada mesa (para revisarla)."""
        now = time.monotonic()
        if now - t.last_saved < 10:
            return
        t.last_saved = now
        try:
            import cv2
            from .config import APP_DIR
            d = APP_DIR / "diagnostico"
            d.mkdir(parents=True, exist_ok=True)
            ok, buf = cv2.imencode(".png", img)
            if ok:
                buf.tofile(str(d / f"mesa_{t.hwnd}.png"))
        except Exception:
            log.exception("No se pudo guardar la captura de diagnóstico")

    def _analyze(self, t: TableState):
        t0 = time.perf_counter()
        img, method = winapi.capture_client(t.hwnd)
        t1 = time.perf_counter()
        t.method = method
        t.skipped = ""
        if img is None:
            t.skipped = f"sin captura ({method})"
            t.last_analysis = time.monotonic()
            return
        if method == "pantalla" and not winapi.is_fully_visible(t.hwnd):
            # Una mesa tapada capturada desde pantalla daría asientos "vacíos" falsos.
            t.skipped = "mesa tapada y no capturable con PrintWindow: se espera"
            t.last_analysis = time.monotonic()
            return
        if self.settings["diagnostic"]:
            self._save_capture(t, img)
        det = detect_labels(img)
        t2 = time.perf_counter()
        ocr_fn = self.ocr.recognize if self.ocr.init_error is None else None
        with self.lock:
            n = t.tracker.update(img, det, ocr_fn)
            t.view = build_view(t.tracker)
        t3 = time.perf_counter()
        t.detection = det
        t.frame_size = (img.shape[1], img.shape[0])
        t.timings = {"captura_ms": round((t1 - t0) * 1000), "deteccion_ms": round((t2 - t1) * 1000),
                     "ocr_ms": round((t3 - t2) * 1000), "ocr_lecturas": n}
        t.error = ""
        t.last_analysis = time.monotonic()
        del img
