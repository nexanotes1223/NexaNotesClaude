"""Seguimiento de identidad: timebank, asientos vacíos y cambios de jugador.

Se usa una captura real y se simulan las lecturas del OCR para reproducir
cada situación de forma controlada.
"""
import cv2
import numpy as np

from conftest import load
from nexanotes.detector import detect_labels
from nexanotes.tracker import CONFIRMED, TRUNCATED_ST, UNCERTAIN, TableTracker

IMG = load("MesaNexa.png")
DET = detect_labels(IMG)


class FakeOcr:
    """Simula el OCR: devuelve la lectura programada para cada etiqueta
    (identificada por el contenido exacto de su recorte)."""

    def __init__(self, reads, img=IMG, det=DET):
        from nexanotes.detector import crop
        self.map = {}
        for lab, text in zip(det.labels, reads):
            c = crop(img, lab.name_rect)
            self.map[(c.shape, c.tobytes())] = text
        self.calls = 0

    def __call__(self, c):
        self.calls += 1
        return self.map[(c.shape, c.tobytes())], 0.97


def names_of(tr):
    return {s.sid: s.display_name for s in tr.seats}


def run(tr, reads, t, det=DET, img=IMG):
    return tr.update(img, det, FakeOcr(reads, img, det), now=t)


def test_confirma_todos_los_jugadores():
    tr = TableTracker(30)
    base = [f"P{i}x" for i in range(len(DET.labels))]
    run(tr, base, 0)
    assert len(tr.seats) == 7
    assert all(s.status == CONFIRMED for s in tr.seats)
    assert [s.display_name for s in tr.seats] == base


def test_timebank_y_acciones_mantienen_identidad():
    tr = TableTracker(30)
    base = [f"P{i}x" for i in range(7)]
    run(tr, base, 0)
    reads = list(base)
    reads[2] = "14"        # timebank
    reads[3] = "All in"    # acción
    reads[4] = "Fold"
    run(tr, reads, 31)
    assert [s.display_name for s in tr.seats] == base


def test_asiento_vacio_retira_identidad_y_no_se_hereda():
    tr = TableTracker(30)
    base = [f"P{i}x" for i in range(7)]
    run(tr, base, 0)
    # el jugador 0 desaparece (asiento vacío) en dos análisis seguidos
    det_less = detect_labels(IMG)
    gone = det_less.labels.pop(0)
    rest = base[1:]
    tr.update(IMG, det_less, FakeOcr(rest, IMG, det_less), now=5)
    assert len(tr.seats) == 7  # una sola ausencia: se conserva (animación, etc.)
    tr.update(IMG, det_less, FakeOcr(rest, IMG, det_less), now=10)
    assert len(tr.seats) == 6
    assert "P0x" not in [s.display_name for s in tr.seats]
    # llega un jugador nuevo al mismo sitio: asiento nuevo, sin el nombre anterior
    tr.update(IMG, DET, FakeOcr(["Nuevo1"] + rest), now=15)
    new = [s for s in tr.seats if s.label.rect == gone.rect][0]
    assert new.display_name == "Nuevo1"


def test_cambio_de_jugador_sin_desaparecer_queda_en_duda_y_luego_cambia():
    tr = TableTracker(30)
    base = [f"P{i}x" for i in range(7)]
    run(tr, base, 0)
    reads = list(base)
    reads[1] = "OtroJugador"
    run(tr, reads, 31)
    s1 = tr.seats[1]
    assert s1.status == UNCERTAIN and s1.display_name is None  # sin color mientras hay dudas
    run(tr, reads, 33)
    assert s1.status == CONFIRMED and s1.display_name == "OtroJugador"


def test_lectura_erronea_aislada_no_cambia_jugador():
    tr = TableTracker(30)
    base = ["AhyeonBaby"] + [f"P{i}x" for i in range(1, 7)]
    run(tr, base, 0)
    reads = list(base)
    reads[0] = "AhyeonBabv"  # error menor de OCR
    run(tr, reads, 31)
    assert tr.seats[0].display_name == "AhyeonBaby"


def test_nombre_truncado_no_se_asocia_automaticamente():
    tr = TableTracker(30)
    reads = ["LargoNomb..."] + [f"P{i}x" for i in range(1, 7)]
    run(tr, reads, 0)
    s0 = tr.seats[0]
    assert s0.status == TRUNCATED_ST
    assert s0.display_name is None and s0.truncated_prefix == "LargoNomb"
    tr.set_manual_name(s0.sid, "LargoNombreCompleto")
    assert s0.display_name == "LargoNombreCompleto"
    # sigue viéndose truncado: se mantiene la identidad indicada por el usuario
    run(tr, reads, 31)
    assert s0.display_name == "LargoNombreCompleto"


def test_mesa_redimensionada_conserva_asientos():
    tr = TableTracker(30)
    base = [f"P{i}x" for i in range(7)]
    run(tr, base, 0)
    big = cv2.resize(IMG, None, fx=1.3, fy=1.3, interpolation=cv2.INTER_CUBIC)
    dbig = detect_labels(big)
    tr.update(big, dbig, FakeOcr(base, big, dbig), now=5)
    assert len(tr.seats) == 7
    assert sorted(s.display_name for s in tr.seats) == sorted(base)


def test_cambio_de_avatar_y_nombre_exige_dos_lecturas():
    tr = TableTracker(30)
    base = [f"P{i}x" for i in range(7)]
    run(tr, base, 0)
    img2 = IMG.copy()
    x, y, w, h = DET.labels[0].avatar_rect
    rng = np.random.default_rng(1)
    img2[y:y + h, x:x + w] = rng.integers(0, 255, (h, w, 3), dtype=np.uint8)
    reads = list(base)
    reads[0] = "Sustituto"
    d2 = detect_labels(img2)
    tr.update(img2, d2, FakeOcr(reads, img2, d2), now=3)
    assert tr.seats[0].display_name is None  # en duda: sin color del anterior
    tr.update(img2, d2, FakeOcr(reads, img2, d2), now=5)
    assert tr.seats[0].display_name == "Sustituto"
