"""Editor rápido de color y notas (se abre desde la mesa o desde la ventana principal)."""
from __future__ import annotations

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import (QCompleter, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
                               QPushButton, QTextBrowser, QTextEdit, QVBoxLayout, QWidget)

STYLE = """
QWidget#editor { background: #1f2430; border: 1px solid #3a4150; border-radius: 12px; }
QLabel { color: #e5e7eb; }
QLabel#title { font-size: 15px; font-weight: 600; }
QLabel#muted { color: #9ca3af; font-size: 12px; }
QLineEdit, QTextEdit, QTextBrowser { background: #171b24; color: #f3f4f6; border: 1px solid #3a4150;
    border-radius: 8px; padding: 6px; font-size: 13px; }
QPushButton#close { background: transparent; color: #9ca3af; border: none; font-size: 16px; }
QPushButton#close:hover { color: white; }
QPushButton#secondary { background: transparent; color: #e5e7eb; border: 1px solid #4b5263;
    border-radius: 16px; padding: 7px 14px; font-weight: 600; }
QPushButton#primary { background: #f3f4f6; color: #111827; border: none; border-radius: 16px;
    padding: 7px 14px; font-weight: 700; }
QPushButton#link { background: transparent; color: #93c5fd; border: none; text-align: left; }
"""


class ColorButton(QPushButton):
    def __init__(self, slot: int, hexcol: str, name: str):
        super().__init__()
        self.slot = slot
        self.setFixedSize(46, 34)
        self.setToolTip(f"{slot}. {name}")
        self.set_color(hexcol, False)

    def set_color(self, hexcol: str, selected: bool):
        self.hexcol = hexcol
        border = "2px solid #f9fafb" if selected else "1px solid #3a4150"
        self.setText("●")
        self.setStyleSheet(f"QPushButton {{ background: #171b24; border: {border}; border-radius: 9px; "
                           f"color: {hexcol}; font-size: 22px; padding: 0; }}")


class PlayerEditor(QWidget):
    """Señal saved(nombre, slot o 0, nota, contexto)."""
    saved = Signal(str, int, str, object)

    def __init__(self, palette_getter, names_getter):
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool
                         | Qt.WindowType.WindowStaysOnTopHint)
        self.setObjectName("editor")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.setStyleSheet(STYLE)
        self.setFixedWidth(320)
        self.palette_getter = palette_getter
        self.names_getter = names_getter
        self.context = None
        self.slot = 0
        self._drag = None

        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 14)
        top = QHBoxLayout()
        t = QLabel("Editar jugador")
        t.setObjectName("title")
        top.addWidget(t)
        top.addStretch()
        x = QPushButton("✕")
        x.setObjectName("close")
        x.clicked.connect(self.close)
        top.addWidget(x)
        lay.addLayout(top)

        self.name_label = QLabel()
        self.name_label.setStyleSheet("font-size: 14px; font-weight: 600;")
        lay.addWidget(self.name_label)
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Nombre completo del jugador")
        lay.addWidget(self.name_edit)
        self.hint = QLabel()
        self.hint.setObjectName("muted")
        self.hint.setWordWrap(True)
        lay.addWidget(self.hint)

        m = QLabel("Selecciona un color")
        m.setObjectName("muted")
        lay.addWidget(m)
        grid = QGridLayout()
        grid.setSpacing(6)
        self.color_buttons: list[ColorButton] = []
        for i in range(10):
            b = ColorButton(i + 1, "#ffffff", "")
            b.clicked.connect(lambda _=False, s=i + 1: self._choose(s))
            grid.addWidget(b, i // 5, i % 5)
            self.color_buttons.append(b)
        lay.addLayout(grid)

        m2 = QLabel("Notas del jugador")
        m2.setObjectName("muted")
        lay.addWidget(m2)
        self.notes = QTextEdit()
        self.notes.setFixedHeight(96)
        self.notes.setPlaceholderText("Escribe tus notas aquí…")
        lay.addWidget(self.notes)

        self.hist_btn = QPushButton()
        self.hist_btn.setObjectName("link")
        self.hist_btn.clicked.connect(self._toggle_history)
        lay.addWidget(self.hist_btn)
        self.hist = QTextBrowser()
        self.hist.setFixedHeight(90)
        self.hist.hide()
        lay.addWidget(self.hist)

        row = QHBoxLayout()
        clear = QPushButton("Quitar color")
        clear.setObjectName("secondary")
        clear.setToolTip("Quita el color y mantiene las notas")
        clear.clicked.connect(lambda: self._choose(0))
        save = QPushButton("Guardar")
        save.setObjectName("primary")
        save.clicked.connect(self._save)
        row.addWidget(clear)
        row.addWidget(save)
        lay.addLayout(row)
        QShortcut(QKeySequence("Esc"), self, activated=self.close)
        QShortcut(QKeySequence("Ctrl+Return"), self, activated=self._save)

    # arrastrar la ventana por cualquier zona libre
    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        if self._drag is not None:
            self.move(e.globalPosition().toPoint() - self._drag)

    def mouseReleaseEvent(self, _e):
        self._drag = None

    def _choose(self, slot: int):
        self.slot = slot
        pal = self.palette_getter()
        for b in self.color_buttons:
            name, hexcol = pal[b.slot - 1]
            b.setToolTip(f"{b.slot}. {name}")
            b.set_color(hexcol, b.slot == slot)

    def _toggle_history(self):
        self.hist.setVisible(not self.hist.isVisible())
        self.adjustSize()

    def open_for(self, name: str, slot: int | None, note: str, history: list[tuple[str, str]],
                 context=None, editable_name: bool = False, hint: str = "", near: QPoint | None = None):
        self.context = context
        self.name_label.setText(name or "")
        self.name_label.setVisible(not editable_name)
        self.name_edit.setVisible(editable_name)
        self.name_edit.setText(name or "")
        if editable_name:
            comp = QCompleter(self.names_getter())
            comp.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
            comp.setFilterMode(Qt.MatchFlag.MatchStartsWith)
            self.name_edit.setCompleter(comp)
        self.hint.setText(hint)
        self.hint.setVisible(bool(hint))
        self.notes.setPlainText(note or "")
        self._choose(slot or 0)
        self.hist.setHtml("".join(
            f"<p><span style='color:#9ca3af'>{t}</span><br>{_esc(n)}</p>" for t, n in history)
            or "<p style='color:#9ca3af'>Sin notas anteriores</p>")
        self.hist_btn.setText(f"Notas anteriores ({len(history)})")
        self.hist.hide()
        self.adjustSize()
        if near is not None:
            self._place_near(near)
        self.show()
        self.raise_()
        self.activateWindow()
        (self.name_edit if editable_name else self.notes).setFocus()

    def _place_near(self, pt: QPoint):
        scr = QGuiApplication.screenAt(pt) or QGuiApplication.primaryScreen()
        g = scr.availableGeometry()
        x = min(max(g.left(), pt.x() + 8), g.right() - self.width())
        y = min(max(g.top(), pt.y() + 8), g.bottom() - self.sizeHint().height())
        self.move(x, y)

    def _save(self):
        name = (self.name_edit.text() if self.name_edit.isVisible() else self.name_label.text()).strip()
        if not name:
            self.hint.setText("Escribe el nombre completo del jugador.")
            self.hint.show()
            return
        self.saved.emit(name, self.slot, self.notes.toPlainText(), self.context)
        self.close()


def _esc(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br>"))

