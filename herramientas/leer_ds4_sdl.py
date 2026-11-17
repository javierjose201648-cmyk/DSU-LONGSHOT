#!/usr/bin/env python3
"""Lee con SDL (la SDL3 de Longshot si existe) el DS4 virtual que creó OTRO
programa (p. ej. el .exe) durante unos segundos e imprime lo que ve.

    python herramientas/leer_ds4_sdl.py [segundos]
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import probar_ds4_sdl as h  # noqa: E402


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    seg = float(sys.argv[1]) if len(sys.argv) > 1 else 6
    dll = h.buscar_sdl3_longshot()
    sdl = h.SDL3(dll) if dll else h.SDL2()
    print(sdl.version)
    ctrl = None
    for _ in range(50):
        sdl.actualizar()
        ctrl = sdl.abrir_ds4()
        if ctrl:
            break
        time.sleep(0.1)
    if not ctrl:
        print("✗ No hay DS4 virtual")
        return 2
    print("Control:", sdl.nombre(ctrl), "| giroscopio:", sdl.tiene_sensor(ctrl, h.SENSOR_GYRO))
    sdl.activar_sensor(ctrl, h.SENSOR_GYRO)
    sdl.activar_sensor(ctrl, h.SENSOR_ACCEL)
    pico = [0.0, 0.0, 0.0]
    botones = set()
    stick_max = 0.0
    fin = time.monotonic() + seg
    while time.monotonic() < fin:
        sdl.actualizar()
        g = [x * 57.29578 for x in sdl.sensor(ctrl, h.SENSOR_GYRO)]
        for i in range(3):
            if abs(g[i]) > abs(pico[i]):
                pico[i] = g[i]
        botones |= {n for n, c in h.BOTON.items() if sdl.boton(ctrl, c)}
        stick_max = max(stick_max, abs(sdl.eje(ctrl, h.EJE_LX)) / 32767, abs(sdl.eje(ctrl, h.EJE_LY)) / 32767)
        time.sleep(0.01)
    a = [x / h.G for x in sdl.sensor(ctrl, h.SENSOR_ACCEL)]
    print(f"giro máximo por eje (°/s): {pico[0]:+.0f} {pico[1]:+.0f} {pico[2]:+.0f}")
    print(f"accel ahora (g): {a[0]:+.2f} {a[1]:+.2f} {a[2]:+.2f}")
    print("botones vistos:", sorted(botones))
    print(f"stick máximo: {stick_max:.2f}")
    sdl.cerrar(ctrl)
    ok = max(abs(x) for x in pico) > 20 and botones and stick_max > 0.8
    print("RESULTADO:", "OK" if ok else "FALLA")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
