"""Protocolo DSU (cemuhook): paquetes, parser y cliente UDP.

Spec: https://v1993.github.io/cemuhook-protocol/
Lógica tomada de referencia/dsu_bridge.py (probada con el teléfono real) y
ampliada con el lado servidor (para ServidorDSU y el simulador de pruebas).
"""
import socket
import struct
import time
import zlib

PUERTO_DEFAULT = 26760
VERSION_PROTOCOLO = 1001
MSG_VERSION = 0x100000
MSG_INFO = 0x100001
MSG_DATOS = 0x100002
CLIENT_ID = 0x4A534231  # arbitrario

# Nombres de los bits tal como vienen en el protocolo (convención DS4 por posición
# estilo Xbox: A = abajo, B = derecha, X = izquierda, Y = arriba).
BOTONES = ["A", "B", "X", "Y", "L1", "R1", "L2", "R2", "SELECT", "START",
           "L3", "R3", "ARRIBA", "ABAJO", "IZQ", "DER", "HOME", "TOUCH"]

# byte 36: bit0..bit7 ; byte 37: bit0..bit7
_BITS_36 = ["SELECT", "L3", "R3", "START", "ARRIBA", "DER", "ABAJO", "IZQ"]
_BITS_37 = ["L2", "R2", "L1", "R1", "Y", "B", "A", "X"]   # bit4 △, bit5 ○, bit6 ✕, bit7 □
# bytes analógicos 44..55
_ANALOGICOS = ["IZQ", "ABAJO", "DER", "ARRIBA", "X", "A", "B", "Y", "R1", "L1", "R2", "L2"]


def _crc(datos):
    return zlib.crc32(datos[:8] + b"\0\0\0\0" + datos[12:]) & 0xFFFFFFFF


def _armar(magia, ident, tipo, payload=b""):
    cuerpo = struct.pack("<I", tipo) + payload
    cab = struct.pack("<4sHHII", magia, VERSION_PROTOCOLO, len(cuerpo), 0, ident)
    crc = zlib.crc32(cab + cuerpo) & 0xFFFFFFFF
    return struct.pack("<4sHHII", magia, VERSION_PROTOCOLO, len(cuerpo), crc, ident) + cuerpo


def paquete_cliente(tipo, payload=b"", client_id=CLIENT_ID):
    """Paquete que manda un cliente DSU (magia DSUC)."""
    return _armar(b"DSUC", client_id, tipo, payload)


def paquete_servidor(tipo, payload=b"", server_id=0x06B6722C):
    """Paquete que manda un servidor DSU (magia DSUS)."""
    return _armar(b"DSUS", server_id, tipo, payload)


def solicitud_datos(client_id=CLIENT_ID):
    # flags=0: suscribirse a todos los slots (lo soportan todos los servidores)
    return paquete_cliente(MSG_DATOS, struct.pack("<BB6s", 0, 0, b"\0" * 6), client_id)


def solicitud_info(client_id=CLIENT_ID, slots=(0, 1, 2, 3)):
    return paquete_cliente(MSG_INFO, struct.pack("<i", len(slots)) + bytes(slots), client_id)


def solicitud_version(client_id=CLIENT_ID):
    return paquete_cliente(MSG_VERSION, b"", client_id)


def validar(datos, magia=b"DSUS"):
    """Devuelve (tipo, datos_recortados, id) si el paquete es válido (magia,
    largo y CRC); None si no."""
    if len(datos) < 20 or datos[:4] != magia:
        return None
    _, _, largo, crc, ident = struct.unpack_from("<4sHHII", datos)
    if len(datos) < 16 + largo or largo < 4:
        return None
    datos = datos[:16 + largo]
    if _crc(datos) != crc:
        return None
    return struct.unpack_from("<I", datos, 16)[0], datos, ident


class Estado:
    """Un paquete de datos del control, ya decodificado (valores crudos)."""
    __slots__ = ("slot", "modelo", "conexion", "bateria", "num_paquete", "fuente",
                 "lx", "ly", "rx", "ry", "l2_analog", "r2_analog",
                 "toques", "ts_us", "accel", "gyro", "t_llegada")

    def presionados(self):
        return [b for b, v in self.fuente.items() if v]


def parsear_paquete(datos):
    """Devuelve Estado para paquetes de datos válidos; None para todo lo demás."""
    r = validar(datos)
    if r is None:
        return None
    tipo, datos, _ = r
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
        "X": bool(b2 & 0x80), "A": bool(b2 & 0x40), "B": bool(b2 & 0x20),
        "Y": bool(b2 & 0x10), "R1": bool(b2 & 0x08), "L1": bool(b2 & 0x04),
        "R2": bool(b2 & 0x02), "L2": bool(b2 & 0x01),
        "HOME": bool(home), "TOUCH": bool(touch),
    }
    e.lx, e.ly, e.rx, e.ry = datos[40], datos[41], datos[42], datos[43]
    e.r2_analog, e.l2_analog = datos[54], datos[55]
    # Algunas apps no llenan el bit de los gatillos: el analógico cuenta como presionado
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


def construir_info(slot, conectado=True, modelo=2, conexion=1,
                   mac=b"DSU001", bateria=5, server_id=0x06B6722C):
    """Respuesta 'información de slot' (16 bytes de cabecera + 4 tipo + 12)."""
    payload = struct.pack("<BBBB6sBB", slot, 2 if conectado else 0,
                          modelo if conectado else 0, conexion if conectado else 0,
                          mac if conectado else b"\0" * 6, bateria if conectado else 0, 0)
    return paquete_servidor(MSG_INFO, payload, server_id)


def construir_datos(slot, num_paquete, botones=(), lx=128, ly=128, rx=128, ry=128,
                    ts_us=0, accel=(0.0, 0.0, 0.0), gyro=(0.0, 0.0, 0.0),
                    l2=None, r2=None, modelo=2, conexion=1, mac=b"DSU001",
                    bateria=5, server_id=0x06B6722C):
    """Paquete de datos de 100 bytes. `botones`: nombres de BOTONES presionados.
    Rellena también los analógicos por botón como hace la app del teléfono."""
    botones = set(botones)
    b1 = sum(1 << i for i, n in enumerate(_BITS_36) if n in botones)
    b2 = sum(1 << i for i, n in enumerate(_BITS_37) if n in botones)
    analog = [255 if n in botones else 0 for n in _ANALOGICOS]
    if r2 is not None:
        analog[10] = r2
    if l2 is not None:
        analog[11] = l2
    payload = struct.pack("<BBBB6sBB", slot, 2, modelo, conexion, mac, bateria, 1)
    payload += struct.pack("<I", num_paquete & 0xFFFFFFFF)
    payload += bytes([b1, b2, 255 if "HOME" in botones else 0, 255 if "TOUCH" in botones else 0,
                      lx & 0xFF, ly & 0xFF, rx & 0xFF, ry & 0xFF])
    payload += bytes(analog)
    payload += b"\0" * 12                      # dos toques inactivos
    payload += struct.pack("<Q", ts_us & 0xFFFFFFFFFFFFFFFF)
    payload += struct.pack("<3f", *accel) + struct.pack("<3f", *gyro)
    return paquete_servidor(MSG_DATOS, payload, server_id)


class ClienteDSU:
    """Cliente UDP: se suscribe (y se re-suscribe cada segundo) y entrega Estados."""

    def __init__(self, ip, puerto=PUERTO_DEFAULT, slot=None):
        self.destino = (ip, puerto)
        self.slot = slot  # None = el primero que mande datos
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("0.0.0.0", 0))
        self.sock.settimeout(0.05)
        self._ultima_solicitud = 0.0
        self._ultimo_num = None
        self._t_ultimo = 0.0
        self.paquetes_malos = 0
        self.error_red = None

    def _solicitar(self):
        ahora = time.monotonic()
        if ahora - self._ultima_solicitud < 1.0:
            return
        self._ultima_solicitud = ahora
        try:
            self.sock.sendto(solicitud_datos(), self.destino)
            self.sock.sendto(solicitud_info(), self.destino)
            self.error_red = None
        except OSError as err:
            self.error_red = str(err)  # red caída; se reintenta en el siguiente ciclo

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
                # En Windows un ICMP "puerto inalcanzable" aparece como error aquí
                time.sleep(0.05)
                continue
            e = parsear_paquete(datos)
            if e is None:
                if datos[:4] == b"DSUS" and len(datos) >= 100 and validar(datos) is None:
                    self.paquetes_malos += 1
                continue
            if self.slot is None:
                self.slot = e.slot
            if e.slot != self.slot:
                continue
            # Descartar paquetes UDP fuera de orden (salvo que el servidor se
            # haya reiniciado: tras 1 s de silencio se acepta cualquier número)
            if self._ultimo_num is not None and e.t_llegada - self._t_ultimo < 1.0:
                delta = (e.num_paquete - self._ultimo_num) & 0xFFFFFFFF
                if delta == 0 or delta > 0x7FFFFFFF:
                    continue
            self._ultimo_num = e.num_paquete
            self._t_ultimo = e.t_llegada
            return e
        return None

    def cerrar(self):
        try:
            self.sock.close()
        except OSError:
            pass
