"""Detección visual de las etiquetas oscuras de los jugadores.

No usa coordenadas fijas: todas las medidas son proporcionales al ancho de la
imagen de la mesa (área cliente de la ventana).

Pasos:
 1. Máscara de píxeles gris muy oscuro y poco saturado (fondo de la etiqueta).
 2. Cierre morfológico para rellenar el texto dentro de la etiqueta.
 3. Componentes conectados. Un componente puede incluir avatar oscuro o
    sombras; por eso dentro de cada uno se buscan franjas de filas cuyo tramo
    oscuro tenga anchura de etiqueta y bordes izquierdo/derecho alineados
    (geometría de rectángulo).
 4. Validación: proporción, tamaño relativo, fondo realmente oscuro y DOS
    líneas de texto (nickname arriba, fichas/BB abajo). No depende del azul.
 5. Supresión de duplicados.
Cada candidato descartado se guarda con su motivo (modo diagnóstico).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np

Rect = tuple[int, int, int, int]  # x, y, w, h


@dataclass
class Label:
    rect: Rect
    name_rect: Rect     # mitad superior: solo nickname
    chips_rect: Rect    # mitad inferior: fichas/BB (no se usa para identidad)
    avatar_rect: Rect   # zona central del avatar (firma visual)


@dataclass
class Detection:
    labels: list[Label] = field(default_factory=list)
    rejected: list[tuple[Rect, str]] = field(default_factory=list)
    size: tuple[int, int] = (0, 0)  # w, h de la imagen analizada


# Parámetros (proporciones respecto al ancho W de la mesa)
DARK_V_MAX = 30          # brillo máximo del fondo de la etiqueta
DARK_CHROMA_MAX = 16     # gris: diferencia máx. entre canales
MIN_W, MAX_W = 0.07, 0.20
MIN_H, MAX_H = 0.035, 0.08
MIN_ASPECT, MAX_ASPECT = 1.5, 3.2
EDGE_TOL = 0.006


def _rect_iou_min(a: Rect, b: Rect) -> float:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    ix = max(0, min(ax + aw, bx + bw) - max(ax, bx))
    iy = max(0, min(ay + ah, by + bh) - max(ay, by))
    return ix * iy / max(1, min(aw * ah, bw * bh))


def _make_label(r: Rect, W: int, H: int) -> Label:
    x, y, w, h = r
    name = (x + int(w * 0.04), y + int(h * 0.06), int(w * 0.92), int(h * 0.46))
    chips = (x + int(w * 0.04), y + h // 2, int(w * 0.92), h - h // 2)
    s = int(w * 0.40)
    ax = x + w // 2 - s // 2
    ay = y - int(w * 0.62)
    ax, ay = max(0, ax), max(0, ay)
    s = max(1, min(s, W - ax, H - ay))
    return Label(r, name, chips, (ax, ay, s, s))


MAX_ANALYSIS_W = 1100  # las mesas más grandes se reducen para analizar (más rápido)


def _scale_rect(r: Rect, f: float) -> Rect:
    return (int(round(r[0] * f)), int(round(r[1] * f)), int(round(r[2] * f)), int(round(r[3] * f)))


def detect_labels(img: np.ndarray) -> Detection:
    H, W = img.shape[:2]
    if W <= MAX_ANALYSIS_W:
        return _detect_raw(img)
    f = MAX_ANALYSIS_W / W
    small = cv2.resize(img, (MAX_ANALYSIS_W, max(1, int(round(H * f)))), interpolation=cv2.INTER_AREA)
    d = _detect_raw(small)
    inv = 1.0 / f
    out = Detection(size=(W, H))
    out.labels = [_make_label(_scale_rect(l.rect, inv), W, H) for l in d.labels]
    out.rejected = [(_scale_rect(r, inv), why) for r, why in d.rejected]
    return out


def _detect_raw(img: np.ndarray) -> Detection:
    H, W = img.shape[:2]
    det = Detection(size=(W, H))
    if W < 200 or H < 150:
        return det
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    v = hsv[..., 2]
    chroma = img.max(2).astype(np.int16) - img.min(2).astype(np.int16)
    dark = ((v < DARK_V_MAX) & (chroma < DARK_CHROMA_MAX)).astype(np.uint8) * 255
    k = max(3, int(W * 0.012)) | 1
    closed = cv2.morphologyEx(dark, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (k, k)))
    # Cierre horizontal adicional: rellena huecos entre caracteres grandes
    # (nombres chinos) sin unir objetos separados verticalmente.
    kh = max(5, int(W * 0.035)) | 1
    closed = cv2.morphologyEx(closed, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (kh, 1)))
    minw, maxw = int(MIN_W * W), int(MAX_W * W)
    tol = max(3, W * EDGE_TOL)
    gap_max = max(3, int(W * 0.006))
    min_rows = MIN_H * W * 0.85

    # 1) Todos los tramos horizontales oscuros con anchura de etiqueta.
    m = closed > 0
    pad = np.zeros((H, W + 2), np.int8)
    pad[:, 1:-1] = m
    d = np.diff(pad, axis=1)
    sr, sc = np.nonzero(d == 1)
    _er, ec = np.nonzero(d == -1)
    L = ec - sc
    sel = (L >= minw) & (L <= maxw * 1.15)
    runs = sorted(zip(sr[sel].tolist(), sc[sel].tolist(), ec[sel].tolist()))

    # 2) Apilar tramos alineados de filas consecutivas (bordes verticales).
    stacks: list[list[tuple[int, int, int]]] = []
    active: list[list[tuple[int, int, int]]] = []
    for r, c0, c1 in runs:
        best = None
        for st_ in active:
            lr, l0, l1 = st_[-1]
            if 0 < r - lr <= gap_max + 1 and abs(c0 - l0) <= tol and abs(c1 - l1) <= tol:
                best = st_
                break
        if best is None:
            best = []
            active.append(best)
            stacks.append(best)
        best.append((r, c0, c1))
        # retirar pilas que ya no pueden continuar
        if len(active) > 64:
            active = [s_ for s_ in active if r - s_[-1][0] <= gap_max + 1]
    found: list[Rect] = []
    for st_ in stacks:
        if len(st_) < min_rows * 0.5:
            continue
        r0, r1 = st_[0][0], st_[-1][0] + 1
        c0 = int(np.median([t[1] for t in st_]))
        c1 = int(np.median([t[2] for t in st_]))
        raw = (c0, r0, c1 - c0, r1 - r0)
        if len(st_) < min_rows * 0.5 or (r1 - r0) < min_rows * 0.5:
            continue
        rect = _fit_height(raw, closed)
        if rect[3] < min_rows:
            det.rejected.append((rect, f"franja demasiado baja ({rect[3]}px)"))
            continue
        reason = _validate(rect, v, W)
        if reason:
            det.rejected.append((rect, reason))
        else:
            found.append(rect)

    # Supresión de duplicados (se queda el mayor)
    keep: list[Rect] = []
    for r in sorted(found, key=lambda r: -r[2] * r[3]):
        if all(_rect_iou_min(r, k2) < 0.5 for k2 in keep):
            keep.append(r)
        else:
            det.rejected.append((r, "duplicado"))
    keep.sort(key=lambda r: (r[1], r[0]))
    det.labels = [_make_label(r, W, H) for r in keep]
    return det


LABEL_ASPECT = 2.05  # anchura/altura típica de la etiqueta de Nexa


def _fit_height(rect: Rect, closed: np.ndarray) -> Rect:
    """Si la franja encontrada es más baja de lo esperado (fondo oscuro pegado
    al borde o avatar solapado), se prolonga hacia arriba/abajo mientras las
    filas sigan siendo oscuras dentro de las mismas columnas."""
    x, y, w, h = rect
    H = closed.shape[0]
    target = int(round(w / LABEL_ASPECT))
    cols = closed[:, x:x + w] > 0
    if h > target * 1.06:
        # Demasiado alta: recortar por el extremo con filas menos "de etiqueta"
        # (pegada al avatar o a una sombra). Se evalúa la franja sin texto:
        # bordes izquierdo y derecho de la fila.
        edge = max(2, w // 12)
        top, bot = y, y + h

        def score(r):
            row = cols[r]
            return row[:edge].mean() + row[-edge:].mean() + row.mean()

        while bot - top > target:
            if score(top) <= score(bot - 1):
                top += 1
            else:
                bot -= 1
        return (x, top, w, bot - top)
    if h >= target * 0.97 or h < target * 0.45:
        return rect

    def dark_row(r):
        return 0 <= r < H and cols[r].mean() >= 0.85

    top, bot = y, y + h  # bot exclusivo
    while bot - top < target:
        can_up, can_down = dark_row(top - 1), dark_row(bot)
        if not (can_up or can_down):
            break
        if can_up and (not can_down or (bot - y) >= (y + h - top)):
            top -= 1
        else:
            bot += 1
    return (x, top, w, bot - top)


def _validate(rect: Rect, v: np.ndarray, W: int) -> str | None:
    x, y, w, h = rect
    if h <= 0 or w <= 0:
        return "vacío"
    if not (MIN_ASPECT <= w / h <= MAX_ASPECT):
        return f"proporción {w / h:.2f}"
    if not (MIN_H * W <= h <= MAX_H * W):
        return f"altura {h}px fuera de rango"
    if not (MIN_W * W <= w <= MAX_W * W):
        return f"anchura {w}px fuera de rango"
    roi = v[y:y + h, x:x + w]
    base = float(np.percentile(roi, 40))
    bright = roi > max(60.0, base + 40.0)
    prof = bright.mean(1)
    top = float(prof[: h // 2].max())
    bot = float(prof[h // 2:].max())
    if top < 0.03 or bot < 0.03:
        return f"no tiene dos líneas de texto ({top:.2f}/{bot:.2f})"
    bg = roi[~bright]
    if bg.size and bg.mean() > 40:
        return f"fondo no oscuro ({bg.mean():.0f})"
    return None


def avatar_signature(img: np.ndarray, label: Label) -> np.ndarray | None:
    """Miniatura 8x8 normalizada del centro del avatar (insensible al oscurecido de Fold)."""
    x, y, w, h = label.avatar_rect
    if w < 6 or h < 6:
        return None
    crop = img[y:y + h, x:x + w]
    if crop.size == 0:
        return None
    g = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    g = cv2.resize(g, (8, 8), interpolation=cv2.INTER_AREA).astype(np.float32)
    sd = float(g.std())
    if sd < 3:
        return None
    return (g - g.mean()) / sd


def signature_distance(a: np.ndarray | None, b: np.ndarray | None) -> float | None:
    if a is None or b is None:
        return None
    return float(np.abs(a - b).mean())


def crop(img: np.ndarray, r: Rect) -> np.ndarray:
    x, y, w, h = r
    return img[max(0, y):y + h, max(0, x):x + w]
