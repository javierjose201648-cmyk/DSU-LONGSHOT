"""Estado crudo (lo que manda la app) -> estado lógico (lo que verá el juego)."""
import math

from .controles import control
from .perfiles import SALIDAS


class EstadoLogico:
    """Control ya calibrado.

    Sticks en -1..1 con X + derecha, Y + arriba. Gatillos 0..255.
    Movimiento en el marco estándar SDL/DS4 (X derecha, Y arriba, Z hacia el
    jugador): gyro en °/s como (pitch, yaw, roll) con
      +pitch = apuntar hacia ARRIBA, +yaw = apuntar a la IZQUIERDA,
      +roll = inclinar a la IZQUIERDA;  accel en g (+1 en Y en reposo y plano).
    """
    __slots__ = ("botones", "lx", "ly", "rx", "ry", "l2", "r2",
                 "gyro", "accel", "gyro_crudo", "accel_crudo", "ts_us", "toques")

    def __init__(self):
        self.botones = {}
        self.lx = self.ly = self.rx = self.ry = 0.0
        self.l2 = self.r2 = 0
        self.gyro = (0.0, 0.0, 0.0)
        self.accel = (0.0, 1.0, 0.0)
        self.gyro_crudo = (0.0, 0.0, 0.0)     # tal cual lo manda la app (para
        self.accel_crudo = (0.0, 0.0, 0.0)    # re-emitir en orientación física)
        self.ts_us = 0
        self.toques = []

    def presionados(self):
        return [b for b in SALIDAS if self.botones.get(b)]


def stick_logico(lx, ly, cfg):
    """Byte crudo -> (x, y) lógico con matriz, zona muerta radial y rango."""
    cx, cy = cfg["centro"]
    vx, vy = (lx - cx) / 127.0, (ly - cy) / 127.0
    m = cfg["matriz"]
    x = m[0][0] * vx + m[0][1] * vy
    y = m[1][0] * vx + m[1][1] * vy
    if cfg.get("intercambiar_ejes"):
        x, y = y, x
    if cfg.get("invertir_x"):
        x = -x
    if cfg.get("invertir_y"):
        y = -y
    mag = math.hypot(x, y)
    zm = cfg.get("zona_muerta", 0.0)
    rango = max(zm + 0.05, cfg.get("rango", 1.0))
    if mag <= zm or mag == 0:
        return 0.0, 0.0
    nueva = min(1.0, (mag - zm) / (rango - zm))
    k = nueva / mag
    return max(-1.0, min(1.0, x * k)), max(-1.0, min(1.0, y * k))


def movimiento_logico(gyro, accel, perfil):
    """Aplica bias, permutación, signos, unidades, sensibilidad e inversión."""
    g = perfil["gyro"]
    p, s, b, ge = g["perm"], g["signo"], g["bias"], g["escala"]
    a = perfil["accel"]
    ae = a["escala"] * a["signo"]
    sens = g.get("sensibilidad", 1.0)
    inv = g.get("invertir", (False, False, False))
    zm = g.get("zona_muerta", 0.0)
    gl, al = [], []
    for i in range(3):
        v = s[i] * (gyro[p[i]] - b[p[i]]) * ge
        if zm > 0:
            v = 0.0 if abs(v) < zm else v - math.copysign(zm, v)
        v *= sens
        gl.append(-v if inv[i] else v)
        al.append(s[i] * accel[p[i]] * ae)
    # Invertir un eje del gyro debe invertir también su efecto en el acelerómetro
    # solo si el usuario lo hace por gusto (no por calibración): el accel no se toca.
    return tuple(gl), tuple(al)


def transformar(e, perfil):
    """Estado (protocolo) -> EstadoLogico según el perfil."""
    log = EstadoLogico()
    mapeo = perfil["mapeo"]
    f = e.fuente
    log.botones = {b: bool(mapeo.get(b)) and f.get(mapeo[b], False) for b in SALIDAS}
    log.lx, log.ly = stick_logico(e.lx, e.ly, perfil["stick"])
    # Solo los controles con dos sticks (Wii Classic) mueven el derecho; si no,
    # queda en el centro (lo puede mover el gyro->stick en las salidas).
    if "der" in control(perfil.get("control")).sticks:
        log.rx, log.ry = stick_logico(e.rx, e.ry, perfil["stick_der"])
        if perfil.get("sticks_intercambiados"):      # cada stick conserva sus ajustes
            log.lx, log.ly, log.rx, log.ry = log.rx, log.ry, log.lx, log.ly
    log.l2 = _gatillo(e, mapeo.get("L2"), log.botones["L2"])
    log.r2 = _gatillo(e, mapeo.get("R2"), log.botones["R2"])
    log.gyro, log.accel = movimiento_logico(e.gyro, e.accel, perfil)
    log.gyro_crudo, log.accel_crudo = tuple(e.gyro), tuple(e.accel)
    log.ts_us = e.ts_us
    log.toques = e.toques
    return log


def _gatillo(e, fuente, presionado):
    analog = {"L2": e.l2_analog, "R2": e.r2_analog}.get(fuente, 0)
    if analog > 0:
        return analog
    return 255 if presionado else 0


class GyroStick:
    """Convierte la rotación del control en movimiento del stick derecho."""

    def __init__(self, cfg):
        self.cfg = cfg

    def __call__(self, gyro):
        zm = max(0.5, self.cfg.get("zona_muerta", 6.0))
        tope = max(10.0, self.cfg.get("max_dps", 150.0))

        def eje(dps):
            if abs(dps) < zm:
                return 0.0
            dps -= math.copysign(zm, dps)
            return max(-1.0, min(1.0, dps / tope))
        # +yaw = girar a la izquierda -> stick a la izquierda (X negativa)
        x, y = -eje(gyro[1]), eje(gyro[0])
        if self.cfg.get("invertir_x"):
            x = -x
        if self.cfg.get("invertir_y"):
            y = -y
        return x, y
