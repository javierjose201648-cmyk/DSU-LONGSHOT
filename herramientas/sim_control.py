#!/usr/bin/env python3
"""Simulador + motor sin interfaz, manejado por un archivo de órdenes.

Sirve para probar la cadena completa dentro de un juego real sin teléfono:
    python herramientas/sim_control.py ORDENES.txt

Cada línea que se AGREGA al archivo es una orden:
    presionar SL SR 0.3      (botones físicos del Joy-Con, segundos)
    stick 0 1 0.5            (x, y del usuario, segundos)
    girar 1 40 0.8           (eje 0 pitch / 1 yaw / 2 roll, grados, segundos)
    estado                   (imprime lo que ve el motor)
    salir
"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from app.core import perfiles as PF  # noqa: E402
from app.core.motor import Motor  # noqa: E402
from app.tests.robot import calibrar_con_robot  # noqa: E402
from app.tests.simulador import SimuladorApp  # noqa: E402


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    ordenes = sys.argv[1]
    open(ordenes, "a").close()
    sim = SimuladorApp().iniciar()
    print("Calibrando con el robot...")
    _, perfil = calibrar_con_robot(sim, PF.perfil_por_defecto("lado"))
    m = Motor()
    m.conectar("127.0.0.1", sim.puerto, perfil)
    m.jugar(True)
    time.sleep(1)
    f = m.foto()
    print(f"LISTO estado={f.estado} salidas={f.salidas} error={f.error_salida!r} pps={f.pps} mps={f.mps}")
    pos = 0
    try:
        while True:
            with open(ordenes, encoding="utf-8") as fh:
                fh.seek(pos)
                lineas = fh.readlines()
                pos = fh.tell()
            for linea in lineas:
                p = linea.split()
                if not p:
                    continue
                print(">", linea.strip())
                if p[0] == "salir":
                    return
                if p[0] == "presionar":
                    sim.presionar(*p[1:-1])
                    time.sleep(float(p[-1]))
                    sim.soltar()
                    time.sleep(0.15)
                elif p[0] == "stick":
                    sim.stick(float(p[1]), float(p[2]))
                    time.sleep(float(p[3]))
                    sim.stick(0, 0)
                    time.sleep(0.15)
                elif p[0] == "girar":
                    sim.girar(int(p[1]), float(p[2]), float(p[3]))
                    time.sleep(float(p[3]) + 0.1)
                elif p[0] == "estado":
                    f = m.foto()
                    print(f"  estado={f.estado} pps={f.pps} mps={f.mps} salidas={f.salidas} "
                          f"error={f.error_salida!r} botones={f.logico.presionados() if f.logico else None}")
            time.sleep(0.1)
    finally:
        m.detener()
        sim.detener()
        print("FIN")


if __name__ == "__main__":
    main()
