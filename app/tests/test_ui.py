"""Recorre la interfaz completa contra el simulador (sin teléfono ni pantalla):
conectar -> asistente con usuario robot -> guardar perfil -> reabrir y jugar.

Guarda capturas en build/capturas_ui/ para revisar el aspecto a ojo.
"""
import os
import time

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from app.core import perfiles as PF  # noqa: E402
from app.core.motor import CONECTADO  # noqa: E402
from app.tests.simulador import SimuladorApp  # noqa: E402

CAPTURAS = os.path.join(os.path.dirname(__file__), "..", "..", "build", "capturas_ui")
EJE = {"pitch": 0, "yaw": 1, "roll": 2}


@pytest.fixture(scope="module")
def qt():
    app = QApplication.instance() or QApplication([])
    from app.ui.tema import ESTILO
    app.setStyle("Fusion")
    app.setStyleSheet(ESTILO)
    return app


def _bombear(qt, segundos, hasta=None):
    fin = time.monotonic() + segundos
    while time.monotonic() < fin:
        qt.processEvents()
        if hasta and hasta():
            return True
        time.sleep(0.01)
    return False


def _foto(v, nombre):
    os.makedirs(CAPTURAS, exist_ok=True)
    v.grab().save(os.path.join(CAPTURAS, nombre + ".png"))


def _robot_ui(qt, sim, cal, limite=90, prefijo="3_asistente_"):
    """Hace lo que pide el asistente de la UI, mirando su paso actual."""
    visto = None
    fotos = set()
    fin = time.monotonic() + limite
    while cal.modo == "pasos" and time.monotonic() < fin:
        qt.processEvents()
        time.sleep(0.01)
        if cal.modo != "pasos" or cal.asis is None:
            break
        p = cal.asis.paso
        clave = (p.id, p.estado, p.info.get("fase"))
        if p.tipo not in fotos and p.progreso > 0.3 or (p.tipo == "boton" and "boton" not in fotos):
            fotos.add(p.tipo)
            _foto(cal.v, prefijo + p.tipo + ("_der" if p.info.get("cual") == "der" else ""))
        if clave == visto:
            continue
        visto = clave
        if p.tipo == "boton":
            if p.estado == "esperando":
                sim.soltar()
                _bombear(qt, 0.1)
                sim.presionar(p.info["fisico"])
            else:
                sim.soltar()
        elif p.tipo == "stick_centro":
            sim.stick(0, 0, p.info.get("cual", "izq"))
        elif p.tipo == "stick_dir":
            sim.stick(*(((0, 1) if p.info["direccion"] == "arriba" else (1, 0))
                        if p.estado == "esperando" else (0, 0)), p.info.get("cual", "izq"))
        elif p.tipo == "gesto":
            sim.girar(EJE[p.info["eje"]], -50 if p.info.get("fase") == "regresar" else 50, 0.7)
    sim.soltar()
    sim.stick(0, 0)
    sim.stick(0, 0, "der")
    assert cal.modo == "verificar", f"el asistente se quedó en {cal.asis.paso.id if cal.asis else None}"


def test_flujo_completo_de_la_interfaz(qt, tmp_path, monkeypatch):
    monkeypatch.setenv("DSU_PAD_DATOS", str(tmp_path))
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: QMessageBox.Ok)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: QMessageBox.Ok)
    from app.ui.ventana import Ventana

    with SimuladorApp() as sim:
        v = Ventana()
        v.show()
        # Para la prueba no se crea el control virtual (eso lo cubre test_ds4_real)
        v.perfil["salidas"] = {"ds4": False, "xbox": False, "dsu": True, "dsu_puerto": 0}
        con = v.paginas["Conexión"]
        con.ip.setCurrentText("127.0.0.1")
        con.puerto.setValue(sim.puerto)
        _foto(v, "1_conexion_sin_conectar")
        con.conectar()
        assert _bombear(qt, 5, lambda: v.motor.estado == CONECTADO)
        _bombear(qt, 1.3)
        assert con.datos["slot"].text() == "1"
        assert 35 <= int(con.datos["pps"].text()) <= 65
        assert 22 <= int(con.datos["mps"].text()) <= 40
        assert "Hz" in con.nota_hz.text()
        _foto(v, "1_conexion_conectado")

        v.ir("Control")
        _bombear(qt, 0.2)
        _foto(v, "2_control")

        # --- asistente
        v.ir("Calibración")
        cal = v.paginas["Calibración"]
        assert not v.perfil["calibrado"]
        _foto(v, "3_calibracion_inicio")
        cal.iniciar()
        assert cal.modo == "pasos"
        _robot_ui(qt, sim, cal)
        assert v.perfil["calibrado"] and v.sucio
        assert v.perfil["gyro"]["perm"] == [2, 1, 0] and v.perfil["gyro"]["signo"] == [-1, -1, -1]
        assert v.perfil["stick"]["matriz"] == PF.STICK_LADO
        sim.girar(1, 30, 0.5)
        sim.presionar("F_IZQ")
        _bombear(qt, 0.6)
        _foto(v, "3_calibracion_verificacion")
        sim.soltar()
        assert cal.mov.angulos[1] > 12            # el dibujo siguió el giro a la izquierda
        cal.b_guardar.click()
        assert not v.sucio and PF.listar() == [v.perfil["nombre"]]

        # --- repetir un solo grupo (reposo) sin pasar por lo demás
        cal.repetir("reposo")
        assert cal.modo == "pasos"
        assert _bombear(qt, 8, lambda: cal.modo == "verificar")

        # --- ajustes: reasignar un botón con "clic y presiona"
        v.ir("Ajustes")
        aj = v.paginas["Ajustes"]
        _bombear(qt, 0.3)
        aj.b_map["R2"].click()
        assert aj.escuchando == "R2"
        _bombear(qt, 0.3)
        sim.presionar("SR")
        assert _bombear(qt, 3, lambda: aj.escuchando is None)
        sim.soltar()
        assert v.perfil["mapeo"]["R2"] == "R1"
        aj._mapeo_defecto()
        assert v.perfil["mapeo"]["R2"] == "HOME"
        aj.s_zm[0].setValue(20)
        aj.c_inv[1].setChecked(True)
        assert v.perfil["stick"]["zona_muerta"] == pytest.approx(0.2)
        assert v.perfil["gyro"]["invertir"] == [False, True, False]
        aj.c_inv[1].setChecked(False)
        aj.c_xbox.setChecked(True)
        aj.c_ds4.setChecked(True)
        assert "DOS controles" in aj.aviso_sal.text()
        aj.c_xbox.setChecked(False)
        aj.c_ds4.setChecked(False)
        sim.stick(0.7, 0.7)
        _bombear(qt, 0.4)
        _foto(v, "4_ajustes")
        sim.stick(0, 0)
        v.guardar_perfil()

        # --- perfiles
        v.ir("Perfiles")
        pf = v.paginas["Perfiles"]
        PF.duplicar(v.perfil["nombre"], "Copia de prueba")
        pf.recargar()
        assert pf.lista.count() == 2
        _foto(v, "5_perfiles")

        # --- jugar
        v.ir("Jugar")
        ju = v.paginas["Jugar"]
        ju._alternar()
        assert _bombear(qt, 3, lambda: v.motor.foto().salidas == ["Servidor DSU"])
        sim.presionar("F_ABAJO", "SL")
        sim.stick(0, 1)
        _bombear(qt, 0.5)
        assert ju.bot.text() == "B L1"
        assert ju.stick_w.y > 0.9
        _foto(v, "6_jugar")
        sim.soltar()
        sim.stick(0, 0)
        # se pierde la señal: avisa y sigue intentando
        sim.pausado = True
        _bombear(qt, 1.2)
        assert "neutro" in ju.t_con.text()
        sim.pausado = False
        assert _bombear(qt, 4, lambda: v.motor.estado == CONECTADO)
        nombre = v.perfil["nombre"]
        v.close()

        # --- reabrir: el perfil guardado se usa sin recalibrar
        v2 = Ventana()
        assert v2.perfil["nombre"] == nombre and v2.perfil["calibrado"]
        assert v2.perfil["gyro"]["perm"] == [2, 1, 0]
        assert v2.ajustes["ip"] == "127.0.0.1" and v2.ajustes["puerto"] == sim.puerto
        v2.close()


@pytest.mark.parametrize("control", ["wii-classic", "wii-remote"])
def test_interfaz_con_classic_y_wii_remote(qt, tmp_path, monkeypatch, control):
    """Elegir el control en la página Control, calibrar, ver botones y sticks en Jugar."""
    monkeypatch.setenv("DSU_PAD_DATOS", str(tmp_path))
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: QMessageBox.Ok)
    from app.core import controles as CT
    from app.ui.ventana import Ventana

    corto = control.split("-")[1]
    with SimuladorApp(control=control) as sim:
        v = Ventana()
        v.show()
        v.ir("Control")
        v.paginas["Control"].r_ctrl[control].setChecked(True)
        assert v.perfil["control"] == control
        v.perfil["salidas"] = {"ds4": False, "xbox": False, "dsu": True, "dsu_puerto": 0}
        con = v.paginas["Conexión"]
        con.ip.setCurrentText("127.0.0.1")
        con.puerto.setValue(sim.puerto)
        con.conectar()
        assert _bombear(qt, 5, lambda: v.motor.estado == CONECTADO)
        _bombear(qt, 0.3)
        _foto(v, f"7_{corto}_control")

        v.ir("Calibración")
        cal = v.paginas["Calibración"]
        dos = control == "wii-classic"
        assert cal.filas["stickd"].isVisibleTo(cal) == dos
        assert cal.filas["stick"].isVisibleTo(cal) == dos
        cal.iniciar()
        _robot_ui(qt, sim, cal, prefijo=f"7_{corto}_asistente_")
        assert v.perfil["calibrado"]
        cal.b_guardar.click()

        v.ir("Jugar")
        ju = v.paginas["Jugar"]
        ju._alternar()
        assert _bombear(qt, 3, lambda: v.motor.foto().salidas == ["Servidor DSU"])
        ctrl = CT.control(control)
        b0 = ctrl.botones[0]
        sim.presionar(b0.id)
        if dos:
            sim.stick(0, 1)
            sim.stick(1, 0, "der")
        _bombear(qt, 0.5)
        assert ju.bot.text() == b0.esperado
        assert b0.id in ju.dibujo.presionados
        if dos:
            assert ju.stick_w.y > 0.9
            assert v.motor.foto().logico.rx > 0.9
            assert ju.dibujo.stick_der[0] > 0.9
        _foto(v, f"7_{corto}_jugar")
        sim.soltar()
        sim.stick(0, 0)
        sim.stick(0, 0, "der")
        v.close()
