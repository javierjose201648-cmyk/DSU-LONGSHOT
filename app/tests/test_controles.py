"""Wii Classic y Wii Remote: perfiles, asistente con usuario robot y salida lógica.

Probado con SIMULADOR (bits según los perfiles oficiales de Dolphin de la app),
no con el teléfono real.
"""
import time

import pytest

from app.core import calibracion as C
from app.core import controles as CT
from app.core import perfiles as PF
from app.core import protocolo as P
from app.core.protocolo import ClienteDSU
from app.core.transformar import transformar
from app.tests.robot import calibrar_con_robot
from app.tests.simulador import EJES_FISICA, EJES_LADO, SimuladorApp


def _leer(c, seg):
    fin, out = time.monotonic() + seg, []
    while time.monotonic() < fin:
        e = c.recibir(0.05)
        if e:
            out.append(e)
    return out


def _estado(botones=(), **kw):
    return P.parsear_paquete(P.construir_datos(1, 1, botones, **kw))


def test_perfiles_por_defecto_de_cada_control():
    cl = PF.perfil_por_defecto(control="wii-classic")
    assert cl["control"] == "wii-classic" and cl["orientacion"] == "lado"
    # a = ○ (Switch A), b = ✕, x = △, y = □, AL/AR = L3/R3: como el perfil de Dolphin
    assert cl["fisicos"]["C_A"] == "B" and cl["fisicos"]["C_B"] == "A"
    assert cl["fisicos"]["AL"] == "L3" and cl["fisicos"]["AR"] == "R3"
    assert cl["mapeo"]["B"] == "B" and cl["mapeo"]["L3"] == "L3" and cl["mapeo"]["R2"] == "R2"
    assert len(cl["mapeo"]) == 17
    wr = PF.perfil_por_defecto(control="wii-remote")
    assert wr["orientacion"] == "fisica"
    assert wr["fisicos"] == {"W_A": "A", "W_B": "X", "UNO": "Y", "DOS": "B", "MENOS": "SELECT",
                             "HOME": "HOME", "MAS": "START", "D_ARRIBA": "ARRIBA", "D_DER": "DER",
                             "D_ABAJO": "ABAJO", "D_IZQ": "IZQ"}
    # Un perfil 1.0.0 (sin "control" ni "fisicos") sigue siendo Joy-Con
    viejo = PF.perfil_por_defecto("lado")
    del viejo["control"], viejo["fisicos"], viejo["stick_der"]
    m = PF.migrar(viejo)
    assert m["control"] == "joycon-izq" and m["mapeo"] == PF.MAPEO_LADO_LONGSHOT


def test_perfil_classic_ida_y_vuelta(tmp_path, monkeypatch):
    monkeypatch.setenv("DSU_LONGSHOT_DATOS", str(tmp_path))
    p = PF.perfil_por_defecto(nombre="Classic", control="wii-classic")
    p["fisicos"]["C_A"] = "IZQ"
    p["orientacion"] = "fisica"             # no válida para el Classic: se corrige
    PF.guardar(p)
    q = PF.cargar("Classic")
    assert q["control"] == "wii-classic" and q["orientacion"] == "lado"
    assert q["fisicos"]["C_A"] == "IZQ"


def test_classic_stick_derecho_llega_al_estado_logico():
    p = PF.perfil_por_defecto(control="wii-classic")
    log = transformar(_estado(["B", "R3"], lx=128, ly=254, rx=254, ry=128), p)
    assert log.botones["B"] and log.botones["R3"]
    assert log.ly > 0.95 and log.rx > 0.95 and abs(log.ry) < 0.05
    # El Joy-Con no tiene stick derecho: rx/ry de la app se ignoran
    log = transformar(_estado(rx=254), PF.perfil_por_defecto("lado"))
    assert log.rx == 0


@pytest.mark.parametrize("control,ejes", [("wii-classic", EJES_LADO), ("wii-remote", EJES_FISICA)])
def test_asistente_con_robot(control, ejes):
    with SimuladorApp(control=control) as sim:
        base = PF.perfil_por_defecto(control=control)
        base["gyro"].update(perm=[0, 1, 2], signo=[1, 1, 1])
        base["stick"]["matriz"] = [[0, 1], [1, 0]]          # equivocada a propósito
        base["stick_der"]["matriz"] = [[-1, 0], [0, -1]]
        asis, perfil = calibrar_con_robot(sim, base)
        assert perfil["calibrado"] and not asis.error
        ctrl = CT.control(control)
        n_sticks = len(ctrl.sticks)
        assert len([x for x in asis.pasos if x.tipo == "stick_dir"]) == 2 * n_sticks
        perm_real, signo_real = [None] * 3, [None] * 3
        for i_app, (i_std, s) in enumerate(ejes):
            perm_real[i_std], signo_real[i_std] = i_app, s
        assert perfil["gyro"]["perm"] == perm_real and perfil["gyro"]["signo"] == signo_real
        assert perfil["mapeo"] == C.mapeo_recomendado(PF.perfil_por_defecto(control=control))

        c = ClienteDSU("127.0.0.1", sim.puerto)
        try:
            _leer(c, 0.3)
            if n_sticks == 2:
                assert perfil["stick"]["matriz"] == [[1, 0], [0, 1]]
                assert perfil["stick_der"]["matriz"] == [[1, 0], [0, 1]]
                sim.stick(0, 1)
                sim.stick(1, 0, "der")
                log = transformar(_leer(c, 0.2)[-1], perfil)
                assert log.ly > 0.95 and abs(log.lx) < 0.05
                assert log.rx > 0.95 and abs(log.ry) < 0.05
                sim.stick(0, 0)
                sim.stick(0, 0, "der")
            primero = ctrl.botones[0]
            sim.presionar(primero.id)
            log = transformar(_leer(c, 0.2)[-1], perfil)
            assert log.presionados() == [primero.esperado]
            sim.soltar()
        finally:
            c.cerrar()


def test_asistente_aprende_un_bit_distinto_al_esperado():
    """Si la app manda la cruceta del Classic rotada, el asistente lo aprende."""
    perfil = PF.perfil_por_defecto(control="wii-classic")
    asis = C.Asistente(perfil)
    asis.alimentar(_estado())
    assert asis.paso.id == "boton:C_A"
    asis.alimentar(_estado(["IZQ"]))           # llegó otra cosa
    assert asis.paso.info.get("inesperado") == "IZQ"
    assert "Cruceta ←" in asis.paso.aviso
    asis.aceptar_inesperado()
    assert asis.paso.id == "boton:C_B"
    # terminar sin más cambios
    while not asis.terminado:
        asis.omitir()
    nuevo = asis.aplicar(perfil)
    assert nuevo["fisicos"]["C_A"] == "IZQ"
    assert nuevo["mapeo"]["B"] == "IZQ"         # el botón a sigue saliendo como ○
