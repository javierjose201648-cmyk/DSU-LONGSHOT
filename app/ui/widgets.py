"""Widgets dibujados a mano: el control de la app, el stick y el movimiento."""
import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from app.core import controles as CT
from app.i18n import T

MORADO = QColor("#8d4fc7")
GRIS = QColor("#3a3a3d")
GRIS_CLARO = QColor("#b9b9c0")
VERDE = QColor("#2fbf71")
AMBAR = QColor("#ffb020")
ROJO = QColor("#e5484d")
FONDO_TEL = QColor("#0b0b0d")
TEXTO = QColor("#e8e8ee")
TENUE = QColor("#8a8a96")

COLORES = {"morado": MORADO, "gris": GRIS, "fondo": FONDO_TEL}
TEXTO_VERDE = ("VERDE", "HOME")


class ControlWidget(QWidget):
    """Dibujo del control tal como se ve en el teléfono, girado según la orientación.

    control: un app.core.controles.Control
    resaltado: id físico a iluminar ("STICK" / "STICK_DER" para los sticks)
    hechos: ids en verde   presionados: ids presionados ahora   etiquetas: id -> texto extra
    stick / stick_der: (x, y) -1..1. Si el control manda el stick en el marco del
    teléfono vertical (Joy-Con) es el crudo centrado con Y abajo; si no, es el
    lógico (x derecha, y arriba).
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.control = CT.JOYCON_IZQ
        self.orientacion = "lado"
        self.resaltado = None
        self.hechos = set()
        self.presionados = set()
        self.etiquetas = {}
        self.stick = (0.0, 0.0)
        self.stick_der = (0.0, 0.0)
        self.flecha_stick = None      # (dx, dy) en coordenadas DEL USUARIO, o None
        self.fase = 0.0
        self.setMinimumSize(300, 200)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def poner_perfil(self, perfil):
        self.control = CT.control(perfil.get("control"))
        self.orientacion = perfil["orientacion"]

    # -- geometría: teléfono vertical -> pantalla
    def _lienzo(self):
        w, h = self.control.ancho, self.control.alto
        return (h, w) if self.orientacion == "lado" else (w, h)

    def _p(self, x, y):
        if self.orientacion == "lado":      # girado 90° a la izquierda
            return y, self.control.ancho - x
        return x, y

    def _rect(self, x, y, w, h):
        x1, y1 = self._p(x, y)
        x2, y2 = self._p(x + w, y + h)
        return QRectF(min(x1, x2), min(y1, y2), abs(x2 - x1), abs(y2 - y1))

    def _botones(self):
        bs = list(self.control.botones)
        if self.control.id == "joycon-izq":
            bs.append(CT.BOTON_L_JOYCON)
        return bs

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        lw, lh = self._lienzo()
        esc = min(self.width() / lw, self.height() / lh)
        p.translate((self.width() - lw * esc) / 2, (self.height() - lh * esc) / 2)
        p.scale(esc, esc)
        p.setPen(QPen(QColor("#2c2c33"), 6))
        p.setBrush(FONDO_TEL)
        p.drawRoundedRect(QRectF(3, 3, lw - 6, lh - 6), 60, 60)
        pulso = 0.5 + 0.5 * math.sin(self.fase * 2 * math.pi)

        for b in self._botones():
            fid, forma, geo, texto = b.id, b.forma, b.geo, b.corto
            color = COLORES.get(b.color, GRIS)
            relleno = QColor(color)
            borde = QPen(Qt.NoPen)
            if fid in self.hechos:
                relleno = QColor(VERDE).darker(160)
                borde = QPen(VERDE, 5)
            if fid in self.presionados:
                relleno = QColor(VERDE)
                borde = QPen(QColor("white"), 5)
            if fid == self.resaltado:
                relleno = QColor(AMBAR)
                relleno.setAlphaF(0.55 + 0.45 * pulso)
                borde = QPen(AMBAR, 6 + 8 * pulso)
            p.setPen(borde)
            p.setBrush(QBrush(relleno))
            if forma == "rect":
                r = self._rect(*geo)
                p.drawRoundedRect(r, 22, 22)
            else:
                cx, cy = self._p(geo[0], geo[1])
                r = QRectF(cx - geo[2], cy - geo[2], 2 * geo[2], 2 * geo[2])
                if color == FONDO_TEL and fid not in self.hechos and fid not in self.presionados                         and fid != self.resaltado:
                    p.setPen(QPen(QColor("#3a3a44"), 3))
                p.drawEllipse(r)
            p.setPen(QColor("#111") if fid == self.resaltado or fid in self.presionados else
                     (QColor("#3fae7a") if fid in TEXTO_VERDE else TEXTO))
            f = QFont("Segoe UI", 1)
            f.setPixelSize(max(8, int(min(r.height(), r.width()) * (0.42 if forma == "rect" else 0.62))))
            f.setBold(True)
            p.setFont(f)
            p.drawText(r, Qt.AlignCenter, texto)
            extra = self.etiquetas.get(fid)
            if extra:
                f.setPixelSize(40)
                f.setBold(False)
                p.setFont(f)
                p.setPen(QColor("#9ad"))
                p.drawText(QRectF(r.center().x() - 140, r.bottom() + 2, 280, 50), Qt.AlignCenter, extra)

        for cual, (sx, sy, sr) in self.control.sticks.items():
            sid = "STICK" if cual == "izq" else "STICK_DER"
            vec = self.stick if cual == "izq" else self.stick_der
            cx, cy = self._p(sx, sy)
            activo = self.resaltado == sid
            p.setPen(QPen(AMBAR if activo else MORADO.lighter(120), 6 + (6 * pulso if activo else 0)))
            p.setBrush(QColor("#1d1030"))
            p.drawEllipse(QPointF(cx, cy), sr + 34, sr + 34)
            if self.control.stick_vertical:
                # el vector crudo (x, y abajo) se gira igual que el teléfono
                vx, vy = (vec[1], -vec[0]) if self.orientacion == "lado" else vec
            else:
                vx, vy = vec[0], -vec[1]
            p.setPen(Qt.NoPen)
            p.setBrush(VERDE if sid in self.hechos else MORADO)
            p.drawEllipse(QPointF(cx + vx * 34, cy + vy * 34), sr - 8, sr - 8)
            if self.flecha_stick and activo:
                dx, dy = self.flecha_stick[0], -self.flecha_stick[1]
                largo = 150 + 25 * pulso
                p.setPen(QPen(AMBAR, 14, Qt.SolidLine, Qt.RoundCap))
                ini = QPointF(cx + dx * (sr + 50), cy + dy * (sr + 50))
                fin = QPointF(cx + dx * (sr + 50 + largo), cy + dy * (sr + 50 + largo))
                p.drawLine(ini, fin)
                ang = math.atan2(dy, dx)
                for s in (-1, 1):
                    a = ang + math.pi + s * 0.5
                    p.drawLine(fin, QPointF(fin.x() + 50 * math.cos(a), fin.y() + 50 * math.sin(a)))
        p.end()


JoyConWidget = ControlWidget


class StickWidget(QWidget):
    """Indicador circular del stick lógico con zona muerta y rango."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.x = self.y = 0.0
        self.crudo = None             # (x, y) antes de zona muerta, opcional
        self.zona_muerta = 0.1
        self.rango = 1.0
        self.setMinimumSize(150, 150)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = min(self.width(), self.height()) / 2 - 8
        c = QPointF(self.width() / 2, self.height() / 2)
        p.setPen(QPen(QColor("#44444f"), 2))
        p.setBrush(QColor("#17171c"))
        p.drawEllipse(c, r, r)
        p.setPen(QPen(QColor("#5a5a66"), 1, Qt.DashLine))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(c, r * self.rango, r * self.rango)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(229, 72, 77, 70))
        p.drawEllipse(c, r * self.zona_muerta, r * self.zona_muerta)
        p.setPen(QPen(QColor("#33333c"), 1))
        p.drawLine(QPointF(c.x() - r, c.y()), QPointF(c.x() + r, c.y()))
        p.drawLine(QPointF(c.x(), c.y() - r), QPointF(c.x(), c.y() + r))
        if self.crudo:
            p.setPen(QPen(TENUE, 2))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(QPointF(c.x() + self.crudo[0] * r, c.y() - self.crudo[1] * r), 6, 6)
        p.setPen(Qt.NoPen)
        p.setBrush(VERDE if (self.x or self.y) else MORADO)
        p.drawEllipse(QPointF(c.x() + self.x * r, c.y() - self.y * r), 9, 9)
        p.end()


class MovimientoWidget(QWidget):
    """Vista 2D del control que se mueve con los ángulos integrados.

    pitch/yaw/roll en grados (marco estándar). Con `meta` dibuja además el
    avance del gesto pedido: (eje 0|1|2, avance 0..1, fase 'girar'|'regresar').
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.angulos = [0.0, 0.0, 0.0]
        self.meta = None
        self.orientacion = "lado"
        self.setMinimumSize(240, 200)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        c = QPointF(w / 2, h / 2)
        pitch, yaw, roll = self.angulos
        # mira de referencia
        p.setPen(QPen(QColor("#33333c"), 1, Qt.DashLine))
        p.drawLine(QPointF(0, c.y()), QPointF(w, c.y()))
        p.drawLine(QPointF(c.x(), 0), QPointF(c.x(), h))
        esc = min(w, h) / 2 / 60.0            # 60° = borde
        dx = max(-w / 2 + 30, min(w / 2 - 30, -yaw * esc))     # +yaw = izquierda
        dy = max(-h / 2 + 30, min(h / 2 - 30, -pitch * esc))   # +pitch = arriba
        p.save()
        p.translate(c.x() + dx, c.y() + dy)
        p.rotate(-roll)                       # +roll = inclinar a la izquierda
        largo, alto = (min(w, h) * 0.5, min(w, h) * 0.24)
        if self.orientacion != "lado":
            largo, alto = alto, largo
        cuerpo = QRectF(-largo / 2, -alto / 2, largo, alto)
        p.setPen(QPen(MORADO.lighter(130), 3))
        p.setBrush(QColor("#1d1030"))
        p.drawRoundedRect(cuerpo, 14, 14)
        p.setPen(Qt.NoPen)
        p.setBrush(MORADO)
        if self.orientacion == "lado":
            p.drawEllipse(QPointF(-largo * 0.25, 0), alto * 0.22, alto * 0.22)
            for ox, oy in ((0.25, -0.2), (0.25, 0.2), (0.17, 0), (0.33, 0)):
                p.setBrush(GRIS_CLARO)
                p.drawEllipse(QPointF(largo * ox, alto * oy), alto * 0.07, alto * 0.07)
        else:
            p.drawEllipse(QPointF(0, -alto * 0.15), largo * 0.22, largo * 0.22)
        # flecha "enfrente / arriba"
        p.setPen(QPen(AMBAR, 3))
        p.drawLine(QPointF(0, -alto / 2 - 4), QPointF(0, -alto / 2 - 22))
        p.restore()

        if self.meta:
            eje, avance, fase = self.meta
            r = QRectF(12, h - 30, w - 24, 16)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor("#26262d"))
            p.drawRoundedRect(r, 8, 8)
            p.setBrush(VERDE if avance >= 1 else AMBAR)
            p.drawRoundedRect(QRectF(r.x(), r.y(), r.width() * max(0.0, min(1.0, avance)), r.height()), 8, 8)
            p.setPen(TEXTO)
            f = QFont("Segoe UI", 9)
            f.setBold(True)
            p.setFont(f)
            grados = abs(self.angulos[eje])
            texto = (T("¡Listo! Regresa a la posición normal", "Done! Return to the normal position")
                     if fase == "regresar" else T(f"{grados:.0f}° de 40°", f"{grados:.0f}° of 40°"))
            p.drawText(QRectF(12, h - 54, w - 24, 20), Qt.AlignCenter, texto)
        p.setPen(TENUE)
        p.setFont(QFont("Consolas", 9))
        p.drawText(QRectF(8, 4, w - 16, 18), Qt.AlignLeft,
                   T(f"arriba {pitch:+5.0f}°   izquierda {yaw:+5.0f}°   inclinación {roll:+5.0f}°",
                     f"up {pitch:+5.0f}°   left {yaw:+5.0f}°   tilt {roll:+5.0f}°"))
        p.end()


class Semaforo(QWidget):
    """Punto de color para estados."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.color = TENUE
        self.setFixedSize(16, 16)

    def poner(self, color):
        if color != self.color:
            self.color = color
            self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(self.color)
        p.drawEllipse(2, 2, 12, 12)
        p.end()
