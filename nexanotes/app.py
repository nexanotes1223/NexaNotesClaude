"""Interfaz principal de Nexa Notes y coordinación de overlays."""
from __future__ import annotations

import html
import logging
import os
import threading
import time

from PySide6.QtCore import QObject, QPoint, QRect, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtWidgets import (QCheckBox, QColorDialog, QDialog, QDialogButtonBox, QDoubleSpinBox,
                               QFileDialog, QFormLayout, QGridLayout, QGroupBox, QHBoxLayout,
                               QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem,
                               QMainWindow, QMessageBox, QPushButton, QTextBrowser, QTextEdit,
                               QVBoxLayout, QWidget)

from . import APP_NAME, VERSION, winapi
from .config import APP_DIR, DB_PATH, DEFAULT_PALETTE, Settings, resource_path
from .db import Database
from .editor import ColorButton, PlayerEditor
from .engine import AnalysisWorker, match_tables
from .ocr import OcrEngine
from .overlay import BorderStrip, SeatButton, TableOverlay
from .tracker import TRUNCATED_ST

log = logging.getLogger(__name__)

POSITION_POLL_MS = 120  # seguimiento de posición: solo llamadas Win32 baratas


class Controller(QObject):
    tables_changed = Signal(int)
    colors_changed = Signal()

    def __init__(self, settings: Settings, db: Database):
        super().__init__()
        self.settings, self.db = settings, db
        self.ocr = OcrEngine(threads=1)
        self.worker = AnalysisWorker(settings, self.ocr)
        self.worker.table_updated.connect(self._on_table_updated, Qt.ConnectionType.QueuedConnection)
        self.overlays: dict[int, TableOverlay] = {}
        self.buttons: dict[int, list[SeatButton]] = {}
        self.strips: dict[int, list[BorderStrip]] = {}  # 4 tiras por jugador con color
        self.layers: dict[int, list[int]] = {}           # capas de Nexa encima de cada mesa
        self.visible_count: dict[int, int] = {}          # etiquetas visibles (no tapadas) por mesa
        self.geom: dict[int, tuple] = {}
        self.colors: dict[str, str] = {}
        self._seen: set[str] = set()
        self.ui_error = ""
        self.last_scan_rejected = []
        self.last_scan_time = 0.0
        self.editor = PlayerEditor(lambda: self.settings["palette"], lambda: [p.nickname for p in self.db.list()])
        self.editor.saved.connect(self._on_editor_saved)
        self.refresh_colors()

        self.scan_timer = QTimer(self)
        self.scan_timer.timeout.connect(self.scan)
        self.pos_timer = QTimer(self)
        self.pos_timer.timeout.connect(self.reposition)

    def start(self):
        threading.Thread(target=self.ocr.warm_up, name="ocr-init", daemon=True).start()
        self.worker.start()
        self.scan()
        self.scan_timer.start(int(float(self.settings["window_scan_s"]) * 1000))
        self.pos_timer.start(POSITION_POLL_MS)

    def shutdown(self):
        self.scan_timer.stop()
        self.pos_timer.stop()
        self.worker.stop()
        for h in list(self.overlays):
            self._remove_table(h)

    # -------------------------------------------------------------- mesas
    def scan(self):
        try:
            wins = winapi.enum_windows()
            tables, rejected = match_tables(wins, self.settings["process_keywords"], self.settings["title_keyword"])
        except Exception:
            log.exception("Error buscando ventanas")
            return
        self.last_scan_rejected = rejected
        self.last_scan_time = time.time()
        self.worker.set_tables(tables)
        alive = {w.hwnd for w in tables}
        for h in list(self.overlays):
            if h not in alive:
                self._remove_table(h)
        for w in tables:
            if w.hwnd not in self.overlays:
                self.overlays[w.hwnd] = TableOverlay(w.hwnd)
                self.buttons[w.hwnd] = []
        self.tables_changed.emit(len(tables))

    def _remove_table(self, h):
        ov = self.overlays.pop(h, None)
        if ov:
            ov.hide()
            ov.deleteLater()
        for b in self.buttons.pop(h, []) + self.strips.pop(h, []):
            b.hide()
            b.deleteLater()
        self.geom.pop(h, None)

    def table_count(self) -> int:
        return len(self.overlays)

    def reposition(self):
        try:
            self._reposition()
        except Exception as e:  # nunca debe romper la interfaz; queda en el diagnóstico
            self.ui_error = f"superposición: {type(e).__name__}: {e}"
            log.exception("Error en la superposición")

    def _reposition(self):
        for h, ov in list(self.overlays.items()):
            if not winapi.is_window(h):
                self._remove_table(h)
                continue
            hidden = winapi.is_minimized(h) or not winapi.is_visible(h) or winapi.is_cloaked(h)
            rc = None if hidden else winapi.client_rect_screen(h)
            if rc is None or rc[2] < 50:
                if ov.isVisible():
                    ov.hide()
                for b in self.buttons.get(h, []) + self.strips.get(h, []):
                    b.hide()
                self.geom.pop(h, None)
                continue
            if self.geom.get(h) != rc:
                self.geom[h] = rc
                ov.setGeometry(QRect(*rc))
                self._place_buttons(h)
            want = ov.has_content()
            if want and not ov.isVisible():
                ov.show()
                ov.ensure_owned()
            elif not want and ov.isVisible():
                ov.hide()
            # orden de ventanas: dibujo justo encima de la mesa y botones encima del dibujo
            # Visibilidad real de cada etiqueta: nuestras ventanas son "siempre
            # visibles" (así nunca quedan detrás de la mesa) y se ocultan las de cada
            # jugador cuya etiqueta tapa otra ventana (otra aplicación, otra mesa...).
            visible_sids = self._visible_seats(h, rc, ov)
            for st in self.strips.get(h, []):
                show = st.active and st.sid in visible_sids
                self._show_topmost(st, show)
            for b in self.buttons.get(h, []):
                show = bool(b.sid) and self.settings["show_edit_buttons"] and b.sid in visible_sids
                self._show_topmost(b, show)

    def _show_topmost(self, w, show: bool):
        if show:
            if not w.isVisible():
                w.show()
                w.ensure_owned()
                winapi.set_topmost(w.native)
        elif w.isVisible():
            w.hide()

    def _visible_seats(self, h, rc, ov) -> set:
        """Asientos cuya etiqueta se ve entera (5 puntos: centro y esquinas interiores)."""
        fw, fh = ov.frame_size
        sx, sy = rc[2] / max(1, fw), rc[3] / max(1, fh)
        out = set()
        for s in ov.view:
            x, y, w, hh = s.rect
            X, Y, W, Hh = rc[0] + x * sx, rc[1] + y * sy, w * sx, hh * sy
            pts = [(X + W / 2, Y + Hh / 2), (X + W * 0.1, Y + Hh * 0.15), (X + W * 0.9, Y + Hh * 0.15),
                   (X + W * 0.1, Y + Hh * 0.85), (X + W * 0.9, Y + Hh * 0.85)]
            if all(winapi.point_shows_table(h, px, py) for px, py in pts):
                out.add(s.sid)
        self.visible_count[h] = len(out)
        return out

    def _on_table_updated(self, hwnd: int):
        try:
            self._table_updated(hwnd)
        except Exception as e:
            self.ui_error = f"actualización: {type(e).__name__}: {e}"
            log.exception("Error actualizando la mesa")

    def _table_updated(self, hwnd: int):
        ov = self.overlays.get(hwnd)
        st = self.worker.snapshot(hwnd)
        if ov is None or st is None:
            return
        tm = st.timings
        header = ""
        if self.settings["diagnostic"]:
            header = (f"{st.title[:60]}\n"
                      f"captura: {st.method} {tm.get('captura_ms', '-')} ms | detección {tm.get('deteccion_ms', '-')} ms"
                      f" | OCR {tm.get('ocr_ms', '-')} ms ({tm.get('ocr_lecturas', 0)})\n"
                      f"etiquetas: {len(st.view)}  {st.skipped or st.error}")
        rejected = st.detection.rejected if st.detection else []
        ov.set_data(st.view, st.frame_size, self.colors, self.settings["my_nick"], self.settings["diagnostic"],
                    rejected, header)
        for s in st.view:  # "visto por última vez": una escritura por jugador y sesión
            if s.display_name and s.display_name not in self._seen and self.db.get(s.display_name):
                self._seen.add(s.display_name)
                self.db.touch_seen(s.display_name)
        self._sync_buttons(hwnd)
        self.reposition()

    def _sync_buttons(self, hwnd):
        ov = self.overlays.get(hwnd)
        pool = self.buttons.setdefault(hwnd, [])
        wanted = []
        if ov is not None and self.settings["show_edit_buttons"]:
            for s in ov.view:
                if s.status == "en duda" or s.status == "vacío":
                    continue
                if not (s.display_name or s.truncated_prefix or self.settings["diagnostic"]):
                    continue
                if s.display_name and s.display_name == self.settings["my_nick"]:
                    continue
                wanted.append(s)
        while len(pool) < len(wanted):
            b = SeatButton(hwnd)
            b.clicked.connect(self.open_editor_for_seat)
            pool.append(b)
        for i, b in enumerate(pool):
            if i < len(wanted):
                b.sid = wanted[i].sid
                b.color = ov._color_for(wanted[i]) if ov else None
                b.update()
            else:
                b.sid = 0
                b.hide()
        # tiras de color (4 por jugador con color asignado)
        colored = []
        if ov is not None:
            for s in ov.view:
                c = ov._color_for(s)
                if c:
                    colored.append((s, c, False))
                elif self.settings["diagnostic"]:
                    colored.append((s, "#e5e7eb", True))  # diagnóstico: etiqueta detectada sin color
        spool = self.strips.setdefault(hwnd, [])
        while len(spool) < 4 * len(colored):
            spool.append(BorderStrip(hwnd))
        for i, st in enumerate(spool):
            if i < 4 * len(colored):
                seat, col, thin = colored[i // 4]
                st.sid, st.side, st.active, st.thin = seat.sid, i % 4, True, thin
                st.set_color(col)
            else:
                st.active = False
                st.hide()
        self._place_buttons(hwnd)

    def _place_buttons(self, hwnd):
        rc = self.geom.get(hwnd)
        ov = self.overlays.get(hwnd)
        if not rc or ov is None:
            return
        fw, fh = ov.frame_size
        sx, sy = rc[2] / max(1, fw), rc[3] / max(1, fh)
        seats = {s.sid: s for s in ov.view}
        for b in self.buttons.get(hwnd, []):
            s = seats.get(b.sid)
            if not s:
                b.hide()
                continue
            x, y, w, h = s.rect
            size = int(max(14, min(26, h * sy * 0.42)))
            bx = rc[0] + int((x + w) * sx) + 1 + max(2, int(round(w * sx * 0.03))) + 3  # a la derecha del borde
            by = rc[1] + int(y * sy)
            b.setGeometry(bx, by, size, size)
        for st in self.strips.get(hwnd, []):
            s = seats.get(getattr(st, "sid", 0)) if st.active else None
            if not s:
                st.hide()
                continue
            x, y, w, h = s.rect
            X, Y = rc[0] + int(round(x * sx)), rc[1] + int(round(y * sy))
            Wd, Ht = int(round(w * sx)), int(round(h * sy))
            t = 1 if getattr(st, "thin", False) else max(2, int(round(Wd * 0.03)))   # grosor
            g = 1                                # separación con la etiqueta
            if st.side == 0:    # arriba
                st.setGeometry(X - g - t, Y - g - t, Wd + 2 * (g + t), t)
            elif st.side == 1:  # abajo
                st.setGeometry(X - g - t, Y + Ht + g, Wd + 2 * (g + t), t)
            elif st.side == 2:  # izquierda
                st.setGeometry(X - g - t, Y - g, t, Ht + 2 * g)
            else:               # derecha
                st.setGeometry(X + Wd + g, Y - g, t, Ht + 2 * g)

    # -------------------------------------------------------------- colores
    def refresh_colors(self):
        out = {}
        for nick, (slot, hexcol) in self.db.colored_map().items():
            col = self.settings.palette_hex(slot) or hexcol
            if col:
                out[nick] = col
        self.colors = out
        for h, ov in self.overlays.items():
            ov.colors = out
            ov.update()
            self._sync_buttons(h)
        self.colors_changed.emit()
        self.reposition()

    def set_diagnostic(self, on: bool):
        self.settings["diagnostic"] = on
        for h, ov in self.overlays.items():
            ov.diagnostic = on
            ov.set_capture_exclusion()
            ov.update()
            self._sync_buttons(h)
        self.reposition()

    # -------------------------------------------------------------- editor
    def open_editor_for_seat(self, hwnd: int, sid: int):
        st = self.worker.snapshot(hwnd)
        if not st:
            return
        seat = next((s for s in st.view if s.sid == sid), None)
        if not seat:
            return
        name = seat.display_name
        editable, hint = False, ""
        if not name:
            editable = True
            if seat.status == TRUNCATED_ST and seat.truncated_prefix:
                name = seat.truncated_prefix
                hint = (f"El nombre aparece cortado («{seat.truncated_prefix}…»). Escribe el nombre completo; "
                        "no se asociará a nadie automáticamente.")
            else:
                name = seat.last_text or ""
                hint = "El nombre aún no está confirmado. Revísalo antes de guardar."
        p = self.db.get(name) if name else None
        rc = self.geom.get(hwnd)
        near = None
        if rc:
            fw, fh = st.frame_size
            x, y, w, h = seat.rect
            near = QPoint(rc[0] + int((x + w) * rc[2] / max(1, fw)), rc[1] + int(y * rc[3] / max(1, fh)))
        self.editor.open_for(name, p.color_slot if p else None, p.note if p else "",
                             self.db.history(name) if p else [], context=(hwnd, sid, editable),
                             editable_name=editable, hint=hint, near=near)

    def open_editor_for_name(self, name: str):
        p = self.db.get(name)
        self.editor.open_for(name, p.color_slot if p else None, p.note if p else "",
                             self.db.history(name), context=None)

    def _on_editor_saved(self, name: str, slot: int, note: str, context):
        if name == self.settings["my_nick"]:
            QMessageBox.warning(None, APP_NAME, "No puedes etiquetar tu propio nick.")
            return
        self.save_player(name, slot or None, note)
        if context and context[2]:
            hwnd, sid, _ = context
            self.worker.set_manual_name(hwnd, sid, name)
            self._on_table_updated(hwnd)

    def save_player(self, name: str, slot: int | None, note: str):
        self.db.save(name, slot, self.settings.palette_hex(slot), note)
        self.refresh_colors()  # inmediato: no espera al siguiente OCR


# ======================================================================
class SettingsDialog(QDialog):
    def __init__(self, settings: Settings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Ajustes de Nexa Notes")
        self.settings = settings
        self.palette = [list(p) for p in settings["palette"]]
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.proc = QLineEdit(", ".join(settings["process_keywords"]))
        self.proc.setToolTip("Texto que contiene el nombre del ejecutable de Nexa Poker (p. ej. nexa)")
        form.addRow("Proceso de Nexa contiene:", self.proc)
        self.title = QLineEdit(settings["title_keyword"])
        form.addRow("Título de mesa contiene:", self.title)
        self.tick = QDoubleSpinBox()
        self.tick.setRange(1.0, 10.0)
        self.tick.setSingleStep(0.5)
        self.tick.setValue(float(settings["analysis_tick_s"]))
        self.tick.setSuffix(" s")
        form.addRow("Intervalo entre análisis de mesas:", self.tick)
        self.ocr = QDoubleSpinBox()
        self.ocr.setRange(10.0, 120.0)
        self.ocr.setValue(float(settings["ocr_interval_s"]))
        self.ocr.setSuffix(" s")
        form.addRow("Relectura OCR de cada asiento:", self.ocr)
        self.btns = QCheckBox("Mostrar el botón de edición junto a cada jugador")
        self.btns.setChecked(bool(settings["show_edit_buttons"]))
        form.addRow(self.btns)
        lay.addLayout(form)
        box = QGroupBox("Colores (clic para cambiar el RGB)")
        g = QGridLayout(box)
        self.color_btns = []
        for i in range(10):
            b = QPushButton()
            b.clicked.connect(lambda _=False, i=i: self._pick(i))
            g.addWidget(b, i // 2, i % 2)
            self.color_btns.append(b)
        self._paint()
        lay.addWidget(box)
        reset = QPushButton("Restaurar colores predefinidos")
        reset.clicked.connect(self._reset)
        lay.addWidget(reset)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self._save)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _paint(self):
        for i, b in enumerate(self.color_btns):
            name, hx = self.palette[i]
            c = QColor(hx)
            b.setText(f"{i + 1}. {name}  RGB({c.red()}, {c.green()}, {c.blue()})")
            fg = "#000" if c.lightness() > 140 else "#fff"
            b.setStyleSheet(f"background:{hx}; color:{fg}; padding:6px;")

    def _pick(self, i):
        c = QColorDialog.getColor(QColor(self.palette[i][1]), self, f"Color {i + 1}")
        if c.isValid():
            self.palette[i][1] = c.name()
            self._paint()

    def _reset(self):
        self.palette = [list(p) for p in DEFAULT_PALETTE]
        self._paint()

    def _save(self):
        kws = [k.strip() for k in self.proc.text().split(",") if k.strip()]
        if not kws or not self.title.text().strip():
            QMessageBox.warning(self, "Ajustes", "El proceso y la palabra del título no pueden estar vacíos.")
            return
        s = self.settings
        s.data.update({"process_keywords": kws, "title_keyword": self.title.text().strip(),
                       "analysis_tick_s": self.tick.value(), "ocr_interval_s": self.ocr.value(),
                       "show_edit_buttons": self.btns.isChecked(), "palette": self.palette})
        s.save()
        self.accept()


# ======================================================================
class DiagnosticsWindow(QWidget):
    def __init__(self, ctl: Controller):
        super().__init__(None, Qt.WindowType.Window)
        self.ctl = ctl
        self.setWindowTitle("Nexa Notes — Diagnóstico")
        self.resize(760, 620)
        lay = QVBoxLayout(self)
        row = QHBoxLayout()
        b1 = QPushButton("Probar con captura…")
        b1.clicked.connect(self.test_capture)
        b2 = QPushButton("Abrir carpeta de datos")
        b2.clicked.connect(lambda: os.startfile(str(APP_DIR)) if hasattr(os, "startfile") else None)
        row.addWidget(b1)
        row.addWidget(b2)
        row.addStretch()
        lay.addLayout(row)
        self.text = QTextBrowser()
        lay.addWidget(self.text)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)

    def showEvent(self, e):
        self.refresh()
        self.timer.start(2000)  # solo mientras la ventana está abierta
        super().showEvent(e)

    def hideEvent(self, e):
        self.timer.stop()
        super().hideEvent(e)

    def refresh(self):
        c = self.ctl
        e = html.escape
        out = [f"<h3>{APP_NAME} {VERSION}</h3>"]
        out.append(f"<p>Pantalla: {e(winapi.dpi_awareness())} · capturas de diagnóstico en "
                   f"{e(str(APP_DIR / 'diagnostico'))}</p>")
        out.append(f"<p>OCR: {'error: ' + e(c.ocr.init_error) if c.ocr.init_error else 'listo'} · "
                   f"reconocimiento {'activado' if c.settings['recognition_enabled'] else 'desactivado'} · "
                   f"último error de análisis: {e(c.worker.last_error) or 'ninguno'} · "
                   f"último error de superposición: {e(c.ui_error) or 'ninguno'}</p>")
        out.append("<h4>Mesas identificadas</h4>")
        if not c.overlays:
            out.append("<p>Ninguna.</p>")
        for h in list(c.overlays):
            st = c.worker.snapshot(h)
            if not st:
                continue
            ago = f"{time.monotonic() - st.last_analysis:.0f} s" if st.last_analysis else "pendiente"
            out.append(f"<p><b>{e(st.title)}</b><br>proceso: {e(st.exe)} · ventana {h} · último análisis: {ago}"
                       f" · captura: {e(st.method)} · tiempos: {e(str(st.timings))}"
                       f"{'<br><span style=color:#c00>' + e(st.skipped or st.error) + '</span>' if (st.skipped or st.error) else ''}</p>")
            ov = c.overlays.get(h)
            if ov is not None:
                activos = [x for x in c.strips.get(h, []) if x.active]
                botones = [b for b in c.buttons.get(h, []) if b.sid]
                out.append(f"<p>Etiquetas visibles en pantalla (no tapadas): {c.visible_count.get(h, 0)} de "
                           f"{len(st.view)} · tiras de color activas: {len(activos)} (mostradas "
                           f"{sum(x.isVisible() for x in activos)}) · botones: {len(botones)} (mostrados "
                           f"{sum(b.isVisible() for b in botones)})"
                           f"{' · primera tira ' + str(activos[0].geometry().getRect()) if activos else ''}"
                           f" · mesa en {c.geom.get(h)}</p>")
            out.append("<table border=1 cellspacing=0 cellpadding=3><tr><th>Asiento</th><th>Estado</th>"
                       "<th>Identidad</th><th>Última lectura OCR</th><th>Etiqueta (x,y,w,h)</th><th>Eventos</th></tr>")
            for s in st.view:
                out.append(f"<tr><td>{s.sid}</td><td>{e(s.status)}</td><td>{e(s.display_name or '-')}</td>"
                           f"<td>{e(s.last_text)} [{e(s.last_kind)} {s.last_score:.2f}]</td><td>{s.rect}</td>"
                           f"<td>{'<br>'.join(e(x) for x in s.events)}</td></tr>")
            out.append("</table>")
            if st.detection and st.detection.rejected:
                out.append("<p>Descartadas: " + "; ".join(
                    f"{r} → {e(why)}" for r, why in st.detection.rejected[:15]) + "</p>")
            ev = st.tracker.events[-8:]
            if ev:
                out.append("<p style='color:#555'>" + "<br>".join(e(x) for x in ev) + "</p>")
        out.append("<h4>Ventanas descartadas en la última búsqueda</h4><ul>")
        for w, why in c.last_scan_rejected[:30]:
            out.append(f"<li>{e(w.title[:80])} — proceso {e(w.exe)} — {e(why)}</li>")
        out.append("</ul>")
        self.text.setHtml("".join(out))

    def test_capture(self):
        path, _ = QFileDialog.getOpenFileName(self, "Captura de una mesa", "", "Imágenes (*.png *.jpg *.jpeg *.bmp)")
        if not path:
            return
        from .analysis import analyze_file
        try:
            res = analyze_file(path, self.ctl.ocr)
        except Exception as ex:
            QMessageBox.warning(self, "Diagnóstico", str(ex))
            return
        lines = [f"Etiquetas detectadas: {len(res['etiquetas'])}"]
        for i, e in enumerate(res["etiquetas"], 1):
            lines.append(f"{i}. {e.get('texto', '')}  [{e.get('tipo', '')} {e.get('confianza', 0)}]  {e['etiqueta']}")
        lines.append(f"Descartadas: {len(res['descartadas'])}")
        for d in res["descartadas"]:
            lines.append(f"   {d['zona']} → {d['motivo']}")
        lines.append(f"Tiempos: {res['tiempos_ms']}")
        dlg = QDialog(self)
        dlg.setWindowTitle("Resultado de la captura")
        v = QVBoxLayout(dlg)
        img = QLabel()
        pm = QPixmap(res["imagen_diagnostico"])
        img.setPixmap(pm.scaledToWidth(min(900, pm.width()), Qt.TransformationMode.SmoothTransformation))
        v.addWidget(img)
        t = QTextEdit("\n".join(lines))
        t.setReadOnly(True)
        v.addWidget(t)
        v.addWidget(QLabel(f"Guardado en: {res['imagen_diagnostico']}"))
        dlg.exec()


# ======================================================================
class MainWindow(QMainWindow):
    def __init__(self, settings: Settings, db: Database, ctl: Controller):
        super().__init__()
        self.settings, self.db, self.ctl = settings, db, ctl
        self.selected_slot: int | None = None
        self.current: str | None = None
        self.diag_win: DiagnosticsWindow | None = None
        self.setWindowTitle(f"{APP_NAME} {VERSION}")
        icon = resource_path("assets/icon.ico")
        if icon.exists():
            self.setWindowIcon(QIcon(str(icon)))
        self.resize(820, 620)
        root = QWidget()
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)

        head = QHBoxLayout()
        logo = QLabel()
        lp = resource_path("assets/logo.png")
        if lp.exists():
            logo.setPixmap(QPixmap(str(lp)).scaledToHeight(48, Qt.TransformationMode.SmoothTransformation))
        head.addWidget(logo)
        t = QLabel(f"<b style='font-size:20px'>{APP_NAME}</b><br><span style='color:#888'>versión {VERSION}</span>")
        head.addWidget(t)
        head.addStretch()
        self.nick_label = QLabel()
        head.addWidget(self.nick_label)
        b = QPushButton("Cambiar mi nick")
        b.clicked.connect(self.change_nick)
        head.addWidget(b)
        outer.addLayout(head)

        status = QHBoxLayout()
        self.status_label = QLabel()
        status.addWidget(self.status_label)
        status.addStretch()
        self.rec_chk = QCheckBox("Reconocimiento activado")
        self.rec_chk.setChecked(bool(settings["recognition_enabled"]))
        self.rec_chk.toggled.connect(self.toggle_recognition)
        status.addWidget(self.rec_chk)
        self.diag_chk = QCheckBox("Modo diagnóstico")
        self.diag_chk.setChecked(bool(settings["diagnostic"]))
        self.diag_chk.toggled.connect(self.toggle_diag)
        status.addWidget(self.diag_chk)
        bd = QPushButton("Ventana de diagnóstico")
        bd.clicked.connect(self.show_diag)
        status.addWidget(bd)
        bs = QPushButton("Ajustes")
        bs.clicked.connect(self.show_settings)
        status.addWidget(bs)
        outer.addLayout(status)

        body = QHBoxLayout()
        outer.addLayout(body, 1)
        left = QVBoxLayout()
        body.addLayout(left, 2)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Buscar jugador o nota…")
        self.search.textChanged.connect(lambda: self.refresh_list(self.current))
        left.addWidget(self.search)
        self.list = QListWidget()
        self.list.currentItemChanged.connect(self._on_select)
        left.addWidget(self.list)
        row = QHBoxLayout()
        add = QPushButton("Añadir jugador")
        add.clicked.connect(self.add_player)
        dele = QPushButton("Eliminar jugador")
        dele.clicked.connect(self.delete_player)
        row.addWidget(add)
        row.addWidget(dele)
        left.addLayout(row)

        right = QVBoxLayout()
        body.addLayout(right, 3)
        self.player_label = QLabel("Selecciona un jugador")
        self.player_label.setStyleSheet("font-size:15px; font-weight:600;")
        right.addWidget(self.player_label)
        grid = QGridLayout()
        self.color_buttons: list[ColorButton] = []
        for i in range(10):
            cb = ColorButton(i + 1, "#fff", "")
            cb.clicked.connect(lambda _=False, s=i + 1: self.choose_color(s))
            grid.addWidget(cb, i // 5, i % 5)
            self.color_buttons.append(cb)
        right.addLayout(grid)
        clear = QPushButton("Quitar color (mantener notas)")
        clear.clicked.connect(lambda: self.choose_color(None))
        right.addWidget(clear)
        right.addWidget(QLabel("Notas del jugador"))
        self.notes = QTextEdit()
        self.notes.setPlaceholderText("Escribe tus notas aquí…")
        right.addWidget(self.notes, 1)
        right.addWidget(QLabel("Notas anteriores"))
        self.hist = QTextBrowser()
        self.hist.setMaximumHeight(110)
        right.addWidget(self.hist)
        save = QPushButton("Guardar color y notas")
        save.clicked.connect(self.save_player)
        right.addWidget(save)

        self.statusBar().showMessage(f"Datos: {DB_PATH}")
        ctl.tables_changed.connect(lambda _n: self.update_status())
        ctl.colors_changed.connect(lambda: self.refresh_list(self.current))
        self.paint_colors()
        self.refresh_list()
        self.update_nick_label()
        self.update_status()

    # ---------------------------------------------------------------
    def update_status(self):
        on = self.settings["recognition_enabled"]
        err = self.ctl.ocr.init_error
        st = "error del OCR" if err else ("activo" if on else "en pausa")
        self.status_label.setText(f"Detector: <b>{st}</b> · Mesas detectadas: <b>{self.ctl.table_count()}</b>")

    def update_nick_label(self):
        self.nick_label.setText("Mi nick: <b>" + html.escape(self.settings["my_nick"] or "(sin configurar)") + "</b>")

    def change_nick(self, initial=False):
        nick, ok = QInputDialog.getText(self, "Configuración inicial" if initial else "Cambiar nick",
                                        "Introduce tu nick exacto de Nexa Poker:", text=self.settings["my_nick"])
        if ok and nick.strip():
            self.settings["my_nick"] = nick.strip()
            self.update_nick_label()
            self.ctl.refresh_colors()

    def toggle_recognition(self, on):
        self.settings["recognition_enabled"] = on
        if on:
            self.ctl.worker.poke()
        self.update_status()

    def toggle_diag(self, on):
        self.ctl.set_diagnostic(on)

    def show_diag(self):
        if self.diag_win is None:
            self.diag_win = DiagnosticsWindow(self.ctl)
        self.diag_win.show()
        self.diag_win.raise_()

    def show_settings(self):
        if SettingsDialog(self.settings, self).exec():
            self.ctl.scan_timer.setInterval(int(float(self.settings["window_scan_s"]) * 1000))
            with self.ctl.worker.lock:
                for st in self.ctl.worker.tables.values():
                    st.tracker.ocr_interval_s = float(self.settings["ocr_interval_s"])
            self.paint_colors()
            self.ctl.refresh_colors()
            self.ctl.scan()

    def paint_colors(self):
        pal = self.settings["palette"]
        for b in self.color_buttons:
            b.setToolTip(f"{b.slot}. {pal[b.slot - 1][0]}")
            b.set_color(pal[b.slot - 1][1], b.slot == self.selected_slot)

    # ---------------------------------------------------------------
    def refresh_list(self, select=None):
        self.list.blockSignals(True)
        self.list.clear()
        for p in self.db.list(self.search.text().strip()):
            it = QListWidgetItem(p.nickname)
            col = self.settings.palette_hex(p.color_slot) or p.color
            if col:
                it.setText("● " + p.nickname)
                it.setForeground(QColor(col))
            it.setData(Qt.ItemDataRole.UserRole, p.nickname)
            self.list.addItem(it)
            if p.nickname == select:
                self.list.setCurrentItem(it)
        self.list.blockSignals(False)

    def _on_select(self, it, _prev=None):
        if not it:
            return
        nick = it.data(Qt.ItemDataRole.UserRole)
        p = self.db.get(nick)
        if not p:
            return
        self.current = nick
        self.selected_slot = p.color_slot
        self.player_label.setText("Jugador: " + nick)
        self.notes.setPlainText(p.note)
        hist = self.db.history(nick)
        self.hist.setHtml("".join(f"<p><span style='color:#888'>{t}</span><br>{html.escape(n)}</p>" for t, n in hist)
                          or "<p style='color:#888'>Sin notas anteriores</p>")
        self.paint_colors()

    def choose_color(self, slot):
        self.selected_slot = slot
        self.paint_colors()

    def add_player(self):
        nick, ok = QInputDialog.getText(self, "Añadir jugador", "Nombre exacto del jugador:")
        if not ok or not nick.strip():
            return
        nick = nick.strip()
        if nick == self.settings["my_nick"]:
            QMessageBox.warning(self, "Tu usuario", "No puedes etiquetar tu propio nick.")
            return
        self.db.ensure(nick)
        self.refresh_list(nick)

    def delete_player(self):
        if not self.current:
            return
        if QMessageBox.question(self, "Eliminar jugador",
                                f"¿Eliminar a «{self.current}» con su color y todas sus notas?\n"
                                "Esta acción no se puede deshacer.") != QMessageBox.StandardButton.Yes:
            return
        self.db.delete(self.current)
        self.current = None
        self.player_label.setText("Selecciona un jugador")
        self.notes.clear()
        self.hist.clear()
        self.ctl.refresh_colors()

    def save_player(self):
        if not self.current:
            QMessageBox.information(self, "Selecciona jugador", "Añade o selecciona un jugador primero.")
            return
        self.ctl.save_player(self.current, self.selected_slot, self.notes.toPlainText())
        self._on_select(self.list.currentItem())
        self.statusBar().showMessage(f"Guardado: {self.current}", 5000)

    def closeEvent(self, e):
        if self.diag_win:
            self.diag_win.close()
        self.ctl.editor.close()
        super().closeEvent(e)
