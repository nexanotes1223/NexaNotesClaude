"""Detección de etiquetas con capturas reales de Nexa Poker."""
import cv2
import numpy as np
import pytest

from conftest import load
from nexanotes.detector import detect_labels

EXPECTED = {
    "MesaNexa.png": 7,        # mesa en pausa (oscurecida)
    "MesaNexafinal.png": 7,
    "MesaNexaReal2.png": 6,   # captura real de Windows: otro fondo, 6 jugadores, cartas en mesa
    "MesaNexaReal3.png": 7,   # captura hecha por el propio programa, con timebank en un jugador
    "MesaNexaReal4.png": 7,   # con los botones Fold / Call visibles (no son jugadores)
}


def _centers(det):
    return [(l.rect[0] + l.rect[2] / 2, l.rect[1] + l.rect[3] / 2) for l in det.labels]


@pytest.mark.parametrize("name,count", EXPECTED.items())
def test_cuenta_exacta(name, count):
    det = detect_labels(load(name))
    assert len(det.labels) == count


@pytest.mark.parametrize("name", EXPECTED)
@pytest.mark.parametrize("scale", [0.45, 0.6, 0.8, 1.25, 1.6, 2.0])
def test_distintos_tamanos_de_mesa(name, scale):
    img = load(name)
    interp = cv2.INTER_AREA if scale < 1 else cv2.INTER_CUBIC
    small = cv2.resize(img, None, fx=scale, fy=scale, interpolation=interp)
    det = detect_labels(small)
    assert len(det.labels) == EXPECTED[name]
    # proporción coherente con la etiqueta de Nexa (~2:1)
    for l in det.labels:
        assert 1.75 <= l.rect[2] / l.rect[3] <= 2.4


@pytest.mark.parametrize("name", EXPECTED)
def test_asiento_vacio_no_genera_rectangulo(name):
    """Se borra un jugador (avatar + etiqueta): debe quedar una etiqueta menos y
    ningún rectángulo en la zona vacía."""
    img = load(name)
    det = detect_labels(img)
    x, y, w, h = det.labels[0].rect
    mask = np.zeros(img.shape[:2], np.uint8)
    cv2.rectangle(mask, (x - 8, y - int(w * 0.9)), (x + w + 8, y + h + 8), 255, -1)
    empty = cv2.inpaint(img, mask, 5, cv2.INPAINT_TELEA)
    det2 = detect_labels(empty)
    assert len(det2.labels) == EXPECTED[name] - 1
    cx, cy = x + w / 2, y + h / 2
    for ox, oy in _centers(det2):
        assert abs(ox - cx) > w or abs(oy - cy) > h


@pytest.mark.parametrize("name", EXPECTED)
def test_rectangulos_ajustados_a_la_etiqueta(name):
    """El borde de cada etiqueta detectada debe ser oscuro por dentro y el
    rectángulo no debe incluir el avatar (filas superiores fuera de la etiqueta)."""
    img = load(name)
    v = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)[..., 2]
    for l in detect_labels(img).labels:
        x, y, w, h = l.rect
        inner_left = v[y + h // 4: y + 3 * h // 4, x + 2: x + 5]
        assert inner_left.mean() < 60
        nx, ny, nw, nh = l.name_rect
        assert ny >= y and ny + nh <= y + h // 2 + 2  # zona OCR = solo mitad superior


def test_imagen_sin_mesa_no_detecta_nada():
    rng = np.random.default_rng(0)
    noise = rng.integers(0, 255, (600, 900, 3), dtype=np.uint8)
    assert detect_labels(noise).labels == []
    assert detect_labels(np.zeros((600, 900, 3), np.uint8)).labels == []
    assert detect_labels(np.full((600, 900, 3), 255, np.uint8)).labels == []


# ---------------------------------------------------------------------------
# Capturas adicionales: guarda en tests/capturas/extra/ archivos con el número
# de jugadores esperado al final del nombre, por ejemplo:
#     mesa_6max_vacios_4.png   -> se esperan exactamente 4 etiquetas
from conftest import CAPTURAS  # noqa: E402

EXTRA = sorted((CAPTURAS / "extra").glob("*_[0-9].png"))


@pytest.mark.parametrize("path", EXTRA, ids=[p.name for p in EXTRA])
def test_capturas_adicionales(path):
    expected = int(path.stem.rsplit("_", 1)[1])
    img = cv2.imdecode(np.fromfile(str(path), np.uint8), cv2.IMREAD_COLOR)
    assert len(detect_labels(img).labels) == expected
