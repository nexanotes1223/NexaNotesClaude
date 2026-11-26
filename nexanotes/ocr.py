"""Motor OCR local (RapidOCR + ONNX Runtime), una única instancia compartida.

Solo se usa el reconocedor de texto (sin detector de texto) sobre el recorte
de la línea del nickname: es más rápido y no puede leer textos de otras zonas.
"""
from __future__ import annotations

import logging
import os
import threading

import numpy as np

log = logging.getLogger(__name__)

# Limitar hilos antes de importar onnxruntime.
os.environ.setdefault("OMP_NUM_THREADS", "1")


class OcrEngine:
    def __init__(self, threads: int = 1):
        self._threads = threads
        self._engine = None
        self._lock = threading.Lock()
        self.init_error: str | None = None

    def _ensure(self):
        if self._engine is None:
            from rapidocr_onnxruntime import RapidOCR  # importación diferida (arranque rápido)
            self._engine = RapidOCR(
                intra_op_num_threads=self._threads,
                inter_op_num_threads=1,
                print_verbose=False,
            )

    def warm_up(self) -> bool:
        try:
            with self._lock:
                self._ensure()
            return True
        except Exception as e:  # pragma: no cover - depende del entorno
            self.init_error = f"{type(e).__name__}: {e}"
            log.exception("No se pudo iniciar el OCR")
            return False

    def recognize(self, img: np.ndarray) -> tuple[str, float]:
        """Devuelve (texto, confianza 0..1) de una línea de texto."""
        if img is None or img.size == 0 or img.shape[0] < 6 or img.shape[1] < 6:
            return "", 0.0
        with self._lock:  # nunca dos reconocimientos simultáneos
            self._ensure()
            res, _ = self._engine(img, use_det=False, use_cls=False, use_rec=True)
        if not res:
            return "", 0.0
        text, score = res[0][0], float(res[0][1])
        return text, score
