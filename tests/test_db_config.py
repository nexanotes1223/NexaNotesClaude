"""Base de datos: compatibilidad con la versión anterior y operaciones básicas."""
import sqlite3

from nexanotes.config import DEFAULT_PALETTE, Settings
from nexanotes.db import Database
from nexanotes.engine import match_tables
from nexanotes.winapi import WindowInfo

PAL = [h for _n, h in DEFAULT_PALETTE]


def old_db(path):
    c = sqlite3.connect(path)
    c.execute('CREATE TABLE IF NOT EXISTS players (nickname TEXT PRIMARY KEY, color TEXT, note TEXT NOT NULL DEFAULT "")')
    c.execute("INSERT INTO players VALUES ('DuDu29', '#ef4444', 'agresivo')")
    c.execute("INSERT INTO players VALUES ('烧烤哥弟', '#22c55e', '')")
    c.execute("INSERT INTO players VALUES ('one01s', NULL, 'pasivo')")
    c.commit()
    c.close()


def test_migracion_conserva_datos_y_hace_copia(tmp_path):
    p = tmp_path / "jugadores.db"
    old_db(p)
    db = Database(p, PAL)
    assert db.migrated_backup is not None and db.migrated_backup.exists()
    d = {x.nickname: x for x in db.list()}
    assert d["DuDu29"].color_slot == 1 and d["DuDu29"].note == "agresivo"
    assert d["烧烤哥弟"].color_slot == 4
    assert d["one01s"].color_slot is None and d["one01s"].note == "pasivo"
    db.close()
    # segunda apertura: no vuelve a migrar ni a copiar
    db2 = Database(p, PAL)
    assert db2.migrated_backup is None
    assert len(db2.list()) == 3


def test_historial_quitar_color_y_borrar(tmp_path):
    db = Database(tmp_path / "j.db", PAL)
    db.save("X", 3, PAL[2], "nota 1")
    db.save("X", 3, PAL[2], "nota 2")
    assert [n for _t, n in db.history("X")] == ["nota 1"]
    db.save("X", None, None, "nota 2")  # quitar color mantiene la nota
    p = db.get("X")
    assert p.color_slot is None and p.note == "nota 2"
    assert "X" not in db.colored_map()
    db.delete("X")
    assert db.get("X") is None and db.history("X") == []


def test_buscador(tmp_path):
    db = Database(tmp_path / "j.db", PAL)
    db.save("Alpha", 1, PAL[0], "farolea en river")
    db.save("Beta", None, None, "")
    assert [p.nickname for p in db.list("river")] == ["Alpha"]
    assert [p.nickname for p in db.list("bet")] == ["Beta"]


def test_settings_conserva_nick_antiguo(tmp_path):
    f = tmp_path / "config.json"
    f.write_text('{"my_nick": "Pau"}', encoding="utf-8")
    s = Settings(f)
    assert s["my_nick"] == "Pau"
    assert len(s["palette"]) == 10
    assert s.palette_hex(1) == "#ef4444"


def test_filtro_de_ventanas_exige_proceso_y_titulo():
    wins = [
        WindowInfo(1, "Torneo X - Blinds 100/200", 10, "NexaPoker.exe"),   # mesa
        WindowInfo(2, "Nexa Poker - Lobby", 10, "NexaPoker.exe"),          # lobby
        WindowInfo(3, "Otra sala - Blinds 50/100", 11, "OtherPoker.exe"),  # otra sala
        WindowInfo(4, "Blinds - Google Chrome", 12, "chrome.exe"),         # navegador
    ]
    tables, rejected = match_tables(wins, ["nexa"], "Blinds")
    assert [w.hwnd for w in tables] == [1]
    assert {w.hwnd for w, _ in rejected} == {2, 3, 4}
