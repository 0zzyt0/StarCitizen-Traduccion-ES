# -*- mode: python ; coding: utf-8 -*-
# PyInstaller: genera dist/SCTraduccionES/ (carpeta) que luego empaqueta Inno Setup.
# Uso (desde la raíz del repositorio):  pyinstaller installer/SCTraduccionES.spec --noconfirm
from pathlib import Path

root = Path(SPECPATH).parent

a = Analysis(
    [str(root / "app" / "main.py")],
    pathex=[str(root / "app")],
    datas=[
        (str(root / "config" / "app_config.json"), "config"),
        (str(root / "assets" / "icono.ico"), "assets"),
        (str(root / "assets" / "icono.png"), "assets"),
        (str(root / "assets" / "check.svg"), "assets"),
    ],
    hiddenimports=["sctrad.gui.app", "sctrad.gui.manager", "sctrad.gui.wizard", "PySide6.QtSvg"],
    excludes=[
        "tkinter", "unittest", "pydoc", "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuickWidgets",
        "PySide6.QtPdf", "PySide6.QtSql", "PySide6.QtTest", "PySide6.QtOpenGL", "PySide6.QtOpenGLWidgets",
        "PySide6.QtDesigner", "PySide6.QtHelp", "PySide6.QtMultimedia", "PySide6.QtWebEngineCore",
        "PySide6.QtWebEngineWidgets", "PySide6.QtCharts", "PySide6.Qt3DCore",
    ],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="SCTraduccionES",
    console=False,
    icon=str(root / "assets" / "icono.ico"),
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="SCTraduccionES", upx=False)
