#!/usr/bin/env python3
"""Etapa 0: comprueba POR PROGRAMA que SDL ve el DS4 virtual de ViGEmBus y lee
sus botones, stick, giroscopio y acelerómetro. No necesita el teléfono.

    python herramientas/probar_ds4_sdl.py            (SDL3 de Longshot si existe; si no, SDL2 de pysdl2)
    python herramientas/probar_ds4_sdl.py --sdl2     (forzar SDL2 de pysdl2-dll)
    python herramientas/probar_ds4_sdl.py --dll RUTA\\SDL3.dll

Crea un DS4 virtual con la MISMA clase que usa la app (SalidaDS4), le inyecta
valores conocidos y los lee de vuelta con la API de gamepad de SDL.
Sale con código 0 si todo coincide.
"""
import argparse
import ctypes
import glob
import os
import sys
import time

RAIZ = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, RAIZ)

from app.core.salidas import SalidaDS4  # noqa: E402
from app.core.transformar import EstadoLogico  # noqa: E402

SENSOR_ACCEL, SENSOR_GYRO = 1, 2
BOTON = {"A": 0, "B": 1, "X": 2, "Y": 3, "SELECT": 4, "HOME": 5, "START": 6, "L3": 7, "R3": 8,
         "L1": 9, "R1": 10, "ARRIBA": 11, "ABAJO": 12, "IZQ": 13, "DER": 14}
EJE_LX, EJE_LY, EJE_L2, EJE_R2 = 0, 1, 4, 5
G = 9.80665


class SDL3:
    def __init__(self, ruta):
        os.add_dll_directory(os.path.dirname(os.path.abspath(ruta)))
        s = self.s = ctypes.CDLL(ruta)
        s.SDL_GetError.restype = ctypes.c_char_p
        s.SDL_Init.restype = ctypes.c_bool
        s.SDL_GetGamepads.restype = ctypes.POINTER(ctypes.c_uint32)
        s.SDL_OpenGamepad.restype = ctypes.c_void_p
        s.SDL_GetGamepadName.restype = ctypes.c_char_p
        s.SDL_GetGamepadName.argtypes = [ctypes.c_void_p]
        s.SDL_GetGamepadVendorForID.restype = ctypes.c_uint16
        s.SDL_GetGamepadProductForID.restype = ctypes.c_uint16
        s.SDL_GamepadHasSensor.restype = ctypes.c_bool
        s.SDL_GamepadHasSensor.argtypes = [ctypes.c_void_p, ctypes.c_int]
        s.SDL_SetGamepadSensorEnabled.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_bool]
        s.SDL_GetGamepadSensorData.argtypes = [ctypes.c_void_p, ctypes.c_int,
                                               ctypes.POINTER(ctypes.c_float), ctypes.c_int]
        s.SDL_GetGamepadButton.restype = ctypes.c_bool
        s.SDL_GetGamepadButton.argtypes = [ctypes.c_void_p, ctypes.c_int]
        s.SDL_GetGamepadAxis.restype = ctypes.c_int16
        s.SDL_GetGamepadAxis.argtypes = [ctypes.c_void_p, ctypes.c_int]
        s.SDL_CloseGamepad.argtypes = [ctypes.c_void_p]
        s.SDL_SetHint.argtypes = [ctypes.c_char_p, ctypes.c_char_p]
        s.SDL_SetHint(b"SDL_JOYSTICK_ALLOW_BACKGROUND_EVENTS", b"1")
        if not s.SDL_Init(0x2000 | 0x8000 | 0x200):     # GAMEPAD | SENSOR | JOYSTICK
            raise RuntimeError("SDL_Init: " + s.SDL_GetError().decode())
        v = s.SDL_GetVersion()
        self.version = f"SDL {v // 1000000}.{v // 1000 % 1000}.{v % 1000} ({ruta})"

    def actualizar(self):
        self.s.SDL_PumpEvents()
        self.s.SDL_UpdateGamepads()

    def abrir_ds4(self):
        n = ctypes.c_int(0)
        ids = self.s.SDL_GetGamepads(ctypes.byref(n))
        for i in range(n.value):
            if (self.s.SDL_GetGamepadVendorForID(ids[i]),
                    self.s.SDL_GetGamepadProductForID(ids[i])) == (0x054C, 0x05C4):
                return self.s.SDL_OpenGamepad(ids[i])
        return None

    def nombre(self, c): return self.s.SDL_GetGamepadName(c).decode()
    def tiene_sensor(self, c, t): return bool(self.s.SDL_GamepadHasSensor(c, t))
    def activar_sensor(self, c, t): self.s.SDL_SetGamepadSensorEnabled(c, t, True)

    def sensor(self, c, t):
        d = (ctypes.c_float * 3)()
        self.s.SDL_GetGamepadSensorData(c, t, d, 3)
        return tuple(d)

    def boton(self, c, b): return bool(self.s.SDL_GetGamepadButton(c, b))
    def eje(self, c, e): return self.s.SDL_GetGamepadAxis(c, e)
    def cerrar(self, c):
        self.s.SDL_CloseGamepad(c)
        self.s.SDL_Quit()


class SDL2:
    def __init__(self):
        try:
            import sdl2dll  # noqa: F401
        except ImportError:
            pass
        import sdl2
        self.s = sdl2
        sdl2.SDL_SetHint(b"SDL_JOYSTICK_ALLOW_BACKGROUND_EVENTS", b"1")
        if sdl2.SDL_Init(sdl2.SDL_INIT_GAMECONTROLLER | sdl2.SDL_INIT_SENSOR) != 0:
            raise RuntimeError("SDL_Init: " + sdl2.SDL_GetError().decode())
        v = sdl2.SDL_version()
        sdl2.SDL_GetVersion(ctypes.byref(v))
        self.version = f"SDL {v.major}.{v.minor}.{v.patch} (pysdl2-dll)"

    def actualizar(self):
        self.s.SDL_PumpEvents()
        self.s.SDL_GameControllerUpdate()

    def abrir_ds4(self):
        s = self.s
        for i in range(s.SDL_NumJoysticks()):
            if s.SDL_IsGameController(i) and (
                    s.SDL_JoystickGetDeviceVendor(i), s.SDL_JoystickGetDeviceProduct(i)) == (0x054C, 0x05C4):
                return s.SDL_GameControllerOpen(i)
        return None

    def nombre(self, c): return self.s.SDL_GameControllerName(c).decode()
    def tiene_sensor(self, c, t): return bool(self.s.SDL_GameControllerHasSensor(c, t))
    def activar_sensor(self, c, t): self.s.SDL_GameControllerSetSensorEnabled(c, t, 1)

    def sensor(self, c, t):
        d = (ctypes.c_float * 3)()
        self.s.SDL_GameControllerGetSensorData(c, t, d, 3)
        return tuple(d)

    def boton(self, c, b): return bool(self.s.SDL_GameControllerGetButton(c, b))
    def eje(self, c, e): return self.s.SDL_GameControllerGetAxis(c, e)
    def cerrar(self, c):
        self.s.SDL_GameControllerClose(c)
        self.s.SDL_Quit()


def buscar_sdl3_longshot():
    patrones = [os.path.expanduser(r"~\Games\Longshot\*\bin\SDL3.dll")]
    for p in patrones:
        encontrados = sorted(glob.glob(p), key=os.path.getmtime, reverse=True)
        if encontrados:
            return encontrados[0]
    return None


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--dll", help="ruta a SDL3.dll")
    ap.add_argument("--sdl2", action="store_true")
    args = ap.parse_args()
    dll = None if args.sdl2 else (args.dll or buscar_sdl3_longshot())
    sdl = SDL3(dll) if dll else SDL2()
    print(sdl.version)

    salida = SalidaDS4()
    ctrl = None
    for _ in range(50):
        sdl.actualizar()
        ctrl = sdl.abrir_ds4()
        if ctrl:
            break
        time.sleep(0.1)
    if not ctrl:
        print("✗ SDL no encontró el DS4 virtual (VID 054C / PID 05C4).")
        return 2
    print("Control visto por SDL:", sdl.nombre(ctrl))
    gy, ac = sdl.tiene_sensor(ctrl, SENSOR_GYRO), sdl.tiene_sensor(ctrl, SENSOR_ACCEL)
    print(f"Tiene giroscopio: {gy} | tiene acelerómetro: {ac}")
    if not gy:
        print("✗ SDL NO expone el giroscopio del DS4 virtual.")
        return 1
    sdl.activar_sensor(ctrl, SENSOR_GYRO)
    sdl.activar_sensor(ctrl, SENSOR_ACCEL)

    casos = [
        # gyro °/s (pitch, yaw, roll) ; accel g ; botones ; stick (x, y)
        ((0.0, 0.0, 0.0), (0.0, 1.0, 0.0), set(), (0.0, 0.0)),
        ((90.0, 0.0, 0.0), (0.0, 1.0, 0.0), {"A"}, (1.0, 0.0)),
        ((0.0, -120.0, 0.0), (0.0, 0.7, 0.7), {"B", "L1"}, (0.0, 1.0)),
        ((0.0, 0.0, 45.0), (0.5, 0.86, 0.0), {"X", "Y", "R1", "START"}, (-1.0, -1.0)),
        ((30.0, 60.0, -90.0), (0.0, 1.0, 0.0), {"L2", "R2", "SELECT", "ARRIBA"}, (0.5, -0.5)),
        ((-200.0, 150.0, 10.0), (-0.3, 0.9, 0.2), {"HOME", "L3", "IZQ"}, (0.0, 0.0)),
    ]
    fallas = 0
    for gyro, accel, botones, (sx, sy) in casos:
        log = EstadoLogico()
        log.botones = {b: True for b in botones}
        log.lx, log.ly = sx, sy
        log.l2 = 255 if "L2" in botones else 0
        log.r2 = 255 if "R2" in botones else 0
        log.gyro, log.accel = gyro, accel
        fin = time.monotonic() + 0.4
        while time.monotonic() < fin:       # mandar varias veces, como en uso real
            salida.actualizar(log)
            sdl.actualizar()
            time.sleep(0.005)
        g = tuple(x * 57.29578 for x in sdl.sensor(ctrl, SENSOR_GYRO))     # SDL: rad/s
        a = tuple(x / G for x in sdl.sensor(ctrl, SENSOR_ACCEL))           # SDL: m/s²
        ok_g = all(abs(g[i] - gyro[i]) < 2.0 for i in range(3))
        ok_a = all(abs(a[i] - accel[i]) < 0.05 for i in range(3))
        leidos = {n for n, c in BOTON.items() if sdl.boton(ctrl, c)}
        if sdl.eje(ctrl, EJE_L2) > 16000:
            leidos.add("L2")
        if sdl.eje(ctrl, EJE_R2) > 16000:
            leidos.add("R2")
        ok_b = leidos == botones
        ax, ay = sdl.eje(ctrl, EJE_LX) / 32767, -sdl.eje(ctrl, EJE_LY) / 32767
        ok_s = abs(ax - sx) < 0.05 and abs(ay - sy) < 0.05
        bien = ok_g and ok_a and ok_b and ok_s
        fallas += not bien
        print(f"{'✓' if bien else '✗'} gyro {gyro} → ({g[0]:+.1f},{g[1]:+.1f},{g[2]:+.1f}) °/s"
              f"{'' if ok_g else ' MAL'} | accel {accel} → ({a[0]:+.2f},{a[1]:+.2f},{a[2]:+.2f}) g"
              f"{'' if ok_a else ' MAL'} | botones {sorted(leidos)}"
              f"{'' if ok_b else ' ESPERABA ' + str(sorted(botones))} | "
              f"stick ({ax:+.2f},{ay:+.2f}){'' if ok_s else ' MAL'}")
    salida.cerrar()
    sdl.cerrar(ctrl)
    print("RESULTADO:", "TODO OK — SDL lee botones, stick, giroscopio y acelerómetro del DS4 virtual"
          if not fallas else f"{fallas} caso(s) fallaron")
    return 0 if not fallas else 1


if __name__ == "__main__":
    sys.exit(main())
