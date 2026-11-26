from nexanotes import textrules as tr


def test_nombres():
    for t in ["DuDu29", "烧烤哥弟", "one01s", "AhyeonBaby", "x_Pro-99", "123456", "嘉禄", "fire161", "Betty77"]:
        assert tr.classify(t, 0.95)[0] == tr.NAME, t


def test_timebank():
    for t in ["12", "5", "0:15", "15s", "9", "時10時", "12個"]:
        assert tr.classify(t, 0.95)[0] == tr.TIMEBANK, t


def test_acciones():
    for t in ["All in", "ALL-IN", "Fold", "Check", "Call", "Sitting Out", "Call 0.5BB", "Raise 2BB"]:
        assert tr.classify(t, 0.95)[0] == tr.ACTION, t


def test_cantidades_no_son_nombres():
    for t in ["9.8BB", "13.2 BB", "¥1,372", "20,2BB", "1.5K"]:
        assert tr.classify(t, 0.95)[0] == tr.NOISE, t


def test_truncados():
    assert tr.classify("AhyeonB...", 0.95) == (tr.TRUNCATED, "AhyeonB")
    assert tr.classify("烧烤…", 0.95) == (tr.TRUNCATED, "烧烤")


def test_baja_confianza():
    assert tr.classify("DuDu29", 0.3)[0] == tr.NOISE


def test_mismo_jugador_con_error_menor():
    assert tr.same_player_text("AhyeonBaby", "AhyeonBabv")
    assert not tr.same_player_text("DuDu29", "DuDu28x")
    assert not tr.same_player_text("one01s", "VETEMENTS")
