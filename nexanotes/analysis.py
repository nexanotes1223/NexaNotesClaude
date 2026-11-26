"""Análisis de capturas estáticas (diagnóstico y autocomprobación del OCR).

No necesita Windows ni la interfaz gráfica: sirve para probar la detección con
capturas reales antes de generar una nueva versión.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import cv2
import numpy as np

from . import textrules as tr
from .detector import crop, detect_labels

# Nombres esperados en la captura de autocomprobación (assets/selftest.png)
SELFTEST_EXPECTED = ["DuDu29", "烧烤哥弟", "九序昭温", "one01s", "VETEMENTS", "跑马王在此", "AhyeonBaby"]


def analyze_image(img: np.ndarray, ocr=None) -> dict:
    t0 = time.perf_counter()
    det = detect_labels(img)
    t1 = time.perf_counter()
    labels = []
    for lab in det.labels:
        entry = {"etiqueta": list(lab.rect), "zona_nickname": list(lab.name_rect)}
        if ocr is not None:
            text, score = ocr.recognize(crop(img, lab.name_rect))
            kind, norm = tr.classify(text, score)
            entry.update({"texto": norm, "confianza": round(score, 3), "tipo": kind})
        labels.append(entry)
    t2 = time.perf_counter()
    return {
        "tamaño": list(det.size),
        "etiquetas": labels,
        "descartadas": [{"zona": list(r), "motivo": why} for r, why in det.rejected],
        "tiempos_ms": {"deteccion": round((t1 - t0) * 1000), "ocr": round((t2 - t1) * 1000)},
    }


def draw_analysis(img: np.ndarray, result: dict) -> np.ndarray:
    """Imagen anotada: verde = etiqueta, amarillo = zona OCR, rojo = descartada.
    Solo usa la fuente vectorial interna de OpenCV (sin archivos de fuentes)."""
    out = img.copy()
    W = img.shape[1]
    thick = max(1, W // 600)
    for d in result["descartadas"]:
        x, y, w, h = d["zona"]
        cv2.rectangle(out, (x, y), (x + w, y + h), (0, 0, 255), 1)
    for i, e in enumerate(result["etiquetas"], 1):
        x, y, w, h = e["etiqueta"]
        cv2.rectangle(out, (x - 2, y - 2), (x + w + 2, y + h + 2), (0, 220, 0), thick + 1)
        nx, ny, nw, nh = e["zona_nickname"]
        cv2.rectangle(out, (nx, ny), (nx + nw, ny + nh), (0, 255, 255), 1)
        cv2.putText(out, str(i), (x + w + 4, y + 14), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 220, 0), thick)
    return out


def analyze_file(path: str, ocr=None) -> dict:
    img = cv2.imdecode(np.fromfile(path, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError(f"No se puede abrir la imagen: {path}")
    res = analyze_image(img, ocr)
    p = Path(path)
    out_img = p.with_name(p.stem + "_diagnostico.png")
    ok, buf = cv2.imencode(".png", draw_analysis(img, res))
    if ok:
        buf.tofile(str(out_img))
    p.with_name(p.stem + "_diagnostico.json").write_text(
        json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    res["imagen_diagnostico"] = str(out_img)
    return res


def selftest(image_path: str, ocr) -> tuple[bool, dict]:
    """Comprueba detección + OCR con una captura real conocida."""
    report: dict = {"imagen": image_path}
    try:
        img = cv2.imdecode(np.fromfile(image_path, np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            report["error"] = "no se pudo abrir la imagen de prueba"
            return False, report
        res = analyze_image(img, ocr)
        names = [e.get("texto", "") for e in res["etiquetas"]]
        report.update(res)
        report["nombres_leidos"] = names
        report["esperados"] = SELFTEST_EXPECTED
        missing = [n for n in SELFTEST_EXPECTED if n not in names]
        report["faltan"] = missing
        ok = len(res["etiquetas"]) == len(SELFTEST_EXPECTED) and not missing
        report["resultado"] = "OK" if ok else "FALLO"
        return ok, report
    except Exception as e:  # el informe debe generarse siempre
        report["error"] = f"{type(e).__name__}: {e}"
        report["resultado"] = "FALLO"
        return False, report
