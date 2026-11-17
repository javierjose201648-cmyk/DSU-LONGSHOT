#!/usr/bin/env python3
"""
dsu_bridge.py — Convierte un control DSU (protocolo cemuhook) del teléfono en un
control virtual de Windows (Xbox 360 o DualShock 4) para usarlo en cualquier
juego o emulador.

Requisitos (Windows):
    pip install vgamepad          (instala también el driver ViGEmBus)

Uso:
    python dsu_bridge.py --ip 192.168.1.50 --calibrar      (primera vez)
    python dsu_bridge.py --ip 192.168.1.50                 (usa calibracion.json)
    python dsu_bridge.py --ip 192.168.1.50 --modo xbox --gyro-stick

Modos:
    ds4   (default) DualShock 4 virtual con giroscopio/acelerómetro reales.
          Lo leen los emuladores basados en SDL y Steam Input.
    xbox  Xbox 360 virtual. Máxima compatibilidad, pero XInput no tiene gyro;
          usa --gyro-stick para apuntar con el movimiento.
"""

import argparse
import json
import math
import os
import socket
import struct
import sys
import threading
import time
import zlib

# --------------------------------------------------------------------------
# Protocolo DSU (https://v1993.github.io/cemuhook-protocol/)
# --------------------------------------------------------------------------
PUERTO_DEFAULT = 26760
VERSION_PROTOCOLO = 1001
MSG_INFO = 0x100001
MSG_DATOS = 0x100002
CLIENT_ID = 0x4A534231  # arbitrario

# Nombres lógicos de los botones. Las letras son por POSICIÓN estilo Xbox:
# A = abajo, B = derecha, X = izquierda, Y = arriba.
BOTONES = ["A", "B", "X", "Y", "L1", "R1", "L2", "R2", "SELECT", "START",
           "L3", "R3", "ARRIBA", "ABAJO", "IZQ", "DER", "HOME", "TOUCH"]

DESCRIPCION_BOTON = {
    "A": "A (botón de ABAJO del rombo)",
    "B": "B (botón de la DERECHA del rombo)",
    "X": "X (botón de la IZQUIERDA del rombo)",
    "Y": "Y (botón de ARRIBA del rombo)",
    "L1": "L / LB (gatillo superior izquierdo)",
    "R1": "R / RB (gatillo superior derecho)",
    "L2": "ZL / LT (gatillo inferior izquierdo)",
    "R2": "ZR / RT (gatillo inferior derecho)",
    "SELECT": "SELECT / MENOS / SHARE",
    "START": "START / MÁS / OPTIONS",
    "L3": "L3 (presionar stick izquierdo)",
    "R3": "R3 (presionar stick derecho)",
    "ARRIBA": "Cruceta ARRIBA",
    "ABAJO": "Cruceta ABAJO",
    "IZQ": "Cruceta IZQUIERDA",
    "DER": "Cruceta DERECHA",
    "HOME": "HOME / PS",
    "TOUCH": "TOUCH / CAPTURA (si tu app lo tiene)",
}


def _paquete(tipo, payload=b""):
    cuerpo = struct.pack("<I", tipo) + payload
    cab = struct.pack("<4sHHII", b"DSUC", VERSION_PROTOCOLO, len(cuerpo), 0, CLIENT_ID)
    crc = zlib.crc32(cab + cuerpo) & 0xFFFFFFFF
    cab = struct.pack("<4sHHII", b"DSUC", VERSION_PROTOCOLO, len(cuerpo), crc, CLIENT_ID)
    return cab + cuerpo


class Estado:
    """Un paquete de datos del control, ya decodificado (valores crudos)."""
    __slots__ = ("slot", "modelo", "conexion", "bateria", "num_paquete", "fuente",
                 "lx", "ly", "rx", "ry", "l2_analog", "r2_analog",
                 "toques", "ts_us", "accel", "gyro", "t_llegada")


def parsear_paquete(datos):
    """Devuelve Estado para paquetes de datos válidos; None para todo lo demás."""
    if len(datos) < 20 or datos[:4] != b"DSUS":
        return None
    _, _, largo, crc, _ = struct.unpack_from("<4sHHII", datos)
    if len(datos) < 16 + largo:
        return None
    datos = datos[:16 + largo]
    if zlib.crc32(datos[:8] + b"\0\0\0\0" + datos[12:]) & 0xFFFFFFFF != crc:
        return None
    tipo = struct.unpack_from("<I", datos, 16)[0]
    if tipo != MSG_DATOS or len(datos) < 100:
        return None

    e = Estado()
    e.slot, _estado_slot, e.modelo, e.conexion = datos[20], datos[21], datos[22], datos[23]
    e.bateria = datos[30]
    if datos[31] == 0:  # el servidor dice "no conectado"
        return None
    e.num_paquete = struct.unpack_from("<I", datos, 32)[0]
    b1, b2, home, touch = datos[36], datos[37], datos[38], datos[39]
    e.fuente = {
        "IZQ": bool(b1 & 0x80), "ABAJO": bool(b1 & 0x40), "DER": bool(b1 & 0x20),
        "ARRIBA": bool(b1 & 0x10), "START": bool(b1 & 0x08), "R3": bool(b1 & 0x04),
        "L3": bool(b1 & 0x02), "SELECT": bool(b1 & 0x01),
        "Y": bool(b2 & 0x80), "B": bool(b2 & 0x40), "A": bool(b2 & 0x20),
        "X": bool(b2 & 0x10), "R1": bool(b2 & 0x08), "L1": bool(b2 & 0x04),
        "R2": bool(b2 & 0x02), "L2": bool(b2 & 0x01),
        "HOME": bool(home), "TOUCH": bool(touch),
    }
    e.lx, e.ly, e.rx, e.ry = datos[40], datos[41], datos[42], datos[43]
    e.r2_analog, e.l2_analog = datos[54], datos[55]
    # Algunas apps no llenan el analógico de los gatillos: lo tomamos como presionado
    if e.r2_analog > 100:
        e.fuente["R2"] = True
    if e.l2_analog > 100:
        e.fuente["L2"] = True
    e.toques = []
    for off in (56, 62):
        activo, tid, x, y = struct.unpack_from("<BBHH", datos, off)
        if activo:
            e.toques.append((tid, x, y))
    e.ts_us = struct.unpack_from("<Q", datos, 68)[0]
    e.accel = struct.unpack_from("<3f", datos, 76)
    e.gyro = struct.unpack_from("<3f", datos, 88)  # pitch, yaw, roll (según la app)
    e.t_llegada = time.monotonic()
    return e


class ClienteDSU:
    def __init__(self, ip, puerto=PUERTO_DEFAULT, slot=None):
        self.destino = (ip, puerto)
        self.slot = slot  # None = el primero que mande datos
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("0.0.0.0", 0))
        self.sock.settimeout(0.05)
        self._ultima_solicitud = 0.0
        self._ultimo_num = None
        self.paquetes_malos = 0

    def _solicitar(self):
        ahora = time.monotonic()
        if ahora - self._ultima_solicitud < 1.0:
            return
        self._ultima_solicitud = ahora
        try:
            # flags=0: suscribirse a todos los slots (lo soportan todos los servidores)
            self.sock.sendto(_paquete(MSG_DATOS, struct.pack("<BB6s", 0, 0, b"\0" * 6)), self.destino)
            slots = list(range(4))
            self.sock.sendto(_paquete(MSG_INFO, struct.pack("<i", 4) + bytes(slots)), self.destino)
        except OSError:
            pass  # red caída momentáneamente; se reintenta en el siguiente ciclo

    def recibir(self, timeout=0.5):
        """Devuelve el siguiente Estado del slot elegido, o None si no llegó nada."""
        limite = time.monotonic() + timeout
        while time.monotonic() < limite:
            self._solicitar()
            try:
                datos, _ = self.sock.recvfrom(2048)
            except socket.timeout:
                continue
            except OSError:
                time.sleep(0.05)
                continue
            e = parsear_paquete(datos)
            if e is None:
                if datos[:4] == b"DSUS" and len(datos) >= 100:
                    self.paquetes_malos += 1
                continue
            if self.slot is None:
                self.slot = e.slot
            if e.slot != self.slot:
                continue
            # Descartar paquetes UDP que llegan fuera de orden
            if self._ultimo_num is not None:
                delta = (e.num_paquete - self._ultimo_num) & 0xFFFFFFFF
                if delta == 0 or delta > 0x7FFFFFFF:
                    continue
            self._ultimo_num = e.num_paquete
            return e
        return None

    def vaciar(self):
        """Tira lo acumulado en el buffer (p. ej. después de esperar un Enter)."""
        self._ultima_solicitud = 0.0
        self._solicitar()
        fin = time.monotonic() + 0.3
        while time.monotonic() < fin:
            if self.recibir(0.05) is None:
                break


# --------------------------------------------------------------------------
# Calibración: datos y transformación
# --------------------------------------------------------------------------
CALIBRACION_DEFAULT = {
    "slot": None,
    "remapeo": {b: b for b in BOTONES},   # botón lógico -> bit que manda la app
    "invertir": {"lx": False, "ly": False, "rx": False, "ry": False},
    "centro": {"lx": 128, "ly": 128, "rx": 128, "ry": 128},
    "gyro_perm": [0, 1, 2],     # eje de la app que alimenta X(pitch), Y(yaw), Z(roll)
    "gyro_signo": [1, 1, 1],
    "gyro_escala": 1.0,         # 57.2958 si la app manda rad/s
    "gyro_bias": [0.0, 0.0, 0.0],
    "gyro_ruido": 0.5,          # °/s, para la zona muerta del gyro->stick
    "accel_escala": 1.0,        # 1/9.81 si la app manda m/s²
    "accel_signo": 1,
}


class Movimiento:
    """Gyro (°/s) y accel (g) en el sistema de ejes estándar (SDL / DualShock 4):
    X a la derecha, Y hacia arriba, Z hacia el jugador.
      +pitch (X) = apuntar hacia ARRIBA
      +yaw   (Y) = apuntar hacia la IZQUIERDA
      +roll  (Z) = inclinar hacia la IZQUIERDA (como volante)
    En reposo y plano, el acelerómetro marca +1 g en Y."""
    __slots__ = ("gyro", "accel")


def aplicar_movimiento(e, cal):
    p, s = cal["gyro_perm"], cal["gyro_signo"]
    b, ge = cal["gyro_bias"], cal["gyro_escala"]
    ae = cal["accel_escala"] * cal["accel_signo"]
    m = Movimiento()
    m.gyro = tuple(s[i] * (e.gyro[p[i]] - b[p[i]]) * ge for i in range(3))
    m.accel = tuple(s[i] * e.accel[p[i]] * ae for i in range(3))
    return m


def botones_logicos(e, cal):
    r = cal["remapeo"]
    return {b: e.fuente.get(r.get(b, b), False) for b in BOTONES}


def stick(e, cal, nombre):
    """Devuelve el eje normalizado -1..1 (X: + derecha, Y: + arriba)."""
    crudo = getattr(e, nombre)
    v = (crudo - cal["centro"][nombre]) / 127.0
    if cal["invertir"][nombre]:
        v = -v
    return max(-1.0, min(1.0, v))


def gatillo(e, cal, nombre):
    """0..255. Usa el analógico si la app lo manda; si no, digital."""
    fuente = cal["remapeo"].get(nombre, nombre)
    analog = {"L2": e.l2_analog, "R2": e.r2_analog}.get(fuente, 0)
    if analog > 0:
        return analog
    return 255 if e.fuente.get(fuente, False) else 0


# --------------------------------------------------------------------------
# Salidas: control virtual
# --------------------------------------------------------------------------
def _a_byte(v):
    """-1..1 -> 0..255 (128 = centro)."""
    return max(0, min(255, int(round(128 + v * 127.5))))


def _a_short(v):
    return max(-32768, min(32767, int(round(v * 32767))))


class GyroStick:
    """Convierte la rotación del teléfono en movimiento del stick derecho."""

    def __init__(self, max_dps, ruido):
        self.max_dps = max_dps
        self.zona_muerta = max(1.0, ruido * 3)

    def __call__(self, m):
        def eje(dps):
            if abs(dps) < self.zona_muerta:
                return 0.0
            dps -= math.copysign(self.zona_muerta, dps)
            return max(-1.0, min(1.0, dps / self.max_dps))
        # +yaw = girar a la izquierda -> stick a la izquierda (X negativa)
        return -eje(m.gyro[1]), eje(m.gyro[0])


class SalidaXbox:
    def __init__(self, vg, gyro_stick=None):
        self.vg = vg
        self.pad = vg.VX360Gamepad()
        self.gyro_stick = gyro_stick

    def actualizar(self, e, cal):
        vg = self.vg
        B = vg.XUSB_BUTTON
        tabla = {
            "A": B.XUSB_GAMEPAD_A, "B": B.XUSB_GAMEPAD_B, "X": B.XUSB_GAMEPAD_X,
            "Y": B.XUSB_GAMEPAD_Y, "L1": B.XUSB_GAMEPAD_LEFT_SHOULDER,
            "R1": B.XUSB_GAMEPAD_RIGHT_SHOULDER, "SELECT": B.XUSB_GAMEPAD_BACK,
            "START": B.XUSB_GAMEPAD_START, "L3": B.XUSB_GAMEPAD_LEFT_THUMB,
            "R3": B.XUSB_GAMEPAD_RIGHT_THUMB, "ARRIBA": B.XUSB_GAMEPAD_DPAD_UP,
            "ABAJO": B.XUSB_GAMEPAD_DPAD_DOWN, "IZQ": B.XUSB_GAMEPAD_DPAD_LEFT,
            "DER": B.XUSB_GAMEPAD_DPAD_RIGHT, "HOME": B.XUSB_GAMEPAD_GUIDE,
        }
        bl = botones_logicos(e, cal)
        mask = 0
        for nombre, bit in tabla.items():
            if bl[nombre]:
                mask |= int(bit)
        rx, ry = stick(e, cal, "rx"), stick(e, cal, "ry")
        if self.gyro_stick:
            gx, gy = self.gyro_stick(aplicar_movimiento(e, cal))
            rx, ry = max(-1, min(1, rx + gx)), max(-1, min(1, ry + gy))
        r = self.pad.report
        r.wButtons = mask
        r.bLeftTrigger = gatillo(e, cal, "L2")
        r.bRightTrigger = gatillo(e, cal, "R2")
        r.sThumbLX = _a_short(stick(e, cal, "lx"))
        r.sThumbLY = _a_short(stick(e, cal, "ly"))   # XInput: + arriba
        r.sThumbRX = _a_short(rx)
        r.sThumbRY = _a_short(ry)
        self.pad.update()

    def neutral(self):
        self.pad.reset()
        self.pad.update()


# Calibración interna del DualShock 4 virtual de ViGEmBus (la que lee el
# driver/SDL): valor_calibrado = (crudo - bias) * num / den
# Gyro calibrado: 1024 unidades por °/s.  Accel calibrado: 8192 unidades por g.
_DS4_GYRO_CAL = ((0, 1105920, 17676), (0, 1105920, 17771), (0, 1105920, 17786))
_DS4_ACCEL_CAL = ((-297, 16384, 16209), (-42, 16384, 16148), (-512, 16384, 15988))


def _crudo_ds4(valor, unidades_por, cal):
    bias, num, den = cal
    v = int(round(valor * unidades_por * den / num + bias))
    return max(-32768, min(32767, v))


class SalidaDS4:
    def __init__(self, vg, gyro_stick=None):
        self.vg = vg
        self.pad = vg.VDS4Gamepad()
        self.gyro_stick = gyro_stick
        self._contador_touch = 0

    def construir_reporte(self, e, cal):
        vg = self.vg
        D = vg.DS4_BUTTONS
        rep = self.pad.get_default_extended_report()
        r = rep.Report
        bl = botones_logicos(e, cal)
        tabla = {
            "A": D.DS4_BUTTON_CROSS, "B": D.DS4_BUTTON_CIRCLE,
            "X": D.DS4_BUTTON_SQUARE, "Y": D.DS4_BUTTON_TRIANGLE,
            "L1": D.DS4_BUTTON_SHOULDER_LEFT, "R1": D.DS4_BUTTON_SHOULDER_RIGHT,
            "SELECT": D.DS4_BUTTON_SHARE, "START": D.DS4_BUTTON_OPTIONS,
            "L3": D.DS4_BUTTON_THUMB_LEFT, "R3": D.DS4_BUTTON_THUMB_RIGHT,
        }
        mask = 0
        for nombre, bit in tabla.items():
            if bl[nombre]:
                mask |= int(bit)
        l2, r2 = gatillo(e, cal, "L2"), gatillo(e, cal, "R2")
        if l2 > 30:
            mask |= int(D.DS4_BUTTON_TRIGGER_LEFT)
        if r2 > 30:
            mask |= int(D.DS4_BUTTON_TRIGGER_RIGHT)
        mask |= _hat(bl["ARRIBA"], bl["ABAJO"], bl["IZQ"], bl["DER"])
        r.wButtons = mask
        especial = 0
        if bl["HOME"]:
            especial |= int(vg.DS4_SPECIAL_BUTTONS.DS4_SPECIAL_BUTTON_PS)
        if bl["TOUCH"]:
            especial |= int(vg.DS4_SPECIAL_BUTTONS.DS4_SPECIAL_BUTTON_TOUCHPAD)
        r.bSpecial = especial
        r.bTriggerL, r.bTriggerR = l2, r2

        rx, ry = stick(e, cal, "rx"), stick(e, cal, "ry")
        m = aplicar_movimiento(e, cal)
        if self.gyro_stick:
            gx, gy = self.gyro_stick(m)
            rx, ry = max(-1, min(1, rx + gx)), max(-1, min(1, ry + gy))
        # DS4: Y = 0 arriba, así que se invierte
        r.bThumbLX = _a_byte(stick(e, cal, "lx"))
        r.bThumbLY = _a_byte(-stick(e, cal, "ly"))
        r.bThumbRX = _a_byte(rx)
        r.bThumbRY = _a_byte(-ry)

        # Movimiento
        r.wTimestamp = int(e.ts_us * 3 // 16) & 0xFFFF if e.ts_us else int(e.t_llegada * 187500) & 0xFFFF
        r.wGyroX, r.wGyroY, r.wGyroZ = (
            _crudo_ds4(m.gyro[i], 1024, _DS4_GYRO_CAL[i]) for i in range(3))
        r.wAccelX, r.wAccelY, r.wAccelZ = (
            _crudo_ds4(m.accel[i], 8192, _DS4_ACCEL_CAL[i]) for i in range(3))

        # Touchpad (si la app manda toques)
        if e.toques:
            self._contador_touch = (self._contador_touch + 1) & 0xFF
            r.bTouchPacketsN = 1
            t = r.sCurrentTouch
            t.bPacketCounter = self._contador_touch
            for i, (tid, x, y) in enumerate(e.toques[:2]):
                x, y = min(x, 1919), min(y, 941)
                datos = (x & 0xFF, ((x >> 8) & 0x0F) | ((y & 0x0F) << 4), (y >> 4) & 0xFF)
                if i == 0:
                    t.bIsUpTrackingNum1 = tid & 0x7F
                    for k in range(3):
                        t.bTouchData1[k] = datos[k]
                else:
                    t.bIsUpTrackingNum2 = tid & 0x7F
                    for k in range(3):
                        t.bTouchData2[k] = datos[k]
        return rep

    def actualizar(self, e, cal):
        self.pad.update_from_extended_report(self.construir_reporte(e, cal))

    def neutral(self):
        self.pad.update_from_extended_report(self.pad.get_default_extended_report())


def _hat(arriba, abajo, izq, der):
    dy = (1 if arriba else 0) - (1 if abajo else 0)
    dx = (1 if der else 0) - (1 if izq else 0)
    return {(0, 1): 0, (1, 1): 1, (1, 0): 2, (1, -1): 3, (0, -1): 4,
            (-1, -1): 5, (-1, 0): 6, (-1, 1): 7}.get((dx, dy), 8)


# --------------------------------------------------------------------------
# Calibración guiada
# --------------------------------------------------------------------------
class EsperaEnter:
    """Detecta un Enter sin bloquear el loop de lectura."""

    def __init__(self):
        self.listo = threading.Event()
        threading.Thread(target=self._esperar, daemon=True).start()

    def _esperar(self):
        try:
            input()
        except EOFError:
            pass
        self.listo.set()


def _pausa(cliente, texto):
    input(f"\n{texto}\n  [Enter para continuar] ")
    cliente.vaciar()


def _linea(texto):
    sys.stdout.write("\r" + texto.ljust(78)[:78])
    sys.stdout.flush()


def _nombre_modelo(e):
    modelos = {0: "no aplica", 1: "DS3", 2: "DS4", 3: "genérico"}
    conex = {0: "no aplica", 1: "USB", 2: "Bluetooth"}
    return f"modelo={modelos.get(e.modelo, e.modelo)}, conexión={conex.get(e.conexion, e.conexion)}"


def paso_conexion(cliente):
    print("\n=== 1/6  CONEXIÓN ===")
    print(f"Buscando datos en {cliente.destino[0]}:{cliente.destino[1]} ...")
    fin = time.monotonic() + 15
    e = None
    while time.monotonic() < fin and e is None:
        e = cliente.recibir(0.5)
    if e is None:
        print("\n✗ No llegó ningún dato en 15 s. Revisa:\n"
              "  - Que la app esté abierta y en modo DSU/servidor\n"
              "  - Que la IP y el puerto coincidan con los que muestra la app\n"
              "  - Que la PC y el teléfono estén en la misma red Wi-Fi\n"
              "  - Que el firewall de Windows permita Python (red privada)")
        sys.exit(1)
    print(f"✓ Conectado. Slot {e.slot}, {_nombre_modelo(e)}")
    # Medir frecuencia
    n, t0 = 0, time.monotonic()
    while time.monotonic() - t0 < 2:
        if cliente.recibir(0.2):
            n += 1
    hz = n / 2
    print(f"  Frecuencia: {hz:.0f} paquetes/s", end="")
    if hz < 30:
        print("  ⚠ baja: el gyro se va a sentir brincado. Acerca el teléfono al router "
              "o usa Wi-Fi de 5 GHz.")
    else:
        print("  ✓")
    if cliente.paquetes_malos:
        print(f"  ⚠ {cliente.paquetes_malos} paquetes con CRC inválido descartados.")
    return e.slot


def _esperar_suelto(cliente, cal_temp):
    """Espera (máx. 5 s) a que no haya botones presionados."""
    fin = time.monotonic() + 5
    while time.monotonic() < fin:
        e = cliente.recibir(0.5)
        if e and not any(e.fuente.values()):
            return


def paso_botones(cliente):
    print("\n=== 2/6  BOTONES ===")
    print("Presiona cada botón que se te pida (toca y suelta). Si tu app no lo tiene,\n"
          "espera 6 s y se salta. Así detectamos si la app manda algún botón cambiado.")
    _pausa(cliente, "Listo para empezar.")
    remapeo, usados = {}, set()
    for b in BOTONES:
        _esperar_suelto(cliente, None)
        print(f"  Presiona: {DESCRIPCION_BOTON[b]:<45}", end="", flush=True)
        fin = time.monotonic() + 6
        detectado = None
        while time.monotonic() < fin and detectado is None:
            e = cliente.recibir(0.2)
            if not e:
                continue
            for fuente, activo in e.fuente.items():
                if activo:
                    detectado = fuente
                    break
        if detectado is None:
            print("→ omitido")
            remapeo[b] = b
        else:
            if detectado in usados:
                print(f"→ ⚠ llegó '{detectado}', que ya usaste antes. Se deja el default.")
                remapeo[b] = b
            else:
                usados.add(detectado)
                remapeo[b] = detectado
                print("→ ✓" if detectado == b else f"→ ✓ (la app lo manda como '{detectado}', se reasigna)")
    return remapeo


def _medir_eje(cliente, nombre, centro, texto):
    print(f"  {texto:<52}", end="", flush=True)
    fin = time.monotonic() + 10
    while time.monotonic() < fin:
        e = cliente.recibir(0.2)
        if not e:
            continue
        d = getattr(e, nombre) - centro
        if abs(d) > 70:
            print("→ ✓" if d > 0 else "→ ✓ (viene invertido, se corrige)")
            return d < 0
    print("→ no detectado, se deja normal")
    return False


def paso_sticks(cliente):
    print("\n=== 3/6  STICKS ===")
    _pausa(cliente, "Suelta los dos sticks (que estén en el centro).")
    muestras = []
    fin = time.monotonic() + 1.0
    while time.monotonic() < fin:
        e = cliente.recibir(0.2)
        if e:
            muestras.append((e.lx, e.ly, e.rx, e.ry))
    if not muestras:
        print("  ⚠ Sin datos; se usan valores por defecto.")
        return dict(CALIBRACION_DEFAULT["centro"]), dict(CALIBRACION_DEFAULT["invertir"])
    centro = {k: round(sum(m[i] for m in muestras) / len(muestras))
              for i, k in enumerate(("lx", "ly", "rx", "ry"))}
    for k, v in centro.items():
        if abs(v - 128) > 15:
            print(f"  ⚠ El stick {k} en reposo marca {v} (debería ser ~128). Se compensa.")
    invertir = {
        "lx": _medir_eje(cliente, "lx", centro["lx"], "Empuja el stick IZQUIERDO a la DERECHA"),
        "ly": _medir_eje(cliente, "ly", centro["ly"], "Empuja el stick IZQUIERDO hacia ARRIBA"),
        "rx": _medir_eje(cliente, "rx", centro["rx"], "Empuja el stick DERECHO a la DERECHA"),
        "ry": _medir_eje(cliente, "ry", centro["ry"], "Empuja el stick DERECHO hacia ARRIBA"),
    }
    return centro, invertir


def analizar_reposo(muestras):
    """muestras: lista de (gyro3, accel3). Devuelve bias, ruido, gravedad media."""
    n = len(muestras)
    bias = [sum(m[0][i] for m in muestras) / n for i in range(3)]
    var = [sum((m[0][i] - bias[i]) ** 2 for m in muestras) / n for i in range(3)]
    ruido = max(math.sqrt(v) for v in var)
    grav = [sum(m[1][i] for m in muestras) / n for i in range(3)]
    return bias, ruido, grav


def _dt(prev, e):
    if prev is None:
        return 0.0
    if e.ts_us and prev.ts_us and e.ts_us > prev.ts_us:
        dt = (e.ts_us - prev.ts_us) / 1e6
        if dt < 0.2:
            return dt
    return max(0.0, min(0.2, e.t_llegada - prev.t_llegada))


def integrar_gesto(muestras, bias):
    """muestras: lista de Estado. Devuelve el ángulo girado en cada eje de la app."""
    angulo = [0.0, 0.0, 0.0]
    prev = None
    for e in muestras:
        dt = _dt(prev, e)
        for i in range(3):
            angulo[i] += (e.gyro[i] - bias[i]) * dt
        prev = e
    return angulo


def deducir_ejes(angulos):
    """angulos: dict {'pitch': [a0,a1,a2], 'yaw': [...], 'roll': [...]} medidos con
    gestos en la dirección POSITIVA de cada eje estándar. Devuelve perm, signo,
    escala o lanza ValueError con la explicación."""
    perm, signo, magnitudes = [], [], []
    for eje in ("pitch", "yaw", "roll"):
        a = angulos[eje]
        idx = max(range(3), key=lambda i: abs(a[i]))
        total = math.sqrt(sum(x * x for x in a))
        if total == 0 or abs(a[idx]) / total < 0.75:
            raise ValueError(f"el gesto de {eje} movió varios ejes a la vez; hazlo más 'puro'")
        perm.append(idx)
        signo.append(1 if a[idx] > 0 else -1)
        magnitudes.append(abs(a[idx]))
    if len(set(perm)) != 3:
        raise ValueError("dos gestos movieron el mismo eje; repite con giros más claros")
    med = sorted(magnitudes)[1]
    if med < 5:          # ~0.8 para 45° => la app manda rad/s
        escala = 180 / math.pi
    else:
        escala = 1.0
    grados = [m * escala for m in magnitudes]
    if min(grados) < 15:
        raise ValueError("algún giro fue muy pequeño; gira unos 45°")
    return perm, signo, escala, grados


def _gesto(cliente, bias, texto):
    print(f"\n  {texto}")
    for n in (3, 2, 1):
        _linea(f"    Prepárate... {n}")
        fin = time.monotonic() + 1
        while time.monotonic() < fin:
            cliente.recibir(0.1)
    _linea("    ¡YA! Gira ~45° y quédate quieto")
    muestras = []
    fin = time.monotonic() + 2.5
    while time.monotonic() < fin:
        e = cliente.recibir(0.1)
        if e:
            muestras.append(e)
    _linea("    ✓ Regresa a la posición normal")
    print()
    time.sleep(1.0)
    cliente.vaciar()
    return integrar_gesto(muestras, bias)


def paso_movimiento(cliente):
    print("\n=== 4/6  REPOSO (ruido del giroscopio) ===")
    _pausa(cliente, "Sostén el teléfono EXACTAMENTE como vas a jugar (como un Joy-Con en\n"
                    "horizontal) y mantenlo quieto. Al dar Enter mide 3 segundos.")
    muestras = []
    fin = time.monotonic() + 3
    while time.monotonic() < fin:
        e = cliente.recibir(0.2)
        if e:
            muestras.append((e.gyro, e.accel))
        _linea(f"  Midiendo... {max(0, fin - time.monotonic()):.1f} s")
    print()
    if len(muestras) < 20:
        print("  ✗ Muy pocos datos de movimiento. ¿La app tiene el gyro activado?")
        sys.exit(1)
    bias, ruido, grav = analizar_reposo(muestras)
    if all(abs(g) < 1e-6 for e_ in muestras for g in e_[0]) and all(abs(a) < 1e-6 for e_ in muestras for a in e_[1]):
        print("  ✗ El gyro y el acelerómetro mandan puros ceros. Activa el movimiento en la app.")
        sys.exit(1)
    mag = math.sqrt(sum(g * g for g in grav))
    if 7 < mag < 12.5:
        accel_escala = 1 / 9.81
        print(f"  Acelerómetro en m/s² (|g| = {mag:.2f}); se convierte a g.")
    else:
        accel_escala = 1.0
        if not 0.8 < mag < 1.2:
            print(f"  ⚠ La gravedad medida es {mag:.2f} (esperaba ~1 g). Puede que el acelerómetro "
                  "venga mal escalado.")
    print(f"  Bias gyro: [{bias[0]:+.3f}, {bias[1]:+.3f}, {bias[2]:+.3f}]  ruido: {ruido:.3f}")

    print("\n=== 5/6  ORIENTACIÓN DE LOS EJES ===")
    print("Vas a hacer 3 giros. Para cada uno: espera el ¡YA!, gira UNOS 45° en esa\n"
          "dirección, quédate quieto, y regresa a la posición normal.")
    gestos = {
        "pitch": "Gesto 1: APUNTA HACIA ARRIBA (la parte de enfrente sube, como mirar al techo)",
        "yaw": "Gesto 2: APUNTA HACIA LA IZQUIERDA (gira sobre la mesa, sin inclinar)",
        "roll": "Gesto 3: INCLINA HACIA LA IZQUIERDA (como volante: baja el lado izquierdo)",
    }
    for intento in range(3):
        _pausa(cliente, "Vuelve a la posición normal.")
        angulos = {eje: _gesto(cliente, bias, txt) for eje, txt in gestos.items()}
        try:
            perm, signo, escala, grados = deducir_ejes(angulos)
            break
        except ValueError as err:
            print(f"  ✗ No quedó claro: {err}. Intento {intento + 2} de 3.")
    else:
        print("  ✗ No se pudo deducir la orientación. Revisa que la app mande el gyro.")
        sys.exit(1)
    unidades = "rad/s (se convierte a °/s)" if escala != 1 else "°/s"
    print(f"  ✓ Ejes deducidos. Unidades del gyro: {unidades}. "
          f"Giros medidos: {grados[0]:.0f}°, {grados[1]:.0f}°, {grados[2]:.0f}°")

    # Signo del acelerómetro: en la convención estándar, la gravedad en reposo
    # sale positiva en Y cuando el control está más o menos plano.
    g_map = [signo[i] * grav[perm[i]] * accel_escala for i in range(3)]
    dominante = max(range(3), key=lambda i: abs(g_map[i]))
    accel_signo = 1
    if dominante == 1:
        if g_map[1] < 0:
            accel_signo = -1
            print("  La app manda la gravedad con el signo contrario; se corrige.")
    else:
        print("  ⚠ No sostuviste el teléfono plano en el reposo, así que no puedo verificar\n"
              "    el signo del acelerómetro. Si el horizonte del juego sale de cabeza,\n"
              "    repite la calibración sosteniéndolo como un control normal.")
    return {
        "gyro_perm": perm, "gyro_signo": signo, "gyro_escala": escala,
        "gyro_bias": bias, "gyro_ruido": ruido * escala,
        "accel_escala": accel_escala, "accel_signo": accel_signo,
    }


def paso_verificacion(cliente, cal):
    print("\n=== 6/6  VERIFICACIÓN ===")
    print("Mueve el teléfono. Debe pasar:\n"
          "  apuntar ARRIBA -> pitch sube | apuntar IZQUIERDA -> yaw sube |\n"
          "  inclinar IZQUIERDA -> roll sube. Presiona botones para verlos.")
    _pausa(cliente, "Los ángulos empiezan en 0. Enter para terminar la prueba.")
    ang = [0.0, 0.0, 0.0]
    prev = None
    espera = EsperaEnter()
    while not espera.listo.is_set():
        e = cliente.recibir(0.2)
        if not e:
            continue
        m = aplicar_movimiento(e, cal)
        dt = _dt(prev, e)
        prev = e
        for i in range(3):
            ang[i] += m.gyro[i] * dt
        bl = [b for b, v in botones_logicos(e, cal).items() if v]
        _linea(f"  pitch {ang[0]:+5.0f}°  yaw {ang[1]:+5.0f}°  roll {ang[2]:+5.0f}°  "
               f"| {' '.join(bl) or '-'}")
    print()
    r = input("¿Se movió todo en la dirección correcta? (s/n): ").strip().lower()
    return r.startswith("s")


def calibrar(cliente):
    print("CALIBRACIÓN DEL CONTROL DSU\n"
          "Ten la app abierta y el teléfono en la mano. Tarda ~2 minutos.")
    while True:
        cal = json.loads(json.dumps(CALIBRACION_DEFAULT))
        cal["slot"] = paso_conexion(cliente)
        cal["remapeo"] = paso_botones(cliente)
        cal["centro"], cal["invertir"] = paso_sticks(cliente)
        cal.update(paso_movimiento(cliente))
        if paso_verificacion(cliente, cal):
            return cal
        print("\nRepitiendo la calibración desde el principio...\n")


# --------------------------------------------------------------------------
# Programa principal
# --------------------------------------------------------------------------
def cargar_vgamepad():
    try:
        import vgamepad as vg
        return vg
    except Exception as err:
        print("✗ No se pudo cargar vgamepad:", err)
        print("  Instálalo con:  pip install vgamepad")
        print("  (en Windows instala también el driver ViGEmBus; acepta el instalador)")
        sys.exit(1)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Puente DSU (teléfono) -> control virtual")
    ap.add_argument("--ip", required=True, help="IP que muestra la app del teléfono")
    ap.add_argument("--puerto", type=int, default=PUERTO_DEFAULT)
    ap.add_argument("--modo", choices=["ds4", "xbox"], default="ds4")
    ap.add_argument("--gyro-stick", action="store_true",
                    help="el giroscopio mueve el stick derecho (apuntar como Joy-Con)")
    ap.add_argument("--gyro-max", type=float, default=150.0,
                    help="°/s para llevar el stick al tope (menor = más sensible)")
    ap.add_argument("--calibrar", action="store_true", help="repetir la calibración")
    ap.add_argument("--archivo", default=os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                      "calibracion.json"))
    ap.add_argument("--monitor", action="store_true", help="mostrar lo que llega en vivo")
    ap.add_argument("--sin-control", action="store_true", help=argparse.SUPPRESS)  # pruebas
    args = ap.parse_args(argv)

    vg = None if args.sin_control else cargar_vgamepad()

    cal = None
    if not args.calibrar and os.path.exists(args.archivo):
        with open(args.archivo, encoding="utf-8") as f:
            cal = {**CALIBRACION_DEFAULT, **json.load(f)}
        print(f"Calibración cargada de {args.archivo} (usa --calibrar para rehacerla)")

    cliente = ClienteDSU(args.ip, args.puerto, cal["slot"] if cal else None)
    if cal is None:
        cal = calibrar(cliente)
        with open(args.archivo, "w", encoding="utf-8") as f:
            json.dump(cal, f, indent=2, ensure_ascii=False)
        print(f"\n✓ Calibración guardada en {args.archivo}")
        cliente.vaciar()

    gs = GyroStick(args.gyro_max, cal["gyro_ruido"]) if args.gyro_stick else None
    if vg is None:
        salida = None
    elif args.modo == "xbox":
        salida = SalidaXbox(vg, gs)
    else:
        salida = SalidaDS4(vg, gs)

    print(f"\n▶ Control virtual {args.modo.upper()} activo"
          f"{' + gyro en stick derecho' if gs else ''}. Ctrl+C para salir.")
    if args.modo == "xbox" and not gs:
        print("  Nota: en modo xbox el juego no recibe giroscopio. Agrega --gyro-stick si lo quieres.")

    conectado = True
    ultimo_dato = time.monotonic()
    try:
        while True:
            e = cliente.recibir(0.5)
            if e is None:
                if conectado and time.monotonic() - ultimo_dato > 2:
                    conectado = False
                    if salida:
                        salida.neutral()  # que no se queden botones "pegados"
                    print("\n⚠ Sin datos del teléfono. Esperando reconexión...")
                continue
            ultimo_dato = time.monotonic()
            if not conectado:
                conectado = True
                print("✓ Reconectado.")
            if salida:
                salida.actualizar(e, cal)
            if args.monitor:
                m = aplicar_movimiento(e, cal)
                bl = [b for b, v in botones_logicos(e, cal).items() if v]
                _linea(f"L({stick(e, cal, 'lx'):+.2f},{stick(e, cal, 'ly'):+.2f}) "
                       f"R({stick(e, cal, 'rx'):+.2f},{stick(e, cal, 'ry'):+.2f}) "
                       f"gyro({m.gyro[0]:+6.1f},{m.gyro[1]:+6.1f},{m.gyro[2]:+6.1f}) "
                       f"{' '.join(bl)}")
    except KeyboardInterrupt:
        print("\nSaliendo.")
        if salida:
            salida.neutral()


if __name__ == "__main__":
    main()
