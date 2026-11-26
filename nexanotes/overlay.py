"""Superposición transparente sobre cada mesa.

Cada mesa tiene:
  * TableOverlay: ventana transparente del tamaño del área cliente, que NO recibe
    clics ni foco (WS_EX_TRANSPARENT | WS_EX_NOACTIVATE). Dibuja los rectángulos.
  * SeatButton: botón diminuto junto a cada etiqueta reconocida, que abre el
    editor. Es la única zona interactiva y está fuera del nickname, las fichas
    y los botones del cliente.
Las dos son ventanas "propiedad" (owned) de la mesa: Windows las mantiene justo
encima de su mesa en el orden de ventanas, las tapa cuando otra ventana tapa la
mesa y las oculta cuando la mesa se minimiza.
"""
from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QWidget

from . import winapi
from .tracker import UNCERTAIN


def _apply_owner(widget: QWidget, owner_hwnd: int, click_through: bool):
    hwnd = int(widget.winId())
    winapi.set_owner(hwnd, owner_hwnd)
    flags = winapi.WS_EX_NOACTIVATE | winapi.WS_EX_TOOLWINDOW
    if click_through:
        flags |= winapi.WS_EX_LAYERED | winapi.WS_EX_TRANSPARENT
    winapi.add_ex_style(hwnd, flags, remove=winapi.WS_EX_TOPMOST)


class TableOverlay(QWidget):
    def __init__(self, table_hwnd: int):
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool
                         | Qt.WindowType.WindowTransparentForInput | Qt.WindowType.WindowDoesNotAcceptFocus
                         | Qt.WindowType.NoDropShadowWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.table_hwnd = table_hwnd
        self.view = ()
        self.frame_size = (1, 1)
        self.colors: dict[str, str] = {}
        self.my_nick = ""
        self.diagnostic = False
        self.rejected = []
        self.header = ""
        self._owned = False

    def ensure_owned(self):
        if not self._owned:
            _apply_owner(self, self.table_hwnd, click_through=True)
            self._owned = True

    def set_data(self, view, frame_size, colors, my_nick, diagnostic, rejected, header):
        self.view, self.frame_size, self.colors = view, frame_size, colors
        self.my_nick, self.diagnostic, self.rejected, self.header = my_nick, diagnostic, rejected, header
        self.update()

    def has_content(self) -> bool:
        if self.diagnostic:
            return True
        return any(self._color_for(s) for s in self.view)

    def _color_for(self, s) -> str | None:
        if s.status == UNCERTAIN or not s.display_name or s.display_name == self.my_nick:
            return None
        return self.colors.get(s.display_name)

    def _scale(self):
        fw, fh = self.frame_size
        return self.width() / max(1, fw), self.height() / max(1, fh)

    def _map(self, r):
        sx, sy = self._scale()
        x, y, w, h = r
        return QRectF(x * sx, y * sy, w * sx, h * sy)

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        for s in self.view:
            r = self._map(s.rect)
            col = self._color_for(s)
            if col:
                pw = max(2.0, round(r.width() * 0.03))
                pen = QPen(QColor(col), pw)
                pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
                p.setPen(pen)
                p.setBrush(Qt.BrushStyle.NoBrush)
                m = pw / 2 + 1  # por fuera de la etiqueta: no tapa texto
                p.drawRoundedRect(r.adjusted(-m, -m, m, m), r.height() * 0.12 + m, r.height() * 0.12 + m)
        if self.diagnostic:
            self._paint_diagnostic(p)
        p.end()

    def _paint_diagnostic(self, p: QPainter):
        f = QFont()
        f.setPixelSize(11)
        p.setFont(f)
        for r0, why in self.rejected[:20]:
            r = self._map(r0)
            p.setPen(QPen(QColor(255, 60, 60, 200), 1, Qt.PenStyle.DotLine))
            p.drawRect(r)
            p.drawText(r.bottomLeft() + QPoint(0, 11).toPointF(), why[:40])
        for s in self.view:
            r = self._map(s.rect)
            p.setPen(QPen(QColor(255, 255, 255, 220), 1, Qt.PenStyle.DashLine))
            p.drawRect(r)
            p.setPen(QPen(QColor(255, 230, 0, 220), 1))
            p.drawRect(self._map(s.name_rect))
            txt = f"#{s.sid} {s.status}: {s.display_name or s.last_text or '?'} ({s.last_score:.2f})"
            p.fillRect(QRectF(r.left(), r.bottom() + 2, max(r.width(), 7.0 * len(txt)), 14), QColor(0, 0, 0, 170))
            p.setPen(QColor(0, 255, 120))
            p.drawText(QRectF(r.left() + 2, r.bottom() + 2, 7.0 * len(txt) + 40, 14), txt)
        if self.header:
            lines = self.header.split("\n")
            p.fillRect(QRect(4, 4, 460, 15 * len(lines) + 6), QColor(0, 0, 0, 180))
            p.setPen(QColor(0, 255, 120))
            for i, line in enumerate(lines):
                p.drawText(QPoint(10, 18 + 15 * i), line)


class SeatButton(QWidget):
    clicked = Signal(int, int)  # table_hwnd, seat id

    def __init__(self, table_hwnd: int):
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool
                         | Qt.WindowType.WindowDoesNotAcceptFocus | Qt.WindowType.NoDropShadowWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.table_hwnd = table_hwnd
        self.sid = 0
        self.color: str | None = None
        self.hover = False
        self._owned = False
        self.setToolTip("Nexa Notes: color y notas")

    def ensure_owned(self):
        if not self._owned:
            _apply_owner(self, self.table_hwnd, click_through=False)
            self._owned = True

    def enterEvent(self, _e):
        self.hover = True
        self.update()

    def leaveEvent(self, _e):
        self.hover = False
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.table_hwnd, self.sid)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(1, 1, self.width() - 2, self.height() - 2)
        p.setBrush(QColor(30, 34, 42, 235 if self.hover else 200))
        p.setPen(QPen(QColor(self.color) if self.color else QColor(150, 155, 165), 1.5))
        p.drawEllipse(r)
        # icono de lápiz sencillo
        c = r.center()
        s = r.width() * 0.22
        p.setPen(QPen(QColor(235, 235, 235), max(1.2, r.width() * 0.09), Qt.PenStyle.SolidLine,
                      Qt.PenCapStyle.RoundCap))
        p.drawLine(c.x() - s, c.y() + s, c.x() + s, c.y() - s)
        p.end()
