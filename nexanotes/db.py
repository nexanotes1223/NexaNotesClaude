"""Base de datos SQLite de jugadores, colores y notas.

Compatible con la base de datos de las versiones anteriores:
    players(nickname TEXT PRIMARY KEY, color TEXT, note TEXT NOT NULL DEFAULT "")
La migración solo AÑADE columnas y tablas; nunca borra ni renombra datos.
Antes de migrar se crea una copia de seguridad del archivo.
"""
from __future__ import annotations

import logging
import shutil
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

SCHEMA_VERSION = 2


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


@dataclass
class Player:
    nickname: str
    color: str | None       # hexadecimal guardado (compatibilidad)
    color_slot: int | None  # 1..10 dentro de la paleta configurable
    note: str


class Database:
    def __init__(self, path: Path, palette_hex: list[str]):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.migrated_backup: Path | None = None
        self._backup_if_needed()
        self.con = sqlite3.connect(str(self.path))
        self.con.execute("PRAGMA journal_mode=WAL")
        self.migrate(palette_hex)

    # ------------------------------------------------------------ migración
    def _backup_if_needed(self):
        if not self.path.exists():
            return
        try:
            con = sqlite3.connect(str(self.path))
            ver = con.execute("PRAGMA user_version").fetchone()[0]
            con.close()
        except sqlite3.Error:
            log.exception("No se pudo leer la versión de la base de datos")
            return
        if ver < SCHEMA_VERSION:
            dst = self.path.with_name(f"jugadores.backup-v{ver}-{time.strftime('%Y%m%d-%H%M%S')}.db")
            shutil.copy2(self.path, dst)
            self.migrated_backup = dst
            log.info("Copia de seguridad antes de migrar: %s", dst)

    def migrate(self, palette_hex: list[str]):
        c = self.con
        c.execute(
            "CREATE TABLE IF NOT EXISTS players ("
            "nickname TEXT PRIMARY KEY, color TEXT, note TEXT NOT NULL DEFAULT '')"
        )
        cols = {r[1] for r in c.execute("PRAGMA table_info(players)")}
        if "color_slot" not in cols:
            c.execute("ALTER TABLE players ADD COLUMN color_slot INTEGER")
            # Asociar los colores hexadecimales antiguos a su posición en la paleta.
            lower = [h.lower() for h in palette_hex]
            for nick, color in c.execute("SELECT nickname, color FROM players").fetchall():
                if color and color.lower() in lower:
                    c.execute("UPDATE players SET color_slot=? WHERE nickname=?",
                              (lower.index(color.lower()) + 1, nick))
        if "created_at" not in cols:
            c.execute("ALTER TABLE players ADD COLUMN created_at TEXT")
        if "updated_at" not in cols:
            c.execute("ALTER TABLE players ADD COLUMN updated_at TEXT")
        if "last_seen" not in cols:
            c.execute("ALTER TABLE players ADD COLUMN last_seen TEXT")
        c.execute(
            "CREATE TABLE IF NOT EXISTS note_history ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, nickname TEXT NOT NULL, "
            "note TEXT NOT NULL, saved_at TEXT NOT NULL)"
        )
        c.execute("CREATE INDEX IF NOT EXISTS idx_hist_nick ON note_history(nickname)")
        c.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
        c.commit()

    # ------------------------------------------------------------ consultas
    def get(self, nick: str) -> Player | None:
        r = self.con.execute(
            "SELECT nickname, color, color_slot, note FROM players WHERE nickname=?", (nick,)
        ).fetchone()
        return Player(*r) if r else None

    def list(self, search: str = "") -> list[Player]:
        q = "SELECT nickname, color, color_slot, note FROM players"
        args: tuple = ()
        if search:
            q += " WHERE nickname LIKE ? OR note LIKE ?"
            like = f"%{search}%"
            args = (like, like)
        q += " ORDER BY nickname COLLATE NOCASE"
        return [Player(*r) for r in self.con.execute(q, args)]

    def colored_map(self) -> dict[str, tuple[int | None, str | None]]:
        """nickname -> (slot, hex) de los jugadores con color asignado (caché del overlay)."""
        out = {}
        for nick, color, slot in self.con.execute(
            "SELECT nickname, color, color_slot FROM players WHERE color_slot IS NOT NULL OR color IS NOT NULL"
        ):
            out[nick] = (slot, color)
        return out

    def ensure(self, nick: str) -> None:
        self.con.execute(
            "INSERT OR IGNORE INTO players (nickname, color, note, created_at, updated_at) "
            "VALUES (?, NULL, '', ?, ?)", (nick, _now(), _now()))
        self.con.commit()

    def save(self, nick: str, slot: int | None, hex_color: str | None, note: str) -> None:
        """Guarda color y nota. Si la nota cambia, la anterior pasa al historial."""
        self.ensure(nick)
        old = self.get(nick)
        if old and old.note.strip() and old.note != note:
            self.con.execute("INSERT INTO note_history (nickname, note, saved_at) VALUES (?, ?, ?)",
                             (nick, old.note, _now()))
        self.con.execute(
            "UPDATE players SET color=?, color_slot=?, note=?, updated_at=? WHERE nickname=?",
            (hex_color or None, slot, note, _now(), nick))
        self.con.commit()

    def set_color(self, nick: str, slot: int | None, hex_color: str | None) -> None:
        self.ensure(nick)
        self.con.execute("UPDATE players SET color=?, color_slot=?, updated_at=? WHERE nickname=?",
                         (hex_color, slot, _now(), nick))
        self.con.commit()

    def history(self, nick: str) -> list[tuple[str, str]]:
        return [(t, n) for t, n in self.con.execute(
            "SELECT saved_at, note FROM note_history WHERE nickname=? ORDER BY id DESC", (nick,))]

    def delete(self, nick: str) -> None:
        self.con.execute("DELETE FROM players WHERE nickname=?", (nick,))
        self.con.execute("DELETE FROM note_history WHERE nickname=?", (nick,))
        self.con.commit()

    def touch_seen(self, nick: str) -> None:
        self.con.execute("UPDATE players SET last_seen=? WHERE nickname=?", (_now(), nick))
        self.con.commit()

    def close(self):
        try:
            self.con.close()
        except Exception:
            pass
