"""Genera assets/logo.png y assets/icon.ico (solo formas, sin archivos de fuentes).

Los archivos generados ya están incluidos en el proyecto; este script solo hace
falta si se quiere cambiar el logotipo.
"""
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent


def draw_logo(size: int) -> Image.Image:
    s = size
    im = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    r = int(s * 0.22)
    d.rounded_rectangle([0, 0, s - 1, s - 1], r, fill=(23, 27, 36, 255))
    # etiqueta de jugador con borde de color
    pad = int(s * 0.16)
    top, bot = int(s * 0.30), int(s * 0.78)
    d.rounded_rectangle([pad, top, s - pad, bot], int(s * 0.07), outline=(239, 68, 68, 255),
                        width=max(2, s // 18), fill=(12, 14, 18, 255))
    # letra N con trazos
    w = max(2, s // 14)
    x0, x1 = int(s * 0.36), int(s * 0.64)
    y0, y1 = int(s * 0.39), int(s * 0.69)
    d.line([(x0, y1), (x0, y0), (x1, y1), (x1, y0)], fill=(243, 244, 246, 255), width=w, joint="curve")
    # avatar
    c, rr = s // 2, int(s * 0.11)
    d.ellipse([c - rr, int(s * 0.08), c + rr, int(s * 0.08) + 2 * rr], fill=(59, 130, 246, 255))
    return im


def main():
    out = ROOT / "assets"
    out.mkdir(exist_ok=True)
    big = draw_logo(256)
    big.save(out / "logo.png")
    big.save(out / "icon.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print("assets generados")


if __name__ == "__main__":
    main()
