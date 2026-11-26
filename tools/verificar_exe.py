"""Comprueba que el ejecutable contiene los recursos necesarios.

Uso: python tools/verificar_exe.py dist/NexaNotes.exe
Devuelve código 0 si todo está incluido y 1 si falta algo.
"""
import sys

from PyInstaller.archive.readers import CArchiveReader

REQUIRED = [
    "rapidocr_onnxruntime/config.yaml",
    "rapidocr_onnxruntime/models/ch_PP-OCRv4_det_infer.onnx",
    "rapidocr_onnxruntime/models/ch_PP-OCRv4_rec_infer.onnx",
    "rapidocr_onnxruntime/models/ch_ppocr_mobile_v2.0_cls_infer.onnx",
    "assets/selftest.png",
    "assets/logo.png",
    "assets/icon.ico",
]


def main(path: str) -> int:
    reader = CArchiveReader(path)
    names = {n.replace("\\", "/") for n in reader.toc}
    has_ort = any("onnxruntime" in n and (n.endswith(".dll") or n.endswith(".so") or ".so." in n or n.endswith(".pyd"))
                  for n in names)
    missing = [r for r in REQUIRED if r not in names]
    print(f"Archivos en el ejecutable: {len(names)}")
    for r in REQUIRED:
        print(("  OK    " if r in names else "  FALTA ") + r)
    print(("  OK    " if has_ort else "  FALTA ") + "bibliotecas de onnxruntime")
    if missing or not has_ort:
        print("ERROR: faltan recursos en el ejecutable")
        return 1
    print("Todos los recursos están incluidos")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
