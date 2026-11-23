"""Tira de avisos estilo HUD/MFD: una sola línea naranja con el texto desplazándose en horizontal."""

from __future__ import annotations

import os

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFontMetricsF, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

from .theme import title_font

ORANGE = QColor(255, 157, 46)
TEXT = QColor(255, 196, 120)
SEP = "   ◆   "


class NoticeTicker(QWidget):
    """Muestra los avisos (lista de NoticeLine) en una línea que se desplaza de derecha a izquierda."""

    HEIGHT = 30
    SPEED = 55.0   # píxeles por segundo
    TAG = "AVISO"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(self.HEIGHT)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.font_text = title_font(9)
        self.font_tag = title_font(8)
        self.text = ""
        self.offset = 0.0
        self.blink = True
        self.animated = not os.environ.get("SCTRAD_NO_ANIM")
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)
        self._blink_timer = QTimer(self)
        self._blink_timer.setInterval(600)
        self._blink_timer.timeout.connect(self._toggle_blink)

    # ------------------------------------------------------------------ datos
    def set_lines(self, lines) -> None:
        parts = [f"{ln.channel} · {ln.text}" if ln.channel else ln.text for ln in lines]
        text = SEP.join(parts)
        if text != self.text:
            self.text = text
            self.offset = 0.0
            self.setToolTip("\n".join(parts))
        self.setVisible(bool(text))
        self._sync_timers()
        self.update()

    def _sync_timers(self) -> None:
        run = bool(self.text) and self.animated and self.isVisible()
        for t in (self._timer, self._blink_timer):
            if run and not t.isActive():
                t.start()
            elif not run and t.isActive():
                t.stop()

    def showEvent(self, ev):
        super().showEvent(ev)
        self._sync_timers()

    def hideEvent(self, ev):
        super().hideEvent(ev)
        self._sync_timers()

    def _tick(self) -> None:
        self.offset += self.SPEED * self._timer.interval() / 1000.0
        self.update(self._text_rect().toAlignedRect())

    def _toggle_blink(self) -> None:
        self.blink = not self.blink
        self.update()

    # --------------------------------------------------------------- dibujo
    def _tag_width(self) -> float:
        return QFontMetricsF(self.font_tag).horizontalAdvance(self.TAG) + 34

    def _text_rect(self) -> QRectF:
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        return r.adjusted(self._tag_width() + 10, 0, -10, 0)

    def paintEvent(self, _ev) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        c = 7.0  # esquinas biseladas, como un panel MFD
        frame = QPainterPath()
        frame.moveTo(r.left() + c, r.top())
        frame.lineTo(r.right(), r.top())
        frame.lineTo(r.right(), r.bottom() - c)
        frame.lineTo(r.right() - c, r.bottom())
        frame.lineTo(r.left(), r.bottom())
        frame.lineTo(r.left(), r.top() + c)
        frame.closeSubpath()
        bg = QLinearGradient(r.topLeft(), r.bottomLeft())
        bg.setColorAt(0, QColor(40, 22, 4, 200))
        bg.setColorAt(1, QColor(18, 10, 2, 220))
        p.fillPath(frame, bg)
        # Líneas de barrido (scanlines) muy tenues
        p.setPen(QPen(QColor(255, 157, 46, 14), 1))
        y = r.top() + 2
        while y < r.bottom():
            p.drawLine(QPointF(r.left() + 2, y), QPointF(r.right() - 2, y))
            y += 3
        p.setPen(QPen(ORANGE, 1.2))
        p.drawPath(frame)

        # Etiqueta «AVISO» con piloto parpadeante
        tw = self._tag_width()
        tag = QPainterPath()
        tag.moveTo(r.left() + c, r.top())
        tag.lineTo(r.left() + tw, r.top())
        tag.lineTo(r.left() + tw - 8, r.bottom())
        tag.lineTo(r.left(), r.bottom())
        tag.lineTo(r.left(), r.top() + c)
        tag.closeSubpath()
        p.fillPath(tag, ORANGE)
        led = QColor(40, 14, 0) if self.blink else QColor(120, 50, 0)
        p.setPen(Qt.NoPen)
        p.setBrush(led)
        p.drawEllipse(QPointF(r.left() + 11, r.center().y()), 3.2, 3.2)
        p.setFont(self.font_tag)
        p.setPen(QColor(30, 12, 0))
        p.drawText(QRectF(r.left() + 18, r.top(), tw - 24, r.height()), Qt.AlignVCenter | Qt.AlignLeft, self.TAG)

        # Texto desplazándose (dos copias para un bucle continuo)
        tr = self._text_rect()
        p.save()
        p.setClipRect(tr)
        p.setFont(self.font_text)
        fm = QFontMetricsF(self.font_text)
        loop = self.text + SEP
        w = fm.horizontalAdvance(loop)
        # Al abrir, el aviso empieza legible a la izquierda; luego avanza y vuelve a entrar por la derecha.
        x = tr.left() + 6 - (self.offset % w if w > 0 else 0)
        p.setPen(TEXT)
        base = tr.center().y() + (fm.ascent() - fm.descent()) / 2
        while x < tr.right():
            p.drawText(QPointF(x, base), loop)
            x += w
            if not self.animated:
                break
        p.restore()
        # Difuminado en los bordes de la zona de texto
        for left in (True, False):
            g = QLinearGradient(tr.left() if left else tr.right(), 0, tr.left() + 18 if left else tr.right() - 18, 0)
            g.setColorAt(0, QColor(30, 16, 3, 230))
            g.setColorAt(1, QColor(30, 16, 3, 0))
            band = QRectF(tr.left() if left else tr.right() - 18, tr.top() + 1, 18, tr.height() - 2)
            p.fillRect(band, g)
        p.end()
