"""Superposición transparente sobre cada mesa.

Cada mesa tiene:
  * TableOverlay: ventana transparente del tamaño del área cliente, que NO recibe
    clics ni foco (WS_EX_TRANSPARENT | WS_EX_NOACTIVATE). Dibuja los rectángulos.
  * SeatButton: botón diminuto junto a cada etiqueta reconocida, que abre el
    editor. Es la única zona interactiva y está fuera del nickname, las fichas
    y los botones del cliente.
Las dos se colocan justo encima de su mesa en el orden de ventanas (sin
activarse): quedan tapadas por las mismas ventanas que tapan la mesa, y se
ocultan cuando la mesa se minimiza o se cierra.
"""
from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QWidget

from . import winapi
from .tracker import UNCERTAIN


def _prepare_native(widget: QWidget, exclude_capture: bool):
    """Estilos de Windows: sin activar ni robar el foco, fuera de la barra de tareas
    y, para el dibujo, transparente a los clics. El orden respecto a la mesa se
    ajusta después con winapi.place_just_above()."""
    hwnd = int(widget.winId())
    # Importante: NO se añade WS_EX_LAYERED a mano. Qt ya prepara la ventana
    # transparente; marcarla como "layered" por nuestra cuenta la vuelve invisible
    # (era el fallo de la 0.13.1: se veían los botones pero no los rectángulos).
    # Que los clics atraviesen el dibujo lo hace Qt con WindowTransparentForInput.
    winapi.add_ex_style(hwnd, winapi.WS_EX_NOACTIVATE | winapi.WS_EX_TOOLWINDOW, remove=winapi.WS_EX_TOPMOST)
    winapi.exclude_from_capture(hwnd, exclude_capture)
    return hwnd


class TableOverlay(QWidget):
    """Dibujo del modo diagnóstico (ventana transparente que deja pasar los clics).
    Los rectángulos de color NO se dibujan aquí, sino con BorderStrip (más fiable)."""

    def __init__(self, table_hwnd: int):
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool
                         | Qt.WindowType.WindowDoesNotAcceptFocus | Qt.WindowType.NoDropShadowWindowHint)
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
        self.native = 0

    def ensure_owned(self):
        if not self._owned:
            self.native = _prepare_native(self, exclude_capture=not self.diagnostic)
            # La transparencia de Qt ya la hace "layered"; con WS_EX_TRANSPARENT los
            # clics la atraviesan y llegan a la mesa.
            st = winapi.ex_style(self.native)
            if st & winapi.WS_EX_LAYERED:
                winapi.add_ex_style(self.native, winapi.WS_EX_TRANSPARENT)
            self._owned = True

    def set_capture_exclusion(self):
        if self._owned:
            winapi.exclude_from_capture(self.native, not self.diagnostic)

    def set_data(self, view, frame_size, colors, my_nick, diagnostic, rejected, header):
        self.view, self.frame_size, self.colors = view, frame_size, colors
        self.my_nick, self.diagnostic, self.rejected, self.header = my_nick, diagnostic, rejected, header
        self.update()

    def has_content(self) -> bool:
        return self.diagnostic

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
        self.native = 0
        self.setToolTip("Nexa Notes: color y notas")

    def ensure_owned(self):
        if not self._owned:
            self.native = _prepare_native(self, exclude_capture=True)
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


class BorderStrip(QWidget):
    """Una de las cuatro tiras de color que forman el rectángulo alrededor de una
    etiqueta. Ventana normal de color sólido (sin transparencias), situada por
    fuera de la etiqueta: no tapa el nickname, las fichas ni el bounty."""

    def __init__(self, table_hwnd: int):
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool
                         | Qt.WindowType.WindowDoesNotAcceptFocus | Qt.WindowType.NoDropShadowWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.table_hwnd = table_hwnd
        self.color = "#ffffff"
        self.active = False
        self._owned = False
        self.native = 0

    def set_color(self, col: str):
        if col != self.color:
            self.color = col
            self.update()

    def ensure_owned(self):
        if not self._owned:
            self.native = _prepare_native(self, exclude_capture=True)
            self._owned = True

    def paintEvent(self, _e):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(self.color))
        p.end()
