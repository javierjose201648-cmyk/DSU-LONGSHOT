"""Simulador de la app *DSU Controller* del teléfono (Joy-Con izquierdo, Wii Classic, Wii Remote).

Joy-Con izquierdo: medido con el teléfono real. Classic y Wii Remote: bits según
los perfiles oficiales de Dolphin del desarrollador (ver app/core/controles.py).

Reproduce lo medido en referencia/captura_joycon-izq.json:
  - slot 1, modelo DS4, conexión "USB", batería 5
  - ~54 paquetes/s, pero solo ~33 muestras de movimiento nuevas por segundo
    (los demás paquetes repiten la muestra y su timestamp, resolución 1 ms)
  - bits de botones de §3.2 del brief (SL = L = L1, ícono verde = HOME...)
  - stick sin rotar, con Y = 0 arriba (teléfono vertical)
  - deja de mandar ~5 s después de la última suscripción

El "teléfono" se modela en el marco estándar del control tal como lo sostiene
el usuario (X derecha, Y arriba, Z hacia el jugador) y `ejes_app` dice cómo la
app reporta esos ejes. Por defecto: sostenido de lado, como en las mediciones
reales (estándar = (-app2, -app1, -app0)).

Uso como programa (para probar la app a mano sin teléfono):
    python -m app.tests.simulador --puerto 26760 --demo
"""
import math
import random
import socket
import struct
import threading
import time

from app.core import controles as CT
from app.core import protocolo as P

# Botón físico -> bits que manda la app
BITS_FISICOS = {
    "ZL": ["L2"], "L": ["L1"], "SL": ["L1"], "SR": ["R1"], "MENOS": ["SELECT"],
    "MAS": ["START"], "VERDE": ["HOME"], "F_ARRIBA": ["ARRIBA"], "F_ABAJO": ["ABAJO"],
    "F_IZQ": ["IZQ"], "F_DER": ["DER"], "STICK": [],   # presionar el stick no manda nada
}

# app[i] = signo * estandar[indice]   (sostenido de lado; ver docstring)
EJES_LADO = [(2, -1), (1, -1), (0, -1)]
EJES_FISICA = [(0, 1), (1, 1), (2, 1)]


def bits_fisicos(control="joycon-izq"):
    """Botón físico -> bits que manda la app en ese modo."""
    if control == "joycon-izq":
        return dict(BITS_FISICOS)
    return {b.id: [b.esperado] for b in CT.control(control).botones}


def _mul(a, b):
    return [[sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)] for i in range(3)]


def _rot(eje, ang):
    c, s = math.cos(ang), math.sin(ang)
    if eje == 0:
        return [[1, 0, 0], [0, c, -s], [0, s, c]]
    if eje == 1:
        return [[c, 0, s], [0, 1, 0], [-s, 0, c]]
    return [[c, -s, 0], [s, c, 0], [0, 0, 1]]


class SimuladorApp:
    def __init__(self, puerto=0, host="127.0.0.1", slot=1, ejes_app=None,
                 gyro_en_rad=False, accel_en_ms2=False, accel_invertido=False,
                 ruido=2.5, bias=(0.8, 0.6, 0.1), hz_paquetes=54.0, hz_movimiento=33.0,
                 stick_usuario=None, semilla=1, control="joycon-izq"):
        """stick_usuario: matriz M (lógico = M · crudo) del stick; por defecto la
        del control (Joy-Con de lado: arriba del usuario = +X crudo, derecha = +Y crudo)."""
        self.slot = slot
        self.control = control
        self.bits = bits_fisicos(control)
        ctrl = CT.control(control)
        orient = next(iter(ctrl.orientaciones))
        if stick_usuario is None:
            stick_usuario = ctrl.stick_matriz[orient]
        if ejes_app is None:
            ejes_app = EJES_LADO if orient == "lado" else EJES_FISICA
        self.ejes_app = ejes_app
        self.gyro_en_rad, self.accel_en_ms2 = gyro_en_rad, accel_en_ms2
        self.accel_invertido = accel_invertido
        self.ruido, self.bias = ruido, bias
        self.hz_paquetes, self.hz_movimiento = hz_paquetes, hz_movimiento
        self.matriz_stick = stick_usuario
        self.matriz_stick_der = stick_usuario
        self._rng = random.Random(semilla)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind((host, puerto))
        self.sock.settimeout(0.005)
        self.puerto = self.sock.getsockname()[1]
        self.server_id = 0x06B6722C
        # estado del "usuario"
        self._candado = threading.Lock()
        self.fisicos = set()
        self.stick_crudo = (128, 128)
        self.stick_der_crudo = (128, 128)
        self.R = [[1, 0, 0], [0, 1, 0], [0, 0, 1]]     # cuerpo -> mundo
        self.omega = (0.0, 0.0, 0.0)                    # °/s (pitch, yaw, roll) estándar
        self._giro_fin = 0.0
        self.movimiento_activo = True
        self.pausado = False                            # True = la app "se cerró"
        self._clientes = {}
        self._num = 5000
        self._activo = False
        self._hilo = None
        self.enviados = 0

    # ----------------------------------------------------------- "usuario"
    def presionar(self, *fisicos):
        with self._candado:
            self.fisicos.update(fisicos)

    def soltar(self, *fisicos):
        with self._candado:
            if fisicos:
                self.fisicos.difference_update(fisicos)
            else:
                self.fisicos.clear()

    def stick(self, x, y, cual="izq"):
        """Mueve un stick en coordenadas DEL USUARIO (-1..1, y + arriba)."""
        m = self.matriz_stick if cual == "izq" else self.matriz_stick_der
        # lógico = M · crudo  =>  crudo = M^T · lógico (M es ortogonal)
        cx = m[0][0] * x + m[1][0] * y
        cy = m[0][1] * x + m[1][1] * y
        crudo = (max(0, min(255, round(128 + cx * 126))), max(0, min(255, round(128 + cy * 126))))
        with self._candado:
            if cual == "izq":
                self.stick_crudo = crudo
            else:
                self.stick_der_crudo = crudo

    def girar(self, eje, grados, duracion=0.8):
        """Empieza un giro sobre un eje estándar (0 pitch, 1 yaw, 2 roll)."""
        w = [0.0, 0.0, 0.0]
        w[eje] = grados / duracion
        with self._candado:
            self.omega = tuple(w)
            self._giro_fin = time.monotonic() + duracion

    def girando(self):
        return time.monotonic() < self._giro_fin

    # ------------------------------------------------------------- servidor
    def iniciar(self):
        self._activo = True
        self._hilo = threading.Thread(target=self._correr, name="simulador-app", daemon=True)
        self._hilo.start()
        return self

    def detener(self):
        self._activo = False
        if self._hilo:
            self._hilo.join(timeout=2)
        self.sock.close()

    def __enter__(self):
        return self.iniciar()

    def __exit__(self, *a):
        self.detener()

    def _atender(self):
        try:
            while True:
                datos, addr = self.sock.recvfrom(1024)
                r = P.validar(datos, b"DSUC")
                if r is None or self.pausado:
                    continue
                tipo, datos, _ = r
                if tipo == P.MSG_VERSION:
                    self.sock.sendto(P.paquete_servidor(
                        P.MSG_VERSION, struct.pack("<H", 1001), self.server_id), addr)
                elif tipo == P.MSG_INFO:
                    n = max(0, min(4, struct.unpack_from("<i", datos, 20)[0]))
                    for s in datos[24:24 + n]:
                        self.sock.sendto(P.construir_info(
                            s, conectado=(s == self.slot), mac=b"DSU001", server_id=self.server_id), addr)
                elif tipo == P.MSG_DATOS:
                    self._clientes[addr] = time.monotonic()
        except (socket.timeout, BlockingIOError):
            pass
        except OSError:
            pass

    def _muestra_movimiento(self, dt):
        with self._candado:
            if time.monotonic() >= self._giro_fin:
                self.omega = (0.0, 0.0, 0.0)
            w = self.omega
        for eje in range(3):
            if w[eje]:
                self.R = _mul(self.R, _rot(eje, math.radians(w[eje] * dt)))
        # gravedad (reacción, +Y arriba) vista desde el cuerpo: R^T · (0,1,0)
        acc = [self.R[1][0], self.R[1][1], self.R[1][2]]
        gyro_app, accel_app = [], []
        for i, (idx, signo) in enumerate(self.ejes_app):
            g = signo * w[idx] + self.bias[i] + self._rng.gauss(0, self.ruido)
            a = signo * acc[idx] + self._rng.gauss(0, 0.01)
            if self.gyro_en_rad:
                g = math.radians(g)
            if self.accel_en_ms2:
                a *= 9.81
            if self.accel_invertido:
                a = -a
            gyro_app.append(g)
            accel_app.append(a)
        if not self.movimiento_activo:
            return (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)
        return tuple(gyro_app), tuple(accel_app)

    def _correr(self):
        periodo = 1.0 / self.hz_paquetes
        periodo_mov = 1.0 / self.hz_movimiento
        t0 = time.perf_counter()
        base_us = 1794894690000000
        sig_paquete = t0
        sig_mov = t0
        t_mov_prev = t0
        gyro, accel = self._muestra_movimiento(0.0)
        ts_us = base_us
        while self._activo:
            self._atender()
            ahora = time.perf_counter()
            if ahora >= sig_mov:
                gyro, accel = self._muestra_movimiento(ahora - t_mov_prev)
                t_mov_prev = ahora
                ts_us = base_us + int((ahora - t0) * 1000) * 1000   # resolución de 1 ms
                sig_mov += periodo_mov
                if sig_mov < ahora:
                    sig_mov = ahora + periodo_mov
            if ahora < sig_paquete:
                continue
            sig_paquete += periodo
            if sig_paquete < ahora:
                sig_paquete = ahora + periodo
            limite = time.monotonic() - 5.0
            self._clientes = {a: t for a, t in self._clientes.items() if t > limite}
            if self.pausado or not self._clientes:
                continue
            with self._candado:
                bits = [b for f in self.fisicos for b in self.bits.get(f, [])]
                lx, ly = self.stick_crudo
                rx, ry = self.stick_der_crudo
            self._num += 1
            paquete = P.construir_datos(self.slot, self._num, bits, lx=lx, ly=ly, rx=rx, ry=ry,
                                        ts_us=ts_us, accel=accel, gyro=gyro,
                                        server_id=self.server_id)
            for addr in self._clientes:
                try:
                    self.sock.sendto(paquete, addr)
                    self.enviados += 1
                except OSError:
                    pass


def _demo(sim):
    """Movimiento continuo para ver algo en la app sin tocar nada."""
    botones = [f for f in sim.bits if f not in ("STICK", "L")]
    t0 = time.monotonic()
    i = 0
    while True:
        t = time.monotonic() - t0
        sim.stick(math.cos(t * 1.5), math.sin(t * 1.5))
        sim.stick(math.cos(t * 0.9), -math.sin(t * 0.9), "der")
        if int(t) != i:
            i = int(t)
            sim.soltar()
            sim.presionar(botones[i % len(botones)])
            sim.girar(i % 3, 40 if (i // 3) % 2 == 0 else -40, 0.8)
        time.sleep(0.02)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Simulador de DSU Controller (Joy-Con izquierdo)")
    ap.add_argument("--puerto", type=int, default=26760)
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--demo", action="store_true", help="mover stick, botones y giros solos")
    ap.add_argument("--control", default="joycon-izq", choices=sorted(CT.CONTROLES))
    a = ap.parse_args()
    s = SimuladorApp(a.puerto, a.host, control=a.control).iniciar()
    print(f"Simulador escuchando en {a.host}:{s.puerto} (slot {s.slot}). Ctrl+C para salir.")
    try:
        if a.demo:
            _demo(s)
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        s.detener()
