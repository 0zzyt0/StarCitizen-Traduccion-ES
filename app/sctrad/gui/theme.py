"""Aspecto visual: tema oscuro con acentos cian."""

from __future__ import annotations

from PySide6.QtGui import QColor, QFont, QIcon, QPalette
from PySide6.QtWidgets import QApplication

from ..config import resource_path

ACCENT = "#38bdf8"
OK = "#4ade80"
WARN = "#fbbf24"
BAD = "#f87171"
MUTED = "#94a3b8"

QSS = f"""
QWidget {{ background: #0f172a; color: #e2e8f0; font-size: 10pt; }}
QWizard, QMainWindow, QDialog {{ background: #0f172a; }}
QLabel#Title {{ font-size: 18pt; font-weight: 600; color: #f8fafc; }}
QLabel#Subtitle {{ color: {MUTED}; }}
QLabel#Banner {{ background: #1e3a5f; border: 1px solid {ACCENT}; border-radius: 6px; padding: 8px; }}
QLabel#Warning {{ background: #422006; border: 1px solid {WARN}; border-radius: 6px; padding: 8px; }}
QLabel#Error {{ background: #450a0a; border: 1px solid {BAD}; border-radius: 6px; padding: 8px; }}
QFrame#Card {{ background: #111c33; border: 1px solid #1e293b; border-radius: 8px; }}
QPushButton {{ background: #1e293b; border: 1px solid #334155; border-radius: 6px; padding: 7px 14px; }}
QPushButton:hover {{ border-color: {ACCENT}; }}
QPushButton:disabled {{ color: #475569; border-color: #1e293b; }}
QPushButton#Primary {{ background: #0369a1; border-color: {ACCENT}; color: white; font-weight: 600; }}
QPushButton#Primary:hover {{ background: #0284c7; }}
QPushButton#Danger:hover {{ border-color: {BAD}; }}
QTreeWidget, QTextBrowser, QPlainTextEdit, QListWidget {{
    background: #0b1222; border: 1px solid #1e293b; border-radius: 6px; }}
QTreeWidget::item {{ padding: 5px 2px; }}
QTreeWidget::item:selected {{ background: #0c4a6e; }}
QHeaderView::section {{ background: #111c33; color: {MUTED}; border: none; padding: 6px; }}
QTabWidget::pane {{ border: 1px solid #1e293b; border-radius: 6px; top: -1px; }}
QTabBar::tab {{ background: #111c33; padding: 8px 16px; border-top-left-radius: 6px;
    border-top-right-radius: 6px; margin-right: 2px; color: {MUTED}; }}
QTabBar::tab:selected {{ background: #1e293b; color: #f8fafc; }}
QProgressBar {{ background: #0b1222; border: 1px solid #1e293b; border-radius: 6px; text-align: center;
    height: 18px; }}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 5px; }}
QCheckBox, QRadioButton {{ spacing: 8px; background: transparent; }}
QComboBox, QSpinBox {{ background: #1e293b; border: 1px solid #334155; border-radius: 6px; padding: 4px 8px; }}
QStatusBar {{ color: {MUTED}; }}
QToolTip {{ background: #1e293b; color: #e2e8f0; border: 1px solid {ACCENT}; }}
QCheckBox::indicator, QTreeWidget::indicator {{ width: 16px; height: 16px; border: 1px solid #64748b;
    border-radius: 4px; background: #0b1222; }}
QCheckBox::indicator:checked, QTreeWidget::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT};
    image: url(__CHECK__); }}
QCheckBox::indicator:disabled, QTreeWidget::indicator:disabled {{ background: #1e293b; border-color: #334155; }}
QRadioButton::indicator {{ width: 14px; height: 14px; border: 1px solid #64748b; border-radius: 8px;
    background: #0b1222; }}
QRadioButton::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}
QRadioButton::indicator:disabled {{ background: #1e293b; }}
"""


def app_icon() -> QIcon:
    for name in ("icono.ico", "icono.png"):
        p = resource_path("assets", name)
        if p.exists():
            return QIcon(str(p))
    return QIcon()


def apply_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    pal = app.palette()
    pal.setColor(QPalette.Window, QColor("#0f172a"))
    pal.setColor(QPalette.WindowText, QColor("#e2e8f0"))
    pal.setColor(QPalette.Base, QColor("#0b1222"))
    pal.setColor(QPalette.Text, QColor("#e2e8f0"))
    pal.setColor(QPalette.Button, QColor("#1e293b"))
    pal.setColor(QPalette.ButtonText, QColor("#e2e8f0"))
    pal.setColor(QPalette.Highlight, QColor("#0c4a6e"))
    pal.setColor(QPalette.Link, QColor(ACCENT))
    app.setPalette(pal)
    f = QFont("Segoe UI", 10)
    app.setFont(f)
    check = resource_path("assets", "check.svg").as_posix()
    app.setStyleSheet(QSS.replace("__CHECK__", check))
    app.setWindowIcon(app_icon())
