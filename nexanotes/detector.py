"""Detección visual de las etiquetas de los jugadores (sin coordenadas fijas).

Todas las medidas son proporcionales al ancho de la imagen de la mesa.

1. Máscara de color de etiqueta: gris pizarra oscuro y algo frío (azul un poco
   mayor que rojo). El tapete, las sombras y los fondos suelen ser cálidos o
   neutros y quedan fuera aunque sean igual de oscuros. El texto interior se
   rellena con un cierre morfológico.
2. Fase A (apilado): tramos horizontales con anchura de etiqueta y bordes
   alineados, apilados en vertical = rectángulos aislados. Da las etiquetas
   "limpias" y, con ellas, el TAMAÑO de etiqueta de esta mesa (todas miden igual).
3. Fase B (búsqueda a tamaño fijo): con ese tamaño se buscan rectángulos llenos
   del color de etiqueta. Recupera etiquetas pegadas al borde de la mesa u otras
   zonas oscuras, que la fase A no puede separar.
4. Validación de cada candidata: proporción, fondo oscuro, DOS líneas de texto
   centradas (nickname y fichas) y, encima, un avatar (no color de etiqueta).
   No depende del azul de las fichas.
Cada candidata descartada se guarda con su motivo (modo diagnóstico).
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


# --- color de la etiqueta
DARK_V_MAX = 56
DARK_V_MIN = 6
COOL_MIN, COOL_MAX = 1, 14   # azul - rojo
GR_MAX = 6                   # |verde - rojo|
# --- geometría (proporción del ancho W de la mesa)
MIN_W, MAX_W = 0.07, 0.20
MIN_H = 0.035
LABEL_ASPECT = 2.05
MIN_ASPECT, MAX_ASPECT = 1.6, 2.6
K_CLOSE = 0.012              # cierre que rellena el texto
EDGE_TOL = 0.006             # tolerancia de alineación de bordes (fase A)
# --- búsqueda a tamaño fijo (fase B)
INNER_MIN = 0.86
ANALYSIS_W = 1100            # las mesas más grandes se analizan reducidas


def _iou_min(a: Rect, b: Rect) -> float:
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
    ax = max(0, x + w // 2 - s // 2)
    ay = max(0, y - int(w * 0.62))
    s = max(1, min(s, W - ax, H - ay))
    return Label(r, name, chips, (ax, ay, s, s))


def label_mask(img: np.ndarray) -> np.ndarray:
    W = img.shape[1]
    im = img.astype(np.int16)
    b, g, r = im[..., 0], im[..., 1], im[..., 2]
    v = im.max(2)
    m = ((v < DARK_V_MAX) & (v >= DARK_V_MIN) & (b - r >= COOL_MIN) & (b - r <= COOL_MAX)
         & (np.abs(g - r) <= GR_MAX)).astype(np.uint8)
    k = max(3, int(W * K_CLOSE)) | 1
    return cv2.morphologyEx(m, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (k, k)))


# ---------------------------------------------------------------- fase A
def _stack_candidates(m: np.ndarray) -> list[Rect]:
    H, W = m.shape
    minw, maxw = int(MIN_W * W), int(MAX_W * W)
    tol = max(3, W * EDGE_TOL)
    gap_max = max(3, int(W * 0.006))
    min_rows = MIN_H * W * 0.85
    pad = np.zeros((H, W + 2), np.int8)
    pad[:, 1:-1] = m > 0
    d = np.diff(pad, axis=1)
    sr, sc = np.nonzero(d == 1)
    _er, ec = np.nonzero(d == -1)
    L = ec - sc
    sel = (L >= minw) & (L <= maxw * 1.15)
    runs = sorted(zip(sr[sel].tolist(), sc[sel].tolist(), ec[sel].tolist()))
    stacks: list[list[tuple[int, int, int]]] = []
    active: list[list[tuple[int, int, int]]] = []
    for r, c0, c1 in runs:
        best = None
        for st in active:
            lr, l0, l1 = st[-1]
            if 0 < r - lr <= gap_max + 1 and abs(c0 - l0) <= tol and abs(c1 - l1) <= tol:
                best = st
                break
        if best is None:
            best = []
            active.append(best)
            stacks.append(best)
        best.append((r, c0, c1))
        if len(active) > 64:
            active = [s for s in active if r - s[-1][0] <= gap_max + 1]
    out = []
    for st in stacks:
        r0, r1 = st[0][0], st[-1][0] + 1
        if r1 - r0 < min_rows * 0.5:
            continue
        c0 = int(np.median([t[1] for t in st]))
        c1 = int(np.median([t[2] for t in st]))
        out.append(_fit_height((c0, r0, c1 - c0, r1 - r0), m))
    return out


def _fit_height(rect: Rect, m: np.ndarray) -> Rect:
    """Ajusta la altura a la proporción de la etiqueta: prolonga si la franja se
    cortó (fondo pegado al borde) o recorta si incluye filas del avatar o sombra."""
    x, y, w, h = rect
    H = m.shape[0]
    target = int(round(w / LABEL_ASPECT))
    cols = m[:, x:x + w] > 0
    if h > target * 1.06:
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

    top, bot = y, y + h
    while bot - top < target:
        up, down = dark_row(top - 1), dark_row(bot)
        if not (up or down):
            break
        if up and (not down or (bot - y) >= (y + h - top)):
            top -= 1
        else:
            bot += 1
    return (x, top, w, bot - top)


# ---------------------------------------------------------------- fase B
def _fixed_size_candidates(m: np.ndarray, w: int, h: int, limit: int = 40) -> list[tuple[float, Rect]]:
    """Rectángulos de tamaño (w, h) casi llenos del color de etiqueta y con al
    menos un lado claramente distinto (no forman parte de una barra o zona oscura)."""
    mf = m.astype(np.float32)
    H, W = m.shape
    inner = cv2.boxFilter(mf, -1, (w, h), anchor=(0, 0), normalize=True, borderType=cv2.BORDER_CONSTANT)
    sw = max(2, int(h * 0.2))
    side = cv2.boxFilter(mf, -1, (sw, h), anchor=(0, 0), normalize=True, borderType=cv2.BORDER_CONSTANT)
    # lado izquierdo y derecho de cada posición; al menos uno debe ser distinto
    left = np.zeros_like(side)
    left[:, sw:] = side[:, :W - sw]
    right = np.zeros_like(side)
    right[:, :W - w] = side[:, w:]
    score = np.where(np.minimum(left, right) < 0.35, inner, 0).astype(np.float32)
    score[max(0, H - h):, :] = 0
    score[:, max(0, W - w - sw):] = 0
    score[:, :sw] = 0
    k = max(3, (h // 2) | 1)
    dil = cv2.dilate(score, cv2.getStructuringElement(cv2.MORPH_RECT, (k, k)))
    ys, xs = np.nonzero((score >= INNER_MIN) & (score >= dil - 1e-6))
    out = [(float(score[y, x]), (int(x), int(y), w, h)) for y, x in zip(ys, xs)]
    out.sort(key=lambda c: -c[0])
    return out[:limit]


# ---------------------------------------------------------------- validación
def _validate(rect: Rect, v: np.ndarray, m: np.ndarray) -> str | None:
    """Etiqueta de jugador: fondo oscuro, dos líneas de texto centradas y un
    avatar encima (la zona de encima no tiene el color de etiqueta)."""
    x, y, w, h = rect
    H, W = v.shape
    if w <= 0 or h <= 0 or x < 0 or y < 0 or x + w > W or y + h > H:
        return "fuera de la imagen"
    if not (MIN_ASPECT <= w / h <= MAX_ASPECT):
        return f"proporción {w / h:.2f}"
    roi = v[y:y + h, x:x + w].astype(np.int16)
    base = float(np.percentile(roi, 35))
    top = float(np.percentile(roi, 99))
    thr = max(base + 30.0, base + 0.45 * (top - base))
    bright = roi > thr
    bg = roi[~bright]
    if bg.size and bg.mean() > 62:
        return f"fondo no oscuro ({bg.mean():.0f})"
    if bright.mean() > 0.45:
        return "demasiadas zonas claras"
    m0 = max(1, int(h * 0.08))
    e = max(1, int(w * 0.04))  # se ignoran los bordes (esquinas redondeadas, brillos)
    for name, part in (("nickname", bright[m0:h // 2, e:w - e]), ("fichas", bright[h // 2:h - m0, e:w - e])):
        if part.size == 0 or part.mean(1).max() < 0.04:
            return f"sin texto en la línea de {name}"
        # una línea de texto real ocupa varias filas (una raya fina, como el
        # subrayado de los botones Fold/Call, no cuenta como texto)
        if (part.mean(1) >= 0.04).sum() < max(3, part.shape[0] * 0.3):
            return f"la línea de {name} no parece texto"
        colsum = part.sum(0)
        cols = np.nonzero(colsum >= max(2, part.shape[0] * 0.15))[0]
        if len(cols) == 0:
            return f"sin texto en la línea de {name}"
        cx = e + (cols[0] + cols[-1]) / 2
        if abs(cx - w / 2) > w * 0.15:
            return f"texto de {name} no centrado"
    # encima: avatar (o al menos algo que no es otra barra/etiqueta del mismo color)
    ah = max(2, int(h * 0.8))
    ay0 = y - ah
    if ay0 < 0:
        return "no hay sitio para el avatar encima"
    ax0, ax1 = x + w // 4, x + w - w // 4
    above = m[ay0:y - max(1, h // 10), ax0:ax1]
    if above.size and above.mean() > 0.85:
        return "encima no hay avatar (barra oscura)"
    return None


def _nms(cands: list[tuple[float, Rect]], thr: float) -> list[tuple[float, Rect]]:
    keep: list[tuple[float, Rect]] = []
    for c in sorted(cands, key=lambda c: -c[0]):
        if all(_iou_min(c[1], k[1]) < thr for k in keep):
            keep.append(c)
    return keep


def _scale_rect(r: Rect, f: float) -> Rect:
    return (int(round(r[0] * f)), int(round(r[1] * f)), int(round(r[2] * f)), int(round(r[3] * f)))


def detect_labels(img: np.ndarray) -> Detection:
    H, W = img.shape[:2]
    if W > ANALYSIS_W:
        f = ANALYSIS_W / W
        small = cv2.resize(img, (ANALYSIS_W, max(1, int(round(H * f)))), interpolation=cv2.INTER_AREA)
        d = _detect(small)
        inv = 1.0 / f
        out = Detection(size=(W, H))
        out.labels = [_make_label(_scale_rect(l.rect, inv), W, H) for l in d.labels]
        out.rejected = [(_scale_rect(r, inv), why) for r, why in d.rejected]
        return out
    return _detect(img)


def _detect(img: np.ndarray) -> Detection:
    H, W = img.shape[:2]
    det = Detection(size=(W, H))
    if W < 200 or H < 150:
        return det
    v = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)[..., 2]
    m = label_mask(img)

    # Fase A
    good: list[tuple[float, Rect]] = []
    for r in _stack_candidates(m):
        why = _validate(r, v, m)
        if why:
            det.rejected.append((r, why))
        else:
            good.append((2.0, r))  # prioridad sobre la fase B
    # Tamaño de etiqueta de esta mesa
    if good:
        ws = sorted(r[2] for _s, r in good)
        hs = sorted(r[3] for _s, r in good)
        lw, lh = ws[len(ws) // 2], hs[len(hs) // 2]
        # descartar etiquetas de tamaño anómalo
        kept = []
        for s, r in good:
            if 0.85 * lw <= r[2] <= 1.18 * lw:
                kept.append((s, r))
            else:
                det.rejected.append((r, f"tamaño distinto al resto ({r[2]} vs {lw})"))
        good = kept
        # Fase B: a tamaño fijo
        extra = []
        for sc in (0.97, 1.0, 1.03):
            bw, bh = int(round(lw * sc)), int(round(lh * sc))
            for s, r in _fixed_size_candidates(m, bw, bh):
                if any(_iou_min(r, g[1]) >= 0.3 for g in good):
                    continue
                why = _validate(r, v, m)
                if why is None:
                    extra.append((s, r))
        good += _nms(extra, 0.3)
    final = _nms(good, 0.3)
    rects = sorted((r for _s, r in final), key=lambda r: (r[1], r[0]))
    det.labels = [_make_label(r, W, H) for r in rects]
    return det


def avatar_signature(img: np.ndarray, label: Label) -> np.ndarray | None:
    """Miniatura 8x8 normalizada del centro del avatar (insensible al oscurecido de Fold)."""
    x, y, w, h = label.avatar_rect
    if w < 6 or h < 6:
        return None
    crop_ = img[y:y + h, x:x + w]
    if crop_.size == 0:
        return None
    g = cv2.cvtColor(crop_, cv2.COLOR_BGR2GRAY)
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
