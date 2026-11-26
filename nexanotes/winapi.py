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
    user32.SetWindowPos.argtypes = [HWND, HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]
    user32.GetForegroundWindow.restype = HWND
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


def capture_client(hwnd: int) -> tuple[np.ndarray | None, str]:
    """Captura el área cliente de una ventana.

    1) PrintWindow(PW_CLIENTONLY|PW_RENDERFULLCONTENT): obtiene el contenido aunque
       la ventana esté parcialmente tapada por otras.
    2) Si devuelve una imagen negra, se copia desde la pantalla (solo es válido si
       la mesa está visible; quien llama lo comprueba con is_fully_visible()).
    Devuelve (imagen BGR, método).
    """
    if not IS_WINDOWS:
        return None, "no-windows"
    rc = client_rect_screen(hwnd)
    if not rc or rc[2] < 50 or rc[3] < 50:
        return None, "tamaño inválido"
    x, y, w, h = rc
    hdc_win = user32.GetDC(hwnd)
    if not hdc_win:
        return None, "GetDC falló"
    mem = gdi32.CreateCompatibleDC(hdc_win)
    bmp = gdi32.CreateCompatibleBitmap(hdc_win, w, h)
    old = gdi32.SelectObject(mem, bmp)
    img, method = None, ""
    try:
        if user32.PrintWindow(hwnd, mem, PW_CLIENTONLY | PW_RENDERFULLCONTENT):
            img = _dib_to_array(mem, bmp, w, h)
            method = "PrintWindow"
            if img is not None and img.max() < 8:
                img = None  # negra: la ventana no se deja capturar así
        if img is None:
            hdc_scr = user32.GetDC(None)
            try:
                if gdi32.BitBlt(mem, 0, 0, w, h, hdc_scr, x, y, SRCCOPY):
                    img = _dib_to_array(mem, bmp, w, h)
                    method = "pantalla"
            finally:
                user32.ReleaseDC(None, hdc_scr)
    finally:
        gdi32.SelectObject(mem, old)
        gdi32.DeleteObject(bmp)
        gdi32.DeleteDC(mem)
        user32.ReleaseDC(hwnd, hdc_win)
    return img, method


def is_fully_visible(hwnd: int) -> bool:
    """Comprueba (con 9 puntos) que ninguna otra ventana tapa la mesa."""
    if not IS_WINDOWS:
        return False
    rc = client_rect_screen(hwnd)
    if not rc:
        return False
    x, y, w, h = rc
    for fx in (0.05, 0.5, 0.95):
        for fy in (0.05, 0.5, 0.95):
            p = wintypes.POINT(int(x + w * fx), int(y + h * fy))
            hit = user32.WindowFromPoint(p)
            root = user32.GetAncestor(hit, GA_ROOT) if hit else None
            if not root or int(root) != int(hwnd):
                return False
    return True


def set_owner(child_hwnd: int, owner_hwnd: int) -> None:
    """Hace que la ventana del overlay sea 'propiedad' de la mesa: Windows la mantiene
    siempre justo encima de su mesa (respeta el orden de ventanas) y la oculta
    cuando la mesa se minimiza."""
    if IS_WINDOWS:
        user32.SetWindowLongPtrW(child_hwnd, GWLP_HWNDPARENT, owner_hwnd)


def add_ex_style(hwnd: int, flags: int, remove: int = 0) -> None:
    if not IS_WINDOWS:
        return
    st = user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
    user32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, (st | flags) & ~remove)


def move_window(hwnd: int, x: int, y: int, w: int, h: int) -> None:
    if IS_WINDOWS:
        user32.SetWindowPos(hwnd, None, x, y, w, h, SWP_NOACTIVATE | SWP_NOZORDER | SWP_NOOWNERZORDER)
