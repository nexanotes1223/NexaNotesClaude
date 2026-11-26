"""Rutas, ajustes persistentes y paleta de colores."""
from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path

log = logging.getLogger(__name__)

APP_DIR = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "NexaNotes"
DB_PATH = APP_DIR / "jugadores.db"
SETTINGS_PATH = APP_DIR / "config.json"
LOG_PATH = APP_DIR / "nexanotes.log"

# Mismos valores hexadecimales que usaba la versión anterior, para que los
# colores ya guardados en jugadores.db se reconozcan sin cambios.
DEFAULT_PALETTE = [
    ("Rojo", "#ef4444"),
    ("Naranja", "#f97316"),
    ("Amarillo", "#eab308"),
    ("Verde", "#22c55e"),
    ("Turquesa", "#06b6d4"),
    ("Azul", "#3b82f6"),
    ("Morado", "#a855f7"),
    ("Rosa", "#ec4899"),
    ("Gris", "#9ca3af"),
    ("Blanco", "#ffffff"),
]

DEFAULTS = {
    "my_nick": "",
    # Paleta configurable por RGB: lista de [nombre, "#rrggbb"] (10 posiciones).
    "palette": [list(p) for p in DEFAULT_PALETTE],
    # Filtro de ventanas: el ejecutable del proceso debe contener alguno de
    # estos textos (sin distinguir mayúsculas) Y el título debe contener la
    # palabra clave. Se puede ajustar desde Ajustes si el ejecutable real
    # de Nexa Poker tiene otro nombre.
    "process_keywords": ["nexa"],
    "title_keyword": "Blinds",
    "window_scan_s": 5.0,      # búsqueda de ventanas
    "analysis_tick_s": 2.0,    # una mesa analizada (captura + detección) por tick
    "ocr_interval_s": 30.0,    # OCR periódico de cada asiento
    "recognition_enabled": True,
    "diagnostic": False,
    "show_edit_buttons": True,
}


def resource_path(rel: str) -> Path:
    """Ruta a un recurso incluido (funciona en desarrollo y dentro del .exe)."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return base / rel


class Settings:
    def __init__(self, path: Path = SETTINGS_PATH):
        self.path = path
        self.data = dict(DEFAULTS)
        if path.exists():
            try:
                loaded = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    self.data.update(loaded)  # conserva claves antiguas (my_nick)
            except Exception:  # archivo dañado: se conservan los valores por defecto
                log.exception("No se pudo leer %s", path)
        self._fix_palette()

    def _fix_palette(self):
        pal = self.data.get("palette")
        ok = isinstance(pal, list) and len(pal) == 10
        if ok:
            for item in pal:
                if not (isinstance(item, (list, tuple)) and len(item) == 2 and _is_hex(item[1])):
                    ok = False
                    break
        if not ok:
            self.data["palette"] = [list(p) for p in DEFAULT_PALETTE]

    def __getitem__(self, k):
        return self.data.get(k, DEFAULTS.get(k))

    def __setitem__(self, k, v):
        self.data[k] = v
        self.save()

    def save(self):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(tmp, self.path)
        except Exception:
            log.exception("No se pudo guardar la configuración")

    def palette_hex(self, slot: int | None) -> str | None:
        """slot: 1..10."""
        if slot is None or not 1 <= slot <= 10:
            return None
        return self.data["palette"][slot - 1][1]


def _is_hex(s) -> bool:
    if not isinstance(s, str) or len(s) != 7 or not s.startswith("#"):
        return False
    try:
        int(s[1:], 16)
        return True
    except ValueError:
        return False
