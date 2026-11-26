"""OCR solo en la zona del nickname (nombres latinos y chinos)."""
import pytest

from conftest import load
from nexanotes.analysis import SELFTEST_EXPECTED, analyze_image
from nexanotes.detector import crop, detect_labels


@pytest.mark.parametrize("name", ["MesaNexa.png", "MesaNexafinal.png"])
def test_lee_todos_los_nombres(name, ocr):
    res = analyze_image(load(name), ocr)
    names = [e["texto"] for e in res["etiquetas"]]
    assert sorted(names) == sorted(SELFTEST_EXPECTED)
    assert all(e["tipo"] == "name" for e in res["etiquetas"])


def test_no_lee_fichas_ni_avatar(ocr):
    img = load("MesaNexa.png")
    for lab in detect_labels(img).labels:
        text, _ = ocr.recognize(crop(img, lab.name_rect))
        assert "BB" not in text
        assert "School" not in text
