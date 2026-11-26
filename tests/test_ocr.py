"""OCR solo en la zona del nickname (nombres latinos y chinos)."""
import pytest

from conftest import load
from nexanotes.analysis import SELFTEST_EXPECTED, analyze_image
from nexanotes.detector import crop, detect_labels


NAMES = {
    "MesaNexa.png": SELFTEST_EXPECTED,
    "MesaNexafinal.png": SELFTEST_EXPECTED,
    "MesaNexaReal2.png": ["ponchodeus", "TOTI20", "香酥腰果饼", "EricYANGAA", "SanGanchao"],
    "MesaNexaReal3.png": ["香酥腰果饼", "EricYANGAA", "fire161", "TOTI20", "你的刀疤哥", "SanGanchao"],
    "MesaNexaReal4.png": ["香酥腰果饼", "嘉禄", "fire161", "TOTI20", "你的刀疤哥", "SanGanchao"],
}


def test_timebank_con_iconos_no_es_nombre(ocr):
    """En MesaNexaReal3 un jugador muestra el contador del timebank: no debe leerse como nombre."""
    res = analyze_image(load("MesaNexaReal3.png"), ocr)
    kinds = [e["tipo"] for e in res["etiquetas"]]
    assert kinds.count("timebank") == 1


@pytest.mark.parametrize("name", list(NAMES))
def test_lee_todos_los_nombres(name, ocr):
    res = analyze_image(load(name), ocr)
    names = [e["texto"] for e in res["etiquetas"]]
    for n in NAMES[name]:
        assert n in names


def test_no_lee_fichas_ni_avatar(ocr):
    img = load("MesaNexa.png")
    for lab in detect_labels(img).labels:
        text, _ = ocr.recognize(crop(img, lab.name_rect))
        assert "BB" not in text
        assert "School" not in text
