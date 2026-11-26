import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
CAPTURAS = Path(__file__).resolve().parent / "capturas"


def load(name: str) -> np.ndarray:
    img = cv2.imdecode(np.fromfile(str(CAPTURAS / name), np.uint8), cv2.IMREAD_COLOR)
    assert img is not None, name
    return img


@pytest.fixture(scope="session")
def ocr():
    from nexanotes.ocr import OcrEngine
    eng = OcrEngine(threads=1)
    assert eng.warm_up(), eng.init_error
    return eng
