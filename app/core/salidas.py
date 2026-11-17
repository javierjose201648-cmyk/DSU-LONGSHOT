"""Salidas: DS4 virtual, Xbox 360 virtual (ViGEmBus + vgamepad) y servidor DSU."""
import socket
import struct
import threading
import time

from app.i18n import T

from . import protocolo as P
from .transformar import GyroStick


# ------------------------------------------------------------------ ViGEmBus
class ErrorViGEm(Exception):
    """vgamepad/ViGEmBus no disponible. `falta_driver` distingue la causa."""

    def __init__(self, mensaje, falta_driver=False):
        super().__init__(mensaje)
        self.falta_driver = falta_driver


_vg = None


def cargar_vgamepad():
    """Importa vgamepad (carga ViGEmClient.dll). Lanza ErrorViGEm si no se puede."""
    global _vg
    if _vg is None:
        try:
            import vgamepad
            _vg = vgamepad
        except Exception as err:  # ImportError, OSError (DLL), AssertionError (bus)
            texto = str(err)
            falta = "VIGEM_ERROR_BUS_NOT_FOUND" in texto or "bus" in texto.lower()
            raise ErrorViGEm(T("No se pudo cargar el control virtual: ", "Could not load the virtual controller: ")
                             + str(texto), falta) from err
    return _vg


def estado_vigem():
    """(ok, mensaje). Crea y destruye un DS4 de prueba para confirmar el driver."""
    try:
        vg = cargar_vgamepad()
        pad = vg.VDS4Gamepad()
        del pad
        return True, T("ViGEmBus instalado y funcionando", "ViGEmBus installed and working")
    except ErrorViGEm as err:
        return False, str(err)
    except Exception as err:
        return False, T("ViGEmBus no responde: ", "ViGEmBus is not responding: ") + str(err)


def _a_byte(v):
    """-1..1 -> 0..255 (128 = centro)."""
    return max(0, min(255, int(round(128 + v * 127.5))))


def _a_short(v):
    return max(-32768, min(32767, int(round(v * 32767))))


def _hat(arriba, abajo, izq, der):
    dy = (1 if arriba else 0) - (1 if abajo else 0)
    dx = (1 if der else 0) - (1 if izq else 0)
    return {(0, 1): 0, (1, 1): 1, (1, 0): 2, (1, -1): 3, (0, -1): 4,
            (-1, -1): 5, (-1, 0): 6, (-1, 1): 7}.get((dx, dy), 8)


# Calibración interna del DualShock 4 virtual de ViGEmBus (la que lee SDL):
#   valor_calibrado = (crudo - bias) * num / den
# Gyro calibrado: 1024 unidades por °/s.  Accel calibrado: 8192 unidades por g.
_DS4_GYRO_CAL = ((0, 1105920, 17676), (0, 1105920, 17771), (0, 1105920, 17786))
_DS4_ACCEL_CAL = ((-297, 16384, 16209), (-42, 16384, 16148), (-512, 16384, 15988))


def crudo_ds4(valor, unidades_por, cal):
    bias, num, den = cal
    v = int(round(valor * unidades_por * den / num + bias))
    return max(-32768, min(32767, v))


def calibrado_ds4(crudo, unidades_por, cal):
    """Inversa de crudo_ds4: lo que calcula el driver/SDL a partir del crudo."""
    bias, num, den = cal
    return (crudo - bias) * num / den / unidades_por


def reporte_ds4_valores(log, gyro_stick=None):
    """Valores del reporte DS4 como dict (función pura, se prueba sin driver)."""
    b = log.botones
    rx, ry = log.rx, log.ry
    if gyro_stick:
        gx, gy = gyro_stick(log.gyro)
        rx, ry = max(-1.0, min(1.0, rx + gx)), max(-1.0, min(1.0, ry + gy))
    return {
        "botones": [n for n in ("A", "B", "X", "Y", "L1", "R1", "SELECT", "START", "L3", "R3")
                    if b.get(n)],
        "l2_dig": log.l2 > 30, "r2_dig": log.r2 > 30,
        "hat": _hat(b.get("ARRIBA"), b.get("ABAJO"), b.get("IZQ"), b.get("DER")),
        "ps": bool(b.get("HOME")), "touch": bool(b.get("TOUCH")),
        "l2": log.l2, "r2": log.r2,
        # DS4: Y = 0 arriba, así que se invierte
        "lx": _a_byte(log.lx), "ly": _a_byte(-log.ly), "rx": _a_byte(rx), "ry": _a_byte(-ry),
        "gyro": tuple(crudo_ds4(log.gyro[i], 1024, _DS4_GYRO_CAL[i]) for i in range(3)),
        "accel": tuple(crudo_ds4(log.accel[i], 8192, _DS4_ACCEL_CAL[i]) for i in range(3)),
    }


class SalidaDS4:
    """DualShock 4 virtual con giroscopio y acelerómetro reales."""
    nombre = "DS4"

    def __init__(self, vg=None, gyro_stick_cfg=None):
        self.vg = vg or cargar_vgamepad()
        try:
            self.pad = self.vg.VDS4Gamepad()
        except Exception as err:
            raise ErrorViGEm(T("No se pudo crear el DS4 virtual: ", "Could not create the virtual DS4: ")
                             + str(err), True) from err
        self.gyro_stick = GyroStick(gyro_stick_cfg) if gyro_stick_cfg else None
        self._t0 = time.perf_counter()
        D = self.vg.DS4_BUTTONS
        self._tabla = {
            "A": int(D.DS4_BUTTON_CROSS), "B": int(D.DS4_BUTTON_CIRCLE),
            "X": int(D.DS4_BUTTON_SQUARE), "Y": int(D.DS4_BUTTON_TRIANGLE),
            "L1": int(D.DS4_BUTTON_SHOULDER_LEFT), "R1": int(D.DS4_BUTTON_SHOULDER_RIGHT),
            "SELECT": int(D.DS4_BUTTON_SHARE), "START": int(D.DS4_BUTTON_OPTIONS),
            "L3": int(D.DS4_BUTTON_THUMB_LEFT), "R3": int(D.DS4_BUTTON_THUMB_RIGHT),
        }
        self._l2 = int(D.DS4_BUTTON_TRIGGER_LEFT)
        self._r2 = int(D.DS4_BUTTON_TRIGGER_RIGHT)
        S = self.vg.DS4_SPECIAL_BUTTONS
        self._ps, self._touch = int(S.DS4_SPECIAL_BUTTON_PS), int(S.DS4_SPECIAL_BUTTON_TOUCHPAD)
        self.error = ""
        self._valores = self._neutro()
        self._activo = True
        self._hilo = threading.Thread(target=self._bucle, name="ds4-250hz", daemon=True)
        self._hilo.start()

    # Un DS4 real manda reportes a 250 Hz. El teléfono solo da ~54 paquetes/s
    # (~33 muestras de movimiento), así que un hilo re-envía el último estado
    # a ritmo fijo con el reloj avanzando: el juego nunca ve "huecos" de gyro.
    HZ = 250

    def _neutro(self):
        return {"botones": [], "l2_dig": False, "r2_dig": False, "hat": 8, "ps": False,
                "touch": False, "l2": 0, "r2": 0, "lx": 128, "ly": 128, "rx": 128, "ry": 128,
                # en neutro el control "descansa plano": gravedad en +Y, sin giro
                "gyro": tuple(crudo_ds4(0, 1024, c) for c in _DS4_GYRO_CAL),
                "accel": tuple(crudo_ds4(g, 8192, c)
                               for g, c in zip((0.0, 1.0, 0.0), _DS4_ACCEL_CAL))}

    def _enviar(self, v):
        rep = self.pad.get_default_extended_report()
        r = rep.Report
        mask = v["hat"]
        for n in v["botones"]:
            mask |= self._tabla[n]
        if v["l2_dig"]:
            mask |= self._l2
        if v["r2_dig"]:
            mask |= self._r2
        r.wButtons = mask
        r.bSpecial = (self._ps if v["ps"] else 0) | (self._touch if v["touch"] else 0)
        r.bTriggerL, r.bTriggerR = v["l2"], v["r2"]
        r.bThumbLX, r.bThumbLY, r.bThumbRX, r.bThumbRY = v["lx"], v["ly"], v["rx"], v["ry"]
        # Reloj propio que SIEMPRE avanza (unidades de 5.33 µs, como el DS4 real):
        # la app del teléfono repite timestamps y eso confundiría a quien integre.
        r.wTimestamp = int((time.perf_counter() - self._t0) * 187500) & 0xFFFF
        r.wGyroX, r.wGyroY, r.wGyroZ = v["gyro"]
        r.wAccelX, r.wAccelY, r.wAccelZ = v["accel"]
        self.pad.update_from_extended_report(rep)

    def _bucle(self):
        periodo = 1.0 / self.HZ
        sig = time.perf_counter()
        while self._activo:
            try:
                self._enviar(self._valores)
            except Exception as err:
                self.error = str(err)
            sig += periodo
            espera = sig - time.perf_counter()
            if espera > 0:
                time.sleep(espera)
            else:
                sig = time.perf_counter()

    def actualizar(self, log):
        self._valores = reporte_ds4_valores(log, self.gyro_stick)   # asignación atómica

    def neutral(self):
        self._valores = self._neutro()

    def cerrar(self):
        self._activo = False
        if self._hilo.is_alive():
            self._hilo.join(timeout=1)
        try:
            self._enviar(self._neutro())
        except Exception:
            pass
        self.pad = None


class SalidaXbox:
    """Xbox 360 virtual. XInput no tiene giroscopio: usar gyro->stick."""
    nombre = "Xbox 360"

    def __init__(self, vg=None, gyro_stick_cfg=None):
        self.vg = vg or cargar_vgamepad()
        try:
            self.pad = self.vg.VX360Gamepad()
        except Exception as err:
            raise ErrorViGEm(T("No se pudo crear el control Xbox virtual: ",
                               "Could not create the virtual Xbox controller: ") + str(err), True) from err
        self.gyro_stick = GyroStick(gyro_stick_cfg) if gyro_stick_cfg else None
        B = self.vg.XUSB_BUTTON
        self._tabla = {
            "A": B.XUSB_GAMEPAD_A, "B": B.XUSB_GAMEPAD_B, "X": B.XUSB_GAMEPAD_X,
            "Y": B.XUSB_GAMEPAD_Y, "L1": B.XUSB_GAMEPAD_LEFT_SHOULDER,
            "R1": B.XUSB_GAMEPAD_RIGHT_SHOULDER, "SELECT": B.XUSB_GAMEPAD_BACK,
            "START": B.XUSB_GAMEPAD_START, "L3": B.XUSB_GAMEPAD_LEFT_THUMB,
            "R3": B.XUSB_GAMEPAD_RIGHT_THUMB, "ARRIBA": B.XUSB_GAMEPAD_DPAD_UP,
            "ABAJO": B.XUSB_GAMEPAD_DPAD_DOWN, "IZQ": B.XUSB_GAMEPAD_DPAD_LEFT,
            "DER": B.XUSB_GAMEPAD_DPAD_RIGHT, "HOME": B.XUSB_GAMEPAD_GUIDE,
        }

    def actualizar(self, log):
        mask = 0
        for nombre, bit in self._tabla.items():
            if log.botones.get(nombre):
                mask |= int(bit)
        rx, ry = log.rx, log.ry
        if self.gyro_stick:
            gx, gy = self.gyro_stick(log.gyro)
            rx, ry = max(-1.0, min(1.0, rx + gx)), max(-1.0, min(1.0, ry + gy))
        r = self.pad.report
        r.wButtons = mask
        r.bLeftTrigger, r.bRightTrigger = log.l2, log.r2
        r.sThumbLX, r.sThumbLY = _a_short(log.lx), _a_short(log.ly)   # XInput: + arriba
        r.sThumbRX, r.sThumbRY = _a_short(rx), _a_short(ry)
        self.pad.update()

    def neutral(self):
        self.pad.reset()
        self.pad.update()

    def cerrar(self):
        try:
            self.neutral()
        except Exception:
            pass
        self.pad = None


# ---------------------------------------------------------------- servidor DSU
def movimiento_a_dsu(gyro, accel):
    """Marco estándar (SDL) -> convención DSU que esperan Dolphin y compañía.

    Tomado de cómo Dolphin interpreta los campos (DualShockUDPClient.cpp):
    'Accel Up' = -accel_y, 'Accel Left' = +accel_x, 'Accel Forward' = +accel_z,
    'Gyro Pitch Up' = +pitch, 'Gyro Roll Left' = -roll, 'Gyro Yaw Left' = -yaw.
    """
    return ((gyro[0], -gyro[1], -gyro[2]), (-accel[0], -accel[1], -accel[2]))


class ServidorDSU:
    """Re-emite el control lógico (ya calibrado y rotado) como servidor DSU en
    el slot 0. Lo leen Dolphin y los emuladores con cliente DSU/cemuhook."""
    nombre = "Servidor DSU"
    MAC = b"\x02DSULS"
    TIEMPO_CLIENTE = 5.0

    def __init__(self, puerto=26761, host="0.0.0.0", crudo=False):
        self.puerto = puerto
        self.crudo = crudo            # True = movimiento sin convertir (orientación física)
        self.server_id = 0x4C534455
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            self.sock.bind((host, puerto))
        except OSError as err:
            self.sock.close()
            raise OSError(f"No se pudo abrir el puerto UDP {puerto} para el servidor DSU "
                          f"(¿otra app lo usa?): {err}") from err
        self.sock.settimeout(0.2)
        self._clientes = {}           # addr -> último registro
        self._candado = threading.Lock()
        self._num = 0
        self._t0 = time.perf_counter()
        self._activo = True
        self._conectado = False
        self._hilo = threading.Thread(target=self._escuchar, name="servidor-dsu", daemon=True)
        self._hilo.start()

    # -- recepción de solicitudes
    def _escuchar(self):
        while self._activo:
            try:
                datos, addr = self.sock.recvfrom(1024)
            except socket.timeout:
                continue
            except OSError:
                if not self._activo:
                    return
                continue
            r = P.validar(datos, b"DSUC")
            if r is None:
                continue
            tipo, datos, _ = r
            try:
                if tipo == P.MSG_VERSION:
                    self.sock.sendto(P.paquete_servidor(
                        P.MSG_VERSION, struct.pack("<H", P.VERSION_PROTOCOLO), self.server_id), addr)
                elif tipo == P.MSG_INFO and len(datos) >= 24:
                    n = max(0, min(4, struct.unpack_from("<i", datos, 20)[0]))
                    for slot in datos[24:24 + n]:
                        self.sock.sendto(P.construir_info(
                            slot, conectado=(slot == 0), mac=self.MAC, server_id=self.server_id), addr)
                elif tipo == P.MSG_DATOS and len(datos) >= 28:
                    flags, slot, mac = datos[20], datos[21], datos[22:28]
                    # flags: 0 = todos, bit0 = por slot, bit1 = por MAC
                    if flags == 0 or (flags & 1 and slot == 0) or (flags & 2 and mac == self.MAC):
                        with self._candado:
                            self._clientes[addr] = time.monotonic()
            except OSError:
                continue

    def clientes(self):
        ahora = time.monotonic()
        with self._candado:
            for addr in [a for a, t in self._clientes.items() if ahora - t > self.TIEMPO_CLIENTE]:
                del self._clientes[addr]
            return list(self._clientes)

    # -- emisión
    def _enviar(self, log, botones):
        destinos = self.clientes()
        if not destinos:
            return
        self._num += 1
        if self.crudo:
            gyro, accel = log.gyro_crudo, log.accel_crudo
        else:
            gyro, accel = movimiento_a_dsu(log.gyro, log.accel)
        paquete = P.construir_datos(
            0, self._num, botones,
            lx=_a_byte(log.lx), ly=_a_byte(log.ly),      # DSU: Y = 255 arriba
            rx=_a_byte(log.rx), ry=_a_byte(log.ry),
            ts_us=int((time.perf_counter() - self._t0) * 1e6),   # siempre avanza
            accel=accel, gyro=gyro, l2=log.l2, r2=log.r2,
            mac=self.MAC, server_id=self.server_id)
        for addr in destinos:
            try:
                self.sock.sendto(paquete, addr)
            except OSError:
                pass

    def actualizar(self, log):
        self._enviar(log, log.presionados())

    def neutral(self):
        from .transformar import EstadoLogico
        self._enviar(EstadoLogico(), [])

    def cerrar(self):
        self._activo = False
        try:
            self.sock.close()
        except OSError:
            pass
