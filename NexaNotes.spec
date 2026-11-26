# -*- mode: python ; coding: utf-8 -*-
# Especificación de PyInstaller para NexaNotes.exe (un solo archivo portable).
# Incluye explícitamente los modelos ONNX y el config.yaml de RapidOCR, que en
# versiones anteriores no se empaquetaban.
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

datas = collect_data_files("rapidocr_onnxruntime", includes=["**/*.yaml", "**/*.onnx", "**/*.txt"])
datas += [("assets/selftest.png", "assets"), ("assets/logo.png", "assets"), ("assets/icon.ico", "assets")]
binaries = collect_dynamic_libs("onnxruntime")

a = Analysis(
    ["nexa_notes.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=["rapidocr_onnxruntime"],
    excludes=["tkinter", "matplotlib", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets",
              "PySide6.Qt3DCore", "PySide6.QtQuick", "PySide6.QtQml", "PySide6.QtMultimedia"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="NexaNotes",
    debug=False,
    strip=False,
    upx=False,
    console=False,
    icon="assets/icon.ico",
)
