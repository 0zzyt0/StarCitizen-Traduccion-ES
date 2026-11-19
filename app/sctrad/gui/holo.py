"""Elementos visuales estilo holograma (fondo animado, marcos HUD, logo proyectado, brillo)."""

from __future__ import annotations

import math
import os
import random

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import (QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap,
                           QRadialGradient)
from PySide6.QtWidgets import QFrame, QGraphicsDropShadowEffect, QWidget

from ..config import resource_path

CYAN = QColor(56, 214, 255)
CYAN_SOFT = QColor(56, 214, 255, 60)
VIOLET = QColor(180, 123, 255)
CHANNEL_COLORS = {"LIVE": QColor(56, 214, 255), "PTU": QColor(180, 123, 255),
                  "EPTU": QColor(255, 140, 220), "HOTFIX": QColor(255, 122, 69),
                  "TECH-PREVIEW": QColor(255, 196, 92)}


# ----------------------------------------------------------------- fondo
class HoloBackdrop:
    """Dibuja el fondo: degradado espacial, estrellas, rejilla de proyección y líneas de barrido.

    La parte estática se cachea en un QPixmap por tamaño; solo el barrido se anima.
    """

    def __init__(self, seed: int = 7):
        self._cache: QPixmap | None = None
        self._size = None
        rnd = random.Random(seed)
        self._stars = [(rnd.random(), rnd.random() * 0.75, rnd.random() * 1.4 + 0.3, rnd.randint(40, 200))
                       for _ in range(220)]

    def _render(self, w: int, h: int) -> QPixmap:
        pm = QPixmap(w, h)
        pm.fill(QColor(2, 6, 13))
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        g = QLinearGradient(0, 0, 0, h)
        g.setColorAt(0, QColor(1, 4, 10))
        g.setColorAt(0.55, QColor(4, 14, 30))
        g.setColorAt(1, QColor(3, 20, 38))
        p.fillRect(0, 0, w, h, g)
        # Nebulosa / brillo del proyector
        rg = QRadialGradient(QPointF(w * 0.5, h * 0.05), max(w, h) * 0.7)
        rg.setColorAt(0, QColor(30, 140, 220, 70))
        rg.setColorAt(0.5, QColor(10, 60, 120, 25))
        rg.setColorAt(1, QColor(0, 0, 0, 0))
        p.fillRect(0, 0, w, h, rg)
        # Estrellas
        p.setPen(Qt.NoPen)
        for x, y, r, a in self._stars:
            p.setBrush(QColor(200, 235, 255, a))
            p.drawEllipse(QPointF(x * w, y * h), r, r)
        # Rejilla de proyección en perspectiva (suelo holográfico)
        horizon = h * 0.72
        pen = QPen(QColor(56, 214, 255, 26))
        pen.setWidthF(1.0)
        p.setPen(pen)
        cx = w / 2
        for i in range(-24, 25):
            p.drawLine(QPointF(cx + i * 18, horizon), QPointF(cx + i * w / 9, h))
        y, step = horizon, 4.0
        while y < h:
            p.drawLine(QPointF(0, y), QPointF(w, y))
            step *= 1.28
            y += step
        fade = QLinearGradient(0, horizon - 40, 0, horizon + 60)
        fade.setColorAt(0, QColor(3, 12, 26, 255))
        fade.setColorAt(1, QColor(3, 12, 26, 0))
        p.fillRect(QRectF(0, horizon - 40, w, 100), fade)
        # Líneas de barrido (scanlines)
        p.setPen(QPen(QColor(120, 220, 255, 10), 1))
        for yy in range(0, h, 3):
            p.drawLine(0, yy, w, yy)
        # Viñeta
        vg = QRadialGradient(QPointF(w / 2, h / 2), max(w, h) * 0.75)
        vg.setColorAt(0.6, QColor(0, 0, 0, 0))
        vg.setColorAt(1, QColor(0, 0, 0, 150))
        p.fillRect(0, 0, w, h, vg)
        p.end()
        return pm

    def paint(self, p: QPainter, rect, phase: float) -> None:
        w, h = rect.width(), rect.height()
        if self._cache is None or self._size != (w, h):
            self._cache = self._render(max(w, 1), max(h, 1))
            self._size = (w, h)
        p.drawPixmap(0, 0, self._cache)
        # Barrido luminoso que baja lentamente
        y = (phase % 1.0) * (h + 160) - 80
        g = QLinearGradient(0, y - 60, 0, y + 60)
        g.setColorAt(0, QColor(56, 214, 255, 0))
        g.setColorAt(0.5, QColor(56, 214, 255, 18))
        g.setColorAt(1, QColor(56, 214, 255, 0))
        p.fillRect(QRectF(0, y - 60, w, 120), g)


class AnimatedBackdropMixin:
    """Añade el fondo holográfico animado a una ventana (QMainWindow central, QWizard, QDialog)."""

    def _init_backdrop(self, period_ms: int = 9000, fps: int = 20):
        self._backdrop = HoloBackdrop()
        self._phase = 0.0
        self._phase_step = (1000 / fps) / period_ms
        self._anim = QTimer(self)
        self._anim.timeout.connect(self._tick_backdrop)
        if not os.environ.get("SCTRAD_NO_ANIM"):
            self._anim.start(int(1000 / fps))

    def _tick_backdrop(self):
        if self.isVisible() and not self.isMinimized():
            self._phase = (self._phase + self._phase_step) % 1.0
            self.update()

    def _paint_backdrop(self):
        p = QPainter(self)
        self._backdrop.paint(p, self.rect(), self._phase)
        p.end()


class HoloSurface(AnimatedBackdropMixin, QWidget):
    """Widget central con fondo holográfico."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_backdrop()

    def paintEvent(self, ev):
        self._paint_backdrop()


# ----------------------------------------------------------------- marcos
class HoloFrame(QFrame):
    """Panel translúcido con borde fino y esquinas HUD."""

    def __init__(self, parent=None, accent: QColor | None = None, title: str | None = None):
        super().__init__(parent)
        self.accent = accent or CYAN
        self.title = title
        self.setAttribute(Qt.WA_StyledBackground, False)
        if title:
            self.setContentsMargins(4, 18, 4, 4)

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        top = 9 if self.title else 0
        body = r.adjusted(0, top, 0, 0)
        cut = 14
        path = QPainterPath()
        path.moveTo(body.left() + cut, body.top())
        path.lineTo(body.right(), body.top())
        path.lineTo(body.right(), body.bottom() - cut)
        path.lineTo(body.right() - cut, body.bottom())
        path.lineTo(body.left(), body.bottom())
        path.lineTo(body.left(), body.top() + cut)
        path.closeSubpath()
        g = QLinearGradient(0, body.top(), 0, body.bottom())
        g.setColorAt(0, QColor(10, 40, 68, 150))
        g.setColorAt(1, QColor(4, 18, 34, 175))
        p.fillPath(path, g)
        a = QColor(self.accent)
        a.setAlpha(70)
        p.setPen(QPen(a, 1))
        p.drawPath(path)
        # Esquinas brillantes
        a.setAlpha(230)
        p.setPen(QPen(a, 2))
        L = 18
        p.drawLine(QPointF(body.left(), body.top() + cut), QPointF(body.left() + cut, body.top()))
        p.drawLine(QPointF(body.left() + cut, body.top()), QPointF(body.left() + cut + L, body.top()))
        p.drawLine(QPointF(body.right(), body.bottom() - cut), QPointF(body.right() - cut, body.bottom()))
        p.drawLine(QPointF(body.right() - cut, body.bottom()), QPointF(body.right() - cut - L, body.bottom()))
        p.drawLine(QPointF(body.right(), body.top()), QPointF(body.right() - L, body.top()))
        p.drawLine(QPointF(body.right(), body.top()), QPointF(body.right(), body.top() + L))
        p.drawLine(QPointF(body.left(), body.bottom()), QPointF(body.left() + L, body.bottom()))
        p.drawLine(QPointF(body.left(), body.bottom()), QPointF(body.left(), body.bottom() - L))
        if self.title:
            f = p.font()
            f.setFamily("Orbitron")
            f.setPointSizeF(7.5)
            f.setBold(True)
            f.setLetterSpacing(QFont.AbsoluteSpacing, 2)
            p.setFont(f)
            text = f"▸ {self.title.upper()}"
            tw = p.fontMetrics().horizontalAdvance(text) + 18
            tab = QRectF(body.left() + cut + 6, r.top(), tw, 18)
            p.fillRect(tab, QColor(4, 14, 28, 235))
            p.setPen(QPen(QColor(self.accent.red(), self.accent.green(), self.accent.blue(), 200), 1))
            p.drawText(tab, Qt.AlignCenter, text)
        p.end()


# ----------------------------------------------------------------- logo
class HoloLogo(QWidget):
    """Logo proyectado con anillos holográficos girando y halo."""

    def __init__(self, size: int = 220, parent=None, animated: bool = True):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self._pm = QPixmap(str(resource_path("assets", "logo_sc_es.png")))
        self._angle = 0.0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        if animated and not os.environ.get("SCTRAD_NO_ANIM"):
            self._timer.start(33)

    def _tick(self):
        if self.isVisible():
            self._angle = (self._angle + 0.7) % 360
            self.update()

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        w, h = self.width(), self.height()
        c = QPointF(w / 2, h / 2)
        R = min(w, h) / 2 - 4
        halo = QRadialGradient(c, R)
        halo.setColorAt(0, QColor(56, 214, 255, 70))
        halo.setColorAt(0.6, QColor(56, 214, 255, 18))
        halo.setColorAt(1, QColor(56, 214, 255, 0))
        p.setPen(Qt.NoPen)
        p.setBrush(halo)
        p.drawEllipse(c, R, R)
        # Anillo exterior fino y anillo de segmentos girando
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(56, 214, 255, 70), 1))
        p.drawEllipse(c, R - 2, R - 2)
        p.save()
        p.translate(c)
        p.rotate(self._angle)
        pen = QPen(QColor(56, 214, 255, 190), 2.2)
        pen.setCapStyle(Qt.FlatCap)
        p.setPen(pen)
        rr = R - 9
        for i in range(6):
            p.drawArc(QRectF(-rr, -rr, 2 * rr, 2 * rr), int((i * 60) * 16), int(26 * 16))
        p.rotate(-2.4 * self._angle)
        p.setPen(QPen(QColor(180, 123, 255, 130), 1.4))
        rr2 = R - 17
        for i in range(12):
            p.drawArc(QRectF(-rr2, -rr2, 2 * rr2, 2 * rr2), int((i * 30) * 16), int(8 * 16))
        p.restore()
        # Marcas de mira
        p.setPen(QPen(QColor(56, 214, 255, 110), 1))
        for ang in (0, 90, 180, 270):
            a = math.radians(ang)
            p.drawLine(QPointF(c.x() + math.cos(a) * (R - 2), c.y() + math.sin(a) * (R - 2)),
                       QPointF(c.x() + math.cos(a) * (R + 4), c.y() + math.sin(a) * (R + 4)))
        if not self._pm.isNull():
            side = (R - 22) * 2
            pm = self._pm.scaled(int(side), int(side), Qt.KeepAspectRatio, Qt.SmoothTransformation)
            p.setOpacity(0.97)
            p.drawPixmap(int(c.x() - pm.width() / 2), int(c.y() - pm.height() / 2), pm)
        p.end()


# ----------------------------------------------------------------- utilidades
def glow(widget: QWidget, color: QColor = CYAN, radius: int = 22) -> None:
    eff = QGraphicsDropShadowEffect(widget)
    eff.setColor(QColor(color.red(), color.green(), color.blue(), 170))
    eff.setBlurRadius(radius)
    eff.setOffset(0, 0)
    widget.setGraphicsEffect(eff)


def dark_titlebar(widget: QWidget) -> None:
    """Barra de título oscura en Windows 10/11 (si el sistema lo permite)."""
    if os.name != "nt":
        return
    try:
        import ctypes

        hwnd = int(widget.winId())
        dwm = ctypes.windll.dwmapi
        on = ctypes.c_int(1)
        for attr in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE (20H1+ / anterior)
            if dwm.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(on), ctypes.sizeof(on)) == 0:
                break
        caption = ctypes.c_int(0x00160B04)  # COLORREF BGR de #040B16
        dwm.DwmSetWindowAttribute(hwnd, 35, ctypes.byref(caption), ctypes.sizeof(caption))
    except Exception:  # noqa: BLE001
        pass
