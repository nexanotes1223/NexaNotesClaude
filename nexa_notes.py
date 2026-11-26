"""Punto de entrada de Nexa Notes.

Uso:
  NexaNotes.exe                          abre la aplicación
  NexaNotes.exe --selftest --out r.json  comprueba detección + OCR con la captura incluida
                                         (código de salida 0 = correcto, 1 = fallo)
  NexaNotes.exe --analizar captura.png   analiza capturas y guarda *_diagnostico.png/.json
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from logging.handlers import RotatingFileHandler

# Antes de importar Qt/ONNX: hilos limitados y coordenadas en píxeles físicos
# (las coordenadas de Windows y las de Qt coinciden en cualquier escalado DPI).
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "0"


def _setup_logging(to_file: bool):
    handlers = []
    if sys.stderr is not None:
        handlers.append(logging.StreamHandler())
    if to_file:
        from nexanotes.config import APP_DIR, LOG_PATH
        APP_DIR.mkdir(parents=True, exist_ok=True)
        handlers.append(RotatingFileHandler(LOG_PATH, maxBytes=1_000_000, backupCount=2, encoding="utf-8"))
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                        handlers=handlers or [logging.NullHandler()])


def run_selftest(out_path: str | None) -> int:
    from nexanotes.analysis import selftest
    from nexanotes.config import resource_path
    from nexanotes.ocr import OcrEngine

    ocr = OcrEngine(threads=1)
    ok = ocr.warm_up()
    report: dict
    if not ok:
        report = {"resultado": "FALLO", "error": f"el OCR no arranca: {ocr.init_error}"}
    else:
        ok, report = selftest(str(resource_path("assets/selftest.png")), ocr)
    try:
        import rapidocr_onnxruntime
        cfg = os.path.join(os.path.dirname(rapidocr_onnxruntime.__file__), "config.yaml")
        report["config_yaml_incluido"] = os.path.exists(cfg)
        ok = ok and report["config_yaml_incluido"]
    except Exception as e:
        report["config_yaml_incluido"] = f"error: {e}"
        ok = False
    report["resultado"] = "OK" if ok else "FALLO"
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if out_path:
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(text)
    if sys.stdout is not None:
        try:
            print(text)
        except Exception:
            pass
    return 0 if ok else 1


def run_analyze(paths: list[str]) -> int:
    from nexanotes.analysis import analyze_file
    from nexanotes.ocr import OcrEngine
    ocr = OcrEngine(threads=1)
    code = 0
    for p in paths:
        try:
            res = analyze_file(p, ocr)
            if sys.stdout is not None:
                print(f"{p}: {len(res['etiquetas'])} etiquetas -> {res['imagen_diagnostico']}")
        except Exception as e:
            code = 1
            if sys.stderr is not None:
                print(f"{p}: ERROR {e}", file=sys.stderr)
    return code


def run_gui() -> int:
    from PySide6.QtCore import QLockFile
    from PySide6.QtWidgets import QApplication, QMessageBox

    from nexanotes import APP_NAME
    from nexanotes.app import Controller, MainWindow
    from nexanotes.config import APP_DIR, DB_PATH, Settings
    from nexanotes.db import Database

    from nexanotes import winapi
    winapi.set_dpi_aware()  # coordenadas físicas en todos los monitores
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setStyle("Fusion")
    app.setQuitOnLastWindowClosed(True)

    lock = QLockFile(str(APP_DIR / "nexanotes.lock"))
    lock.setStaleLockTime(0)
    if not lock.tryLock(100):
        QMessageBox.information(None, APP_NAME, "Nexa Notes ya está abierto.")
        return 0

    settings = Settings()
    db = Database(DB_PATH, [h for _n, h in settings["palette"]])
    ctl = Controller(settings, db)
    win = MainWindow(settings, db, ctl)
    win.show()
    if not settings["my_nick"]:
        win.change_nick(initial=True)
    ctl.start()
    code = app.exec()
    ctl.shutdown()
    db.close()
    lock.unlock()
    return code


def main() -> int:
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--out")
    ap.add_argument("--analizar", nargs="+")
    args, _ = ap.parse_known_args()
    if args.selftest:
        _setup_logging(False)
        return run_selftest(args.out)
    if args.analizar:
        _setup_logging(False)
        return run_analyze(args.analizar)
    _setup_logging(True)
    try:
        return run_gui()
    except Exception:
        logging.exception("Error fatal")
        raise


if __name__ == "__main__":
    sys.exit(main())
