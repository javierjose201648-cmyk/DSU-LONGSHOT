"""Cadena completa SIN teléfono: simulador -> motor -> DS4 virtual -> SDL.

Necesita ViGEmBus instalado y una SDL (la SDL3 de Longshot o pysdl2-dll). Si
falta alguno, la prueba se salta (p. ej. en GitHub Actions).
"""
import os
import sys
import time

import pytest

from app.core import perfiles as PF
from app.core.motor import Motor
from app.core.salidas import estado_vigem
from app.tests.robot import calibrar_con_robot
from app.tests.simulador import SimuladorApp

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "herramientas"))

G = 9.80665


@pytest.fixture(scope="module")
def sdl():
    ok, msg = estado_vigem()
    if not ok:
        pytest.skip("ViGEmBus no disponible: " + msg)
    try:
        import probar_ds4_sdl as herr
        dll = herr.buscar_sdl3_longshot()
        return herr, (herr.SDL3(dll) if dll else herr.SDL2())
    except Exception as err:      # sin SDL instalada
        pytest.skip(f"SDL no disponible: {err}")


def test_simulador_motor_ds4_sdl(sdl):
    herr, s = sdl
    with SimuladorApp() as sim:
        _, perfil = calibrar_con_robot(sim, PF.perfil_por_defecto("lado"))
        m = Motor()
        m.conectar("127.0.0.1", sim.puerto, perfil)
        m.jugar(True)
        ctrl = None
        try:
            for _ in range(60):
                s.actualizar()
                ctrl = s.abrir_ds4()
                if ctrl:
                    break
                time.sleep(0.1)
            assert ctrl, "SDL no vio el DS4 virtual"
            assert s.tiene_sensor(ctrl, herr.SENSOR_GYRO)
            s.activar_sensor(ctrl, herr.SENSOR_GYRO)
            s.activar_sensor(ctrl, herr.SENSOR_ACCEL)

            def esperar(seg):
                fin = time.monotonic() + seg
                while time.monotonic() < fin:
                    s.actualizar()
                    time.sleep(0.005)

            esperar(0.5)
            assert m.foto().salidas == ["DS4"] and not m.foto().error_salida

            # Botones del mapeo por defecto para Longshot (botón físico -> botón SDL)
            esperado = {"F_IZQ": "A", "F_ABAJO": "B", "F_ARRIBA": "X", "F_DER": "Y",
                        "SL": "L1", "SR": "R1", "MENOS": "SELECT", "MAS": "START"}
            for fisico, boton in esperado.items():
                sim.soltar()
                sim.presionar(fisico)
                esperar(0.2)
                leidos = {n for n, c in herr.BOTON.items() if s.boton(ctrl, c)}
                assert leidos == {boton}, fisico
            sim.soltar()
            sim.presionar("ZL")
            esperar(0.2)
            assert s.eje(ctrl, herr.EJE_L2) > 30000 and s.eje(ctrl, herr.EJE_R2) == 0
            sim.soltar()
            sim.presionar("VERDE")
            esperar(0.2)
            assert s.eje(ctrl, herr.EJE_R2) > 30000 and s.eje(ctrl, herr.EJE_L2) == 0
            sim.soltar()

            # Stick en coordenadas del usuario
            for (x, y) in [(0, 1), (1, 0), (0, -1), (-1, 0)]:
                sim.stick(x, y)
                esperar(0.2)
                ax, ay = s.eje(ctrl, herr.EJE_LX) / 32767, -s.eje(ctrl, herr.EJE_LY) / 32767
                assert abs(ax - x) < 0.06 and abs(ay - y) < 0.06, (x, y, ax, ay)
            sim.stick(0, 0)
            esperar(0.2)

            # Gravedad en reposo y giroscopio en cada eje
            a = [v / G for v in s.sensor(ctrl, herr.SENSOR_ACCEL)]
            assert a[1] > 0.9 and abs(a[0]) < 0.15 and abs(a[2]) < 0.15
            for eje in range(3):
                sim.girar(eje, 60, 0.6)             # 100 °/s
                esperar(0.15)
                muestras = []
                fin = time.monotonic() + 0.3
                while time.monotonic() < fin:
                    s.actualizar()
                    muestras.append([v * 57.29578 for v in s.sensor(ctrl, herr.SENSOR_GYRO)])
                    time.sleep(0.01)
                media = [sum(x[i] for x in muestras) / len(muestras) for i in range(3)]
                assert media[eje] == pytest.approx(100, abs=12), (eje, media)
                assert all(abs(media[i]) < 12 for i in range(3) if i != eje), (eje, media)
                esperar(0.3)
                sim.girar(eje, -60, 0.6)
                esperar(0.8)

            # Sin datos > 2 s: el control queda en neutro (nada pegado)
            sim.presionar("F_IZQ")
            sim.stick(1, 0)
            esperar(0.3)
            assert s.boton(ctrl, herr.BOTON["A"])
            sim.pausado = True
            esperar(2.8)
            assert not s.boton(ctrl, herr.BOTON["A"])
            assert abs(s.eje(ctrl, herr.EJE_LX)) < 1500
        finally:
            m.detener()


def test_wii_classic_hasta_sdl(sdl):
    """Wii Classic (simulado): todos sus botones y los DOS sticks llegan a SDL."""
    from app.core import controles as CT
    herr, s = sdl
    with SimuladorApp(control="wii-classic") as sim:
        _, perfil = calibrar_con_robot(sim, PF.perfil_por_defecto(control="wii-classic"))
        m = Motor()
        m.conectar("127.0.0.1", sim.puerto, perfil)
        m.jugar(True)
        try:
            ctrl = None
            for _ in range(60):
                s.actualizar()
                ctrl = s.abrir_ds4()
                if ctrl:
                    break
                time.sleep(0.1)
            assert ctrl, "SDL no vio el DS4 virtual"

            def esperar(seg):
                fin = time.monotonic() + seg
                while time.monotonic() < fin:
                    s.actualizar()
                    time.sleep(0.005)

            esperar(0.5)
            for b in CT.WII_CLASSIC.botones:
                sim.soltar()
                sim.presionar(b.id)
                esperar(0.2)
                if b.esperado in ("L2", "R2"):
                    eje = herr.EJE_L2 if b.esperado == "L2" else herr.EJE_R2
                    assert s.eje(ctrl, eje) > 30000, b.id
                    continue
                leidos = {n for n, c in herr.BOTON.items() if s.boton(ctrl, c)}
                assert leidos == {b.esperado}, b.id
            sim.soltar()
            for (x, y) in [(0, 1), (1, 0), (0, -1), (-1, 0)]:
                sim.stick(x, y)
                sim.stick(-y, x, "der")
                esperar(0.2)
                lx, ly = s.eje(ctrl, herr.EJE_LX) / 32767, -s.eje(ctrl, herr.EJE_LY) / 32767
                rx, ry = s.eje(ctrl, 2) / 32767, -s.eje(ctrl, 3) / 32767
                assert abs(lx - x) < 0.06 and abs(ly - y) < 0.06, (x, y, lx, ly)
                assert abs(rx + y) < 0.06 and abs(ry - x) < 0.06, (x, y, rx, ry)
            sim.stick(0, 0)
            sim.stick(0, 0, "der")
        finally:
            m.detener()
