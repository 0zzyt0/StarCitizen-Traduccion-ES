"""Tema visual estilo holograma de Star Citizen (cian sobre azul noche)."""

from __future__ import annotations

from PySide6.QtGui import QColor, QFont, QFontDatabase, QIcon, QPalette
from PySide6.QtWidgets import QApplication

from ..config import resource_path

ACCENT = "#38d6ff"
OK = "#3dffb0"
WARN = "#ffb347"
BAD = "#ff5d6c"
MUTED = "#6fa3b8"
TEXT = "#d8f6ff"
TITLE_FONT = "Orbitron"
BODY_FONT = "Rajdhani"

QSS = f"""
* {{ font-family: "{BODY_FONT}", "Segoe UI"; }}
QWidget {{ color: {TEXT}; font-size: 11.5pt; }}
QMainWindow, QDialog, QMessageBox, QWizard {{ background: #030a16; }}
QWizardPage, QStackedWidget, QScrollArea, QScrollArea > QWidget > QWidget, QTabWidget > QWidget {{
    background: transparent; }}
QLabel {{ background: transparent; }}
QLabel#Title {{ font-family: "{TITLE_FONT}"; font-size: 17pt; font-weight: 700; color: #ecfbff;
    letter-spacing: 2px; }}
QLabel#Subtitle {{ color: {MUTED}; font-size: 11pt; letter-spacing: 1px; }}
QLabel#Kicker {{ font-family: "{TITLE_FONT}"; font-size: 8pt; color: {ACCENT}; letter-spacing: 3px; }}
QLabel#Banner {{ background: rgba(56,214,255,0.10); border: 1px solid rgba(56,214,255,0.55);
    border-left: 3px solid {ACCENT}; padding: 9px 12px; }}
QLabel#Warning {{ background: rgba(255,179,71,0.10); border: 1px solid rgba(255,179,71,0.55);
    border-left: 3px solid {WARN}; padding: 9px 12px; }}
QLabel#Error {{ background: rgba(255,93,108,0.12); border: 1px solid rgba(255,93,108,0.6);
    border-left: 3px solid {BAD}; padding: 9px 12px; }}
QPushButton {{ font-family: "{TITLE_FONT}"; font-size: 8.5pt; letter-spacing: 1px; color: #bff3ff;
    background: rgba(56,214,255,0.07); border: 1px solid rgba(56,214,255,0.45); padding: 9px 16px;
    border-radius: 2px; }}
QPushButton:hover {{ background: rgba(56,214,255,0.18); border-color: {ACCENT}; color: #ffffff; }}
QPushButton:pressed {{ background: rgba(56,214,255,0.30); }}
QPushButton:disabled {{ color: #2e5566; border-color: rgba(56,214,255,0.15); background: transparent; }}
QPushButton#Primary {{ color: #031220; font-weight: 700;
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #7ae6ff, stop:1 #1fb8f0); border: 1px solid #a5f0ff; }}
QPushButton#Primary:hover {{ background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #a5f0ff, stop:1 #38d6ff); }}
QPushButton#Primary:disabled {{ background: rgba(56,214,255,0.12); color: #2e5566; border-color: rgba(56,214,255,0.2); }}
QPushButton#Danger {{ border-color: rgba(255,93,108,0.55); color: #ffc2c8; background: rgba(255,93,108,0.07); }}
QPushButton#Danger:hover {{ border-color: {BAD}; background: rgba(255,93,108,0.18); color: white; }}
QTreeWidget, QTextBrowser, QPlainTextEdit, QListWidget {{
    background: rgba(2,10,22,0.72); border: 1px solid rgba(56,214,255,0.25); border-radius: 0px;
    alternate-background-color: rgba(56,214,255,0.035); selection-background-color: rgba(56,214,255,0.22);
    selection-color: #ffffff; }}
QTreeWidget::item {{ padding: 7px 3px; border-bottom: 1px solid rgba(56,214,255,0.07); }}
QTreeWidget::item:selected {{ background: rgba(56,214,255,0.20); }}
QTreeWidget::item:hover {{ background: rgba(56,214,255,0.08); }}
QHeaderView::section {{ font-family: "{TITLE_FONT}"; font-size: 7.5pt; letter-spacing: 1px; color: {ACCENT};
    background: rgba(4,20,38,0.9); border: none; border-bottom: 1px solid rgba(56,214,255,0.45); padding: 7px 5px; }}
QTabWidget::pane {{ border: 1px solid rgba(56,214,255,0.22); top: -1px; background: rgba(2,10,22,0.35); }}
QTabBar::tab {{ font-family: "{TITLE_FONT}"; font-size: 8pt; letter-spacing: 2px; color: {MUTED};
    background: transparent; padding: 10px 20px; border-bottom: 2px solid transparent; }}
QTabBar::tab:selected {{ color: #ecfbff; border-bottom: 2px solid {ACCENT}; background: rgba(56,214,255,0.08); }}
QTabBar::tab:hover {{ color: #bff3ff; }}
QProgressBar {{ background: rgba(2,10,22,0.8); border: 1px solid rgba(56,214,255,0.4); text-align: center;
    height: 16px; font-family: "{TITLE_FONT}"; font-size: 7.5pt; color: #ecfbff; }}
QProgressBar::chunk {{ background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #1590c8, stop:1 #7ae6ff); }}
QCheckBox, QRadioButton {{ spacing: 9px; background: transparent; }}
QCheckBox::indicator, QTreeWidget::indicator {{ width: 15px; height: 15px; border: 1px solid rgba(56,214,255,0.6);
    background: rgba(2,10,22,0.8); }}
QCheckBox::indicator:checked, QTreeWidget::indicator:checked {{ background: {ACCENT}; border-color: #a5f0ff;
    image: url(__CHECK__); }}
QCheckBox::indicator:disabled, QTreeWidget::indicator:disabled {{ background: #0b1a2a; border-color: #18384a; }}
QRadioButton::indicator {{ width: 13px; height: 13px; border: 1px solid rgba(56,214,255,0.6); border-radius: 7px;
    background: rgba(2,10,22,0.8); }}
QRadioButton::indicator:checked {{ background: {ACCENT}; border-color: #a5f0ff; }}
QComboBox, QSpinBox {{ background: rgba(2,10,22,0.85); border: 1px solid rgba(56,214,255,0.45);
    padding: 5px 9px; color: {TEXT}; }}
QComboBox QAbstractItemView {{ background: #041226; border: 1px solid {ACCENT};
    selection-background-color: rgba(56,214,255,0.3); }}
QStatusBar {{ color: {MUTED}; background: rgba(2,8,18,0.92); border-top: 1px solid rgba(56,214,255,0.25); }}
QToolTip {{ background: #041226; color: {TEXT}; border: 1px solid {ACCENT}; padding: 5px; }}
QScrollBar:vertical {{ background: transparent; width: 10px; }}
QScrollBar::handle:vertical {{ background: rgba(56,214,255,0.35); min-height: 30px; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; }}
QScrollBar::handle:horizontal {{ background: rgba(56,214,255,0.35); min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
"""


def app_icon() -> QIcon:
    for name in ("icono.ico", "icono.png"):
        p = resource_path("assets", name)
        if p.exists():
            return QIcon(str(p))
    return QIcon()


def load_fonts() -> None:
    folder = resource_path("assets", "fonts")
    if folder.is_dir():
        for f in sorted(folder.glob("*.ttf")):
            QFontDatabase.addApplicationFont(str(f))


def title_font(size: float = 10, bold: bool = True) -> QFont:
    f = QFont(TITLE_FONT)
    f.setPointSizeF(size)
    f.setBold(bold)
    f.setLetterSpacing(QFont.AbsoluteSpacing, 1.5)
    return f


def apply_theme(app: QApplication) -> None:
    load_fonts()
    app.setStyle("Fusion")
    pal = app.palette()
    pal.setColor(QPalette.Window, QColor("#030a16"))
    pal.setColor(QPalette.WindowText, QColor(TEXT))
    pal.setColor(QPalette.Base, QColor("#020a16"))
    pal.setColor(QPalette.AlternateBase, QColor("#061629"))
    pal.setColor(QPalette.Text, QColor(TEXT))
    pal.setColor(QPalette.Button, QColor("#06182b"))
    pal.setColor(QPalette.ButtonText, QColor(TEXT))
    pal.setColor(QPalette.Highlight, QColor(56, 214, 255, 90))
    pal.setColor(QPalette.HighlightedText, QColor("#ffffff"))
    pal.setColor(QPalette.Link, QColor(ACCENT))
    pal.setColor(QPalette.ToolTipBase, QColor("#041226"))
    pal.setColor(QPalette.ToolTipText, QColor(TEXT))
    app.setPalette(pal)
    f = QFont(BODY_FONT)
    f.setPointSizeF(11.5)
    app.setFont(f)
    check = resource_path("assets", "check.svg").as_posix()
    app.setStyleSheet(QSS.replace("__CHECK__", check))
    app.setWindowIcon(app_icon())
