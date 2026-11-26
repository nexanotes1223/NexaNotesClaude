"""Acceso a Windows mediante ctypes (sin dependencias externas).

Solo mecanismos externos y de solo lectura: enumerar ventanas, leer el nombre
del ejecutable del proceso, posición/estado de ventanas y captura visual del
área cliente. No se inyecta código, no se lee memoria y no se envían clics.
"""
from __future__ import annotations

import ctypes
import logging
import os
import sys
from dataclasses import dataclass

import numpy as np

log = logging.getLogger(__name__)

IS_WINDOWS = sys.platform == "win32"

if IS_WINDOWS:
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    try:
        dwmapi = ctypes.WinDLL("dwmapi")
    except OSError:  # pragma: no cover
        dwmapi = None

    HWND = wintypes.HWND
    LONG_PTR = ctypes.c_ssize_t

    WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, HWND, wintypes.LPARAM)
    user32.EnumWindows.argtypes = [WNDENUMPROC, wintypes.LPARAM]
    user32.IsWindowVisible.argtypes = [HWND]
    user32.IsWindow.argtypes = [HWND]
    user32.IsIconic.argtypes = [HWND]
    user32.GetWindowTextLengthW.argtypes = [HWND]
    user32.GetWindowTextW.argtypes = [HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetWindowThreadProcessId.argtypes = [HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetClientRect.argtypes = [HWND, ctypes.POINTER(wintypes.RECT)]
    user32.ClientToScreen.argtypes = [HWND, ctypes.POINTER(wintypes.POINT)]
    user32.GetDC.argtypes = [HWND]
    user32.GetDC.restype = wintypes.HDC
    user32.ReleaseDC.argtypes = [HWND, wintypes.HDC]
    user32.PrintWindow.argtypes = [HWND, wintypes.HDC, wintypes.UINT]
    user32.WindowFromPoint.argtypes = [wintypes.POINT]
    user32.WindowFromPoint.restype = HWND
    user32.GetAncestor.argtypes = [HWND, wintypes.UINT]
    user32.GetAncestor.restype = HWND
    user32.GetWindowLongPtrW.argtypes = [HWND, ctypes.c_int]
    user32.GetWindowLongPtrW.restype = LONG_PTR
    user32.SetWindowLongPtrW.argtypes = [HWND, ctypes.c_int, LONG_PTR]
    user32.SetWindowLongPtrW.restype = LONG_PTR
    user32.SetWindowPos.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]
    user32.GetForegroundWindow.restype = HWND
    user32.GetWindowRect.argtypes = [HWND, ctypes.POINTER(wintypes.RECT)]
    user32.GetWindowDC.argtypes = [HWND]
    user32.GetWindowDC.restype = wintypes.HDC
    user32.GetWindow.argtypes = [HWND, wintypes.UINT]
    user32.GetWindow.restype = HWND
    user32.GetThreadDpiAwarenessContext.restype = ctypes.c_void_p
    user32.GetAwarenessFromDpiAwarenessContext.argtypes = [ctypes.c_void_p]
    user32.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]
    user32.SetWindowDisplayAffinity.argtypes = [HWND, wintypes.DWORD]
    user32.GetClassNameW.argtypes = [HWND, wintypes.LPWSTR, ctypes.c_int]
    gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
    gdi32.CreateCompatibleDC.restype = wintypes.HDC
    gdi32.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
    gdi32.CreateCompatibleBitmap.restype = wintypes.HBITMAP
    gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
    gdi32.SelectObject.restype = wintypes.HGDIOBJ
    gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
    gdi32.DeleteDC.argtypes = [wintypes.HDC]
    gdi32.BitBlt.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                             wintypes.HDC, ctypes.c_int, ctypes.c_int, wintypes.DWORD]
    gdi32.GetDIBits.argtypes = [wintypes.HDC, wintypes.HBITMAP, wintypes.UINT, wintypes.UINT,
                                ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT]
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                                    ctypes.POINTER(wintypes.DWORD)]

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG),
                    ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD),
                    ("biCompression", wintypes.DWORD), ("biSizeImage", wintypes.DWORD),
                    ("biXPelsPerMeter", wintypes.LONG), ("biYPelsPerMeter", wintypes.LONG),
                    ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD)]

GWL_EXSTYLE = -20
GWLP_HWNDPARENT = -8
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_NOACTIVATE = 0x08000000
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_TOPMOST = 0x00000008
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
PW_CLIENTONLY = 0x1
PW_RENDERFULLCONTENT = 0x2
SRCCOPY = 0x00CC0020
GA_ROOT = 2
GW_OWNER = 4
GW_HWNDPREV = 3
HWND_TOP = 0
HWND_TOPMOST = -1
WDA_NONE = 0
WDA_EXCLUDEFROMCAPTURE = 0x11
SWP_SHOWWINDOW = 0x40
DWMWA_CLOAKED = 14
SWP_NOSIZE, SWP_NOMOVE, SWP_NOACTIVATE, SWP_NOZORDER = 0x1, 0x2, 0x10, 0x4
SWP_NOOWNERZORDER = 0x200


@dataclass
class WindowInfo:
    hwnd: int
    title: str
    pid: int
    exe: str


_exe_cache: dict[int, str] = {}


def process_exe(pid: int) -> str:
    if not IS_WINDOWS:
        return ""
    if pid in _exe_cache:
        return _exe_cache[pid]
    name = ""
    h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if h:
        try:
            buf = ctypes.create_unicode_buffer(1024)
            size = wintypes.DWORD(1024)
            if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
                name = os.path.basename(buf.value)
        finally:
            kernel32.CloseHandle(h)
    if len(_exe_cache) > 512:
        _exe_cache.clear()
    _exe_cache[pid] = name
    return name


def enum_windows() -> list[WindowInfo]:
    """Ventanas de primer nivel visibles con título."""
    if not IS_WINDOWS:
        return []
    out: list[WindowInfo] = []
    own_pid = os.getpid()

    def cb(hwnd, _lp):
        try:
            if not user32.IsWindowVisible(hwnd):
                return True
            n = user32.GetWindowTextLengthW(hwnd)
            if n <= 0:
                return True
            buf = ctypes.create_unicode_buffer(n + 1)
            user32.GetWindowTextW(hwnd, buf, n + 1)
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value == own_pid:
                return True  # nunca las ventanas de Nexa Notes
            out.append(WindowInfo(int(hwnd), buf.value, int(pid.value), process_exe(int(pid.value))))
        except Exception:  # pragma: no cover
            log.exception("EnumWindows")
        return True

    user32.EnumWindows(WNDENUMPROC(cb), 0)
    return out


def is_window(hwnd: int) -> bool:
    return bool(IS_WINDOWS and user32.IsWindow(hwnd))


def is_minimized(hwnd: int) -> bool:
    return bool(IS_WINDOWS and user32.IsIconic(hwnd))


def is_visible(hwnd: int) -> bool:
    return bool(IS_WINDOWS and user32.IsWindowVisible(hwnd))


def is_cloaked(hwnd: int) -> bool:
    """Ventana en otro escritorio virtual u oculta por DWM."""
    if not IS_WINDOWS or dwmapi is None:
        return False
    val = ctypes.c_int(0)
    try:
        res = dwmapi.DwmGetWindowAttribute(HWND(hwnd), DWMWA_CLOAKED, ctypes.byref(val), ctypes.sizeof(val))
        return res == 0 and val.value != 0
    except Exception:
        return False


def client_rect_screen(hwnd: int) -> tuple[int, int, int, int] | None:
    """Área cliente en píxeles físicos de pantalla (x, y, w, h)."""
    if not IS_WINDOWS:
        return None
    r = wintypes.RECT()
    if not user32.GetClientRect(hwnd, ctypes.byref(r)):
        return None
    p = wintypes.POINT(0, 0)
    if not user32.ClientToScreen(hwnd, ctypes.byref(p)):
        return None
    return (p.x, p.y, r.right - r.left, r.bottom - r.top)


def _dib_to_array(hdc, hbmp, w, h) -> np.ndarray | None:
    bmi = BITMAPINFOHEADER()
    bmi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bmi.biWidth, bmi.biHeight = w, -h  # top-down
    bmi.biPlanes, bmi.biBitCount, bmi.biCompression = 1, 32, 0
    buf = np.empty((h, w, 4), np.uint8)
    got = gdi32.GetDIBits(hdc, hbmp, 0, h, buf.ctypes.data, ctypes.byref(bmi), 0)
    if got != h:
        return None
    return np.ascontiguousarray(buf[..., :3])  # BGR


def _is_blank(img: np.ndarray | None) -> bool:
    if img is None or img.size == 0:
        return True
    small = img[::8, ::8]
    return int(small.max()) < 8 or float(small.std()) < 2.0


def window_rect(hwnd: int) -> tuple[int, int, int, int] | None:
    if not IS_WINDOWS:
        return None
    r = wintypes.RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(r)):
        return None
    return (r.left, r.top, r.right - r.left, r.bottom - r.top)


def _print_window(hwnd: int, w: int, h: int, flags: int) -> np.ndarray | None:
    hdc_win = user32.GetWindowDC(hwnd)
    if not hdc_win:
        return None
    mem = gdi32.CreateCompatibleDC(hdc_win)
    bmp = gdi32.CreateCompatibleBitmap(hdc_win, w, h)
    old = gdi32.SelectObject(mem, bmp)
    try:
        if not user32.PrintWindow(hwnd, mem, flags):
            return None
        return _dib_to_array(mem, bmp, w, h)
    finally:
        gdi32.SelectObject(mem, old)
        gdi32.DeleteObject(bmp)
        gdi32.DeleteDC(mem)
        user32.ReleaseDC(hwnd, hdc_win)


def _screen_grab(x: int, y: int, w: int, h: int) -> np.ndarray | None:
    hdc_scr = user32.GetDC(None)
    if not hdc_scr:
        return None
    mem = gdi32.CreateCompatibleDC(hdc_scr)
    bmp = gdi32.CreateCompatibleBitmap(hdc_scr, w, h)
    old = gdi32.SelectObject(mem, bmp)
    try:
        if not gdi32.BitBlt(mem, 0, 0, w, h, hdc_scr, x, y, SRCCOPY):
            return None
        return _dib_to_array(mem, bmp, w, h)
    finally:
        gdi32.SelectObject(mem, old)
        gdi32.DeleteObject(bmp)
        gdi32.DeleteDC(mem)
        user32.ReleaseDC(None, hdc_scr)


# Método que funcionó la última vez para cada ventana (se prueba primero).
_last_method: dict[int, str] = {}


def capture_client(hwnd: int) -> tuple[np.ndarray | None, str]:
    """Captura el área cliente de una ventana sin tocarla.

    Se prueban varias variantes de PrintWindow (funcionan aunque la mesa esté
    parcialmente tapada y no incluyen nuestras superposiciones). Algunas
    aplicaciones con aceleración gráfica devuelven una imagen negra con una
    variante y correcta con otra. Si todas fallan, se copia desde la pantalla
    (solo válido si la mesa está visible: quien llama lo comprueba).
    Devuelve (imagen BGR, método usado).
    """
    if not IS_WINDOWS:
        return None, "no-windows"
    rc = client_rect_screen(hwnd)
    wr = window_rect(hwnd)
    if not rc or not wr or rc[2] < 50 or rc[3] < 50:
        return None, "tamaño inválido"
    cx, cy, cw, ch = rc
    wx, wy, ww, wh = wr
    ox, oy = cx - wx, cy - wy  # posición del área cliente dentro de la ventana

    def full_window(flags):
        img = _print_window(hwnd, ww, wh, flags)
        if img is None or img.shape[0] < oy + ch or img.shape[1] < ox + cw or ox < 0 or oy < 0:
            return None
        return np.ascontiguousarray(img[oy:oy + ch, ox:ox + cw])

    def client_only(flags):
        img = _print_window(hwnd, ww, wh, flags | PW_CLIENTONLY)
        return None if img is None else np.ascontiguousarray(img[:ch, :cw])

    variants = {
        "PrintWindow-completa": lambda: full_window(PW_RENDERFULLCONTENT),
        "PrintWindow-cliente": lambda: client_only(PW_RENDERFULLCONTENT),
        "PrintWindow-clasico": lambda: full_window(0),
    }
    order = list(variants)
    last = _last_method.get(hwnd)
    if last in variants:
        order.remove(last)
        order.insert(0, last)
    for name in order:
        try:
            img = variants[name]()
        except Exception:  # pragma: no cover
            log.exception("captura %s", name)
            img = None
        if not _is_blank(img):
            _last_method[hwnd] = name
            return img, name
    # Capas propias de Nexa encima de la mesa: el contenido puede estar en ellas.
    for layer in table_layers(hwnd):
        lr = window_rect(layer)
        if not lr:
            continue
        lx, ly, lw, lh = lr
        dx, dy = cx - lx, cy - ly
        if dx < 0 or dy < 0 or dx + cw > lw or dy + ch > lh:
            continue
        for flags, name in ((PW_RENDERFULLCONTENT, "PrintWindow-capa"), (0, "PrintWindow-capa-clasico")):
            try:
                full = _print_window(layer, lw, lh, flags)
            except Exception:  # pragma: no cover
                full = None
            if full is not None:
                img = np.ascontiguousarray(full[dy:dy + ch, dx:dx + cw])
                if not _is_blank(img):
                    return img, f"{name} {layer}"
    img = _screen_grab(cx, cy, cw, ch)
    if not _is_blank(img):
        _last_method.pop(hwnd, None)
        return img, "pantalla"
    return None, "todas las capturas vacías"


def is_fully_visible(hwnd: int) -> bool:
    """Comprueba (con 9 puntos) que ninguna otra ventana tapa la mesa. Las ventanas
    propiedad de la mesa (nuestras superposiciones) no cuentan como tapadas."""
    if not IS_WINDOWS:
        return False
    rc = client_rect_screen(hwnd)
    if not rc:
        return False
    x, y, w, h = rc
    own = {int(hwnd), *table_layers(hwnd)}
    for fx in (0.05, 0.5, 0.95):
        for fy in (0.05, 0.5, 0.95):
            p = wintypes.POINT(int(x + w * fx), int(y + h * fy))
            hit = user32.WindowFromPoint(p)
            root = user32.GetAncestor(hit, GA_ROOT) if hit else None
            if not root:
                return False
            if int(root) in own or window_pid(int(root)) == os.getpid():
                continue
            owner = user32.GetWindow(root, GW_OWNER)
            if owner and int(owner) == int(hwnd):
                continue
            return False
    return True


def dpi_awareness() -> str:
    """Modo DPI del proceso (diagnóstico)."""
    if not IS_WINDOWS:
        return "no-windows"
    try:
        ctx = user32.GetThreadDpiAwarenessContext()
        aw = user32.GetAwarenessFromDpiAwarenessContext(ctx)
        return {0: "sin DPI (coordenadas virtualizadas)", 1: "DPI de sistema",
                2: "DPI por monitor"}.get(aw, str(aw))
    except Exception:
        return "desconocido"


def set_dpi_aware() -> None:
    """Coordenadas físicas en todos los monitores (antes de crear la interfaz)."""
    if not IS_WINDOWS:
        return
    try:
        if user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):  # PER_MONITOR_AWARE_V2
            return
    except Exception:
        pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            user32.SetProcessDPIAware()
        except Exception:
            pass


def set_owner(child_hwnd: int, owner_hwnd: int) -> None:
    """Hace que la ventana del overlay sea 'propiedad' de la mesa: Windows la mantiene
    siempre justo encima de su mesa (respeta el orden de ventanas) y la oculta
    cuando la mesa se minimiza."""
    if IS_WINDOWS:
        user32.SetWindowLongPtrW(child_hwnd, GWLP_HWNDPARENT, owner_hwnd)


def is_topmost(hwnd: int) -> bool:
    if not IS_WINDOWS:
        return False
    return bool(user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE) & WS_EX_TOPMOST)


def window_above(hwnd: int) -> int:
    """Ventana situada justo encima en el orden de ventanas (0 si es la primera)."""
    if not IS_WINDOWS:
        return 0
    h = user32.GetWindow(hwnd, GW_HWNDPREV)
    return int(h) if h else 0


def window_pid(hwnd: int) -> int:
    if not IS_WINDOWS or not hwnd:
        return 0
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return int(pid.value)


def window_owner(hwnd: int) -> int:
    if not IS_WINDOWS or not hwnd:
        return 0
    h = user32.GetWindow(hwnd, GW_OWNER)
    return int(h) if h else 0


def window_title(hwnd: int) -> str:
    if not IS_WINDOWS or not hwnd:
        return ""
    n = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(max(1, n + 1))
    user32.GetWindowTextW(hwnd, buf, n + 1)
    return buf.value


def window_class(hwnd: int) -> str:
    if not IS_WINDOWS or not hwnd:
        return ""
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def describe_window(hwnd: int) -> str:
    """Texto para el diagnóstico: clase, título, proceso, propietario y posición."""
    if not hwnd:
        return "ninguna"
    return (f"{hwnd} [{window_class(hwnd)}] «{window_title(hwnd)[:40]}» proceso {process_exe(window_pid(hwnd))}"
            f" propietario {window_owner(hwnd)} rect {window_rect(hwnd)}"
            f"{' visible' if is_visible(hwnd) else ' oculta'}")


def _overlaps(a, b, tol=0.8) -> bool:
    if not a or not b:
        return False
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    ix = max(0, min(ax + aw, bx + bw) - max(ax, bx))
    iy = max(0, min(ay + ah, by + bh) - max(ay, by))
    return ix * iy >= tol * max(1, min(aw * ah, bw * bh))


def table_layers(table_hwnd: int, title_keyword: str = "Blinds") -> list[int]:
    """Ventanas del propio cliente situadas justo encima de la mesa que forman
    parte de ella (capa de contenido, animaciones...): propiedad de la mesa, o del
    mismo proceso, sin ser otra mesa y cubriendo la misma zona. De abajo arriba."""
    if not IS_WINDOWS:
        return []
    pid = window_pid(table_hwnd)
    rc = window_rect(table_hwnd)
    out = []
    h = window_above(table_hwnd)
    steps = 0
    while h and steps < 30:
        steps += 1
        if is_visible(h):
            same = window_pid(h) == pid
            owned = window_owner(h) == table_hwnd
            other_table = title_keyword.lower() in window_title(h).lower()
            if owned or (same and not other_table and _overlaps(window_rect(h), rc)):
                out.append(h)
            elif same and other_table:
                break  # otra mesa encima: no seguir
            elif not same:
                # ventana de otra aplicación (o nuestra): se sigue buscando solo
                # si es pequeña y no tapa la mesa (p. ej. nuestros botones)
                if _overlaps(window_rect(h), rc, 0.3) and window_pid(h) != os.getpid():
                    break
        h = window_above(h)
    return out


def place_just_above(our_hwnd: int, target_hwnd: int) -> None:
    """Coloca nuestra ventana justo encima de target en el orden de ventanas, sin
    activarla: queda tapada por las mismas ventanas que tapan la mesa."""
    if not IS_WINDOWS:
        return
    above = window_above(target_hwnd)
    if above == our_hwnd:
        return
    if above:
        insert_after = above
    else:
        insert_after = HWND_TOPMOST if is_topmost(target_hwnd) else HWND_TOP
    user32.SetWindowPos(our_hwnd, insert_after, 0, 0, 0, 0,
                        SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_NOOWNERZORDER)


def exclude_from_capture(hwnd: int, exclude: bool) -> None:
    """Hace invisible nuestra ventana para las capturas de pantalla (incluidas las
    nuestras), para no analizar nuestros propios dibujos. Windows 10 2004 o superior."""
    if IS_WINDOWS:
        try:
            user32.SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE if exclude else WDA_NONE)
        except Exception:
            pass


def ex_style(hwnd: int) -> int:
    return int(user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)) if IS_WINDOWS else 0


def add_ex_style(hwnd: int, flags: int, remove: int = 0) -> None:
    if not IS_WINDOWS:
        return
    st = user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
    user32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, (st | flags) & ~remove)


def move_window(hwnd: int, x: int, y: int, w: int, h: int) -> None:
    if IS_WINDOWS:
        user32.SetWindowPos(hwnd, None, x, y, w, h, SWP_NOACTIVATE | SWP_NOZORDER | SWP_NOOWNERZORDER)
