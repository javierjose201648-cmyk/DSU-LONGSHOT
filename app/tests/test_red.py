"""Pruebas con red local: simulador de la app, cliente, servidor DSU, motor y
el asistente completo con un usuario robot. No necesitan el driver ViGEmBus."""
import math
import time

import pytest

from app.core import perfiles as PF
from app.core import protocolo as P
from app.core.motor import CONECTADO, SIN_DATOS, Motor
from app.core.protocolo import ClienteDSU
from app.core.salidas import ServidorDSU
from app.core.transformar import EstadoLogico, transformar
from app.tests.robot import calibrar_con_robot
from app.tests.simulador import SimuladorApp


def _leer(cliente, segundos):
    fin = time.monotonic() + segundos
    out = []
    while time.monotonic() < fin:
        e = cliente.recibir(0.1)
        if e:
            out.append(e)
    return out


def test_simulador_se_parece_a_la_captura_real():
    with SimuladorApp() as sim:
        c = ClienteDSU("127.0.0.1", sim.puerto)
        _leer(c, 0.5)
        datos = _leer(c, 3.0)
        c.cerrar()
    assert c.slot == 1
    pps = len(datos) / 3.0
    nuevos = len({e.ts_us for e in datos}) / 3.0
    assert 40 <= pps <= 62, pps                 # real: ~54
    assert 26 <= nuevos <= 37, nuevos           # real: ~33
    assert nuevos < pps - 5                     # hay muestras repetidas
    assert all(e.ts_us % 1000 == 0 for e in datos)
    assert all(e.modelo == 2 and e.conexion == 1 for e in datos)
    g = datos[-1].accel
    assert 0.9 < math.sqrt(sum(a * a for a in g)) < 1.1


def test_simulador_botones_y_stick_como_el_telefono():
    with SimuladorApp(stick_usuario=PF.STICK_FISICA) as sim:
        c = ClienteDSU("127.0.0.1", sim.puerto)
        _leer(c, 0.3)
        esperado = {"ZL": ["L2"], "L": ["L1"], "SL": ["L1"], "SR": ["R1"], "MENOS": ["SELECT"],
                    "MAS": ["START"], "VERDE": ["HOME"], "F_ARRIBA": ["ARRIBA"], "STICK": []}
        for fisico, bits in esperado.items():
            sim.soltar()
            sim.presionar(fisico)
            e = _leer(c, 0.15)[-1]
            assert sorted(e.presionados()) == sorted(bits), fisico
        sim.soltar()
        sim.stick(0, 1)                         # vertical: arriba = LY bajo
        e = _leer(c, 0.15)[-1]
        assert e.ly <= 3 and abs(e.lx - 128) < 3
        c.cerrar()


def test_cliente_se_resuscribe_y_el_servidor_olvida():
    """El simulador deja de mandar a los 5 s sin suscripción; el cliente la
    renueva cada segundo, así que los datos no se cortan."""
    with SimuladorApp() as sim:
        c = ClienteDSU("127.0.0.1", sim.puerto)
        datos = _leer(c, 6.5)
        assert len(datos) > 6.5 * 35
        huecos = [b.t_llegada - a.t_llegada for a, b in zip(datos, datos[1:])]
        assert max(huecos) < 0.5
        # Sin renovar: el servidor deja de mandar
        c._solicitar = lambda: None
        _leer(c, 5.6)
        assert _leer(c, 0.6) == []
        c.cerrar()


def test_cliente_descarta_fuera_de_orden_y_otros_slots():
    import socket
    srv = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    srv.bind(("127.0.0.1", 0))
    srv.settimeout(2)
    c = ClienteDSU("127.0.0.1", srv.getsockname()[1])
    c._solicitar()
    _, addr = srv.recvfrom(1024)
    for slot, num in [(1, 10), (1, 12), (1, 11), (0, 13), (1, 12), (1, 13)]:
        srv.sendto(P.construir_datos(slot, num), addr)
    nums = [e.num_paquete for e in _leer(c, 0.4)]
    assert nums == [10, 12, 13]
    srv.close()
    c.cerrar()


def test_servidor_dsu_responde_a_un_cliente_de_prueba():
    import socket
    import struct
    srv = ServidorDSU(0, host="127.0.0.1")
    puerto = srv.sock.getsockname()[1]
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(1)
        s.sendto(P.solicitud_version(), ("127.0.0.1", puerto))
        tipo, datos, _ = P.validar(s.recvfrom(1024)[0])
        assert tipo == P.MSG_VERSION and struct.unpack_from("<H", datos, 20)[0] == 1001
        s.sendto(P.solicitud_info(), ("127.0.0.1", puerto))
        infos = [P.validar(s.recvfrom(1024)[0]) for _ in range(4)]
        estados = {d[20]: d[21] for t, d, _ in infos}
        assert estados == {0: 2, 1: 0, 2: 0, 3: 0}      # solo el slot 0 conectado
        assert all(len(d) == 32 for _, d, _ in infos)
        s.close()

        c = ClienteDSU("127.0.0.1", puerto)
        c._solicitar()
        time.sleep(0.3)
        assert len(srv.clientes()) == 1
        log = EstadoLogico()
        log.botones = {"A": True, "L1": True, "HOME": True}
        log.lx, log.ly, log.l2 = 0.5, 1.0, 200
        log.gyro, log.accel = (10.0, 20.0, 30.0), (0.1, 0.9, 0.2)
        ts = []
        for _ in range(5):
            srv.actualizar(log)
            time.sleep(0.01)
        recibidos = _leer(c, 0.3)
        assert len(recibidos) == 5
        e = recibidos[-1]
        assert e.slot == 0 and sorted(e.presionados()) == ["A", "HOME", "L1", "L2"]
        assert e.ly == 255 and 190 <= e.lx <= 193          # DSU: Y = 255 arriba
        assert e.l2_analog == 200
        assert e.gyro == pytest.approx((10.0, -20.0, -30.0))   # convención Dolphin
        assert e.accel == pytest.approx((-0.1, -0.9, -0.2))
        ts = [x.ts_us for x in recibidos]
        assert all(b > a for a, b in zip(ts, ts[1:]))       # el timestamp siempre avanza
        nums = [x.num_paquete for x in recibidos]
        assert nums == sorted(set(nums))
        c.cerrar()
    finally:
        srv.cerrar()


def test_servidor_dsu_registro_por_slot_como_dolphin():
    """Dolphin se registra con flags=1 (por slot). Solo el slot 0 recibe datos."""
    import socket
    import struct
    srv = ServidorDSU(0, host="127.0.0.1")
    puerto = srv.sock.getsockname()[1]
    try:
        for slot, espera in [(0, 1), (2, 0)]:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.sendto(P.paquete_cliente(P.MSG_DATOS, struct.pack("<BB6s", 1, slot, b"\0" * 6)),
                     ("127.0.0.1", puerto))
            time.sleep(0.3)
            assert len(srv.clientes()) == espera
            s.close()
            srv._clientes.clear()
    finally:
        srv.cerrar()


def test_motor_estadisticas_neutro_y_reconexion():
    perfil = PF.perfil_por_defecto("lado")
    perfil["salidas"] = {"ds4": False, "xbox": False, "dsu": True, "dsu_puerto": 0}
    with SimuladorApp() as sim:
        m = Motor()
        m.conectar("127.0.0.1", sim.puerto, perfil)
        m.jugar(True)
        try:
            time.sleep(2.0)
            f = m.foto()
            assert f.estado == CONECTADO and f.slot == 1
            assert 40 <= f.pps <= 62 and 26 <= f.mps <= 37
            assert f.salidas == ["Servidor DSU"] and not f.error_salida
            sim.presionar("F_IZQ")
            sim.stick(0, 1)
            time.sleep(0.3)
            f = m.foto()
            assert f.logico.presionados() == ["A"] and f.logico.ly > 0.9
            # La app "se cierra": el motor avisa y pone neutro a los 2 s
            puerto_dsu = m._servidor.sock.getsockname()[1]
            lector = ClienteDSU("127.0.0.1", puerto_dsu)
            _leer(lector, 0.4)
            sim.pausado = True
            time.sleep(1.0)
            assert m.foto().estado == SIN_DATOS
            ultimo = _leer(lector, 2.2)[-1]
            assert ultimo.presionados() == [] and ultimo.lx == 128 and ultimo.ly == 128
            # Vuelve sola al reaparecer la app
            sim.pausado = False
            time.sleep(1.6)
            assert m.foto().estado == CONECTADO
            lector.cerrar()
        finally:
            m.detener()


CONFIGS = {
    "lado-como-el-telefono": dict(),
    "lado-ejes-permutados-rad-ms2": dict(ejes_app=[(1, 1), (2, -1), (0, 1)], gyro_en_rad=True,
                                         accel_en_ms2=True, ruido=1.0),
    "lado-girado-a-la-derecha": dict(stick_usuario=[[0, -1], [-1, 0]],
                                     ejes_app=[(2, 1), (1, -1), (0, 1)]),
    "fisica-vertical": dict(stick_usuario=PF.STICK_FISICA, ejes_app=[(0, 1), (2, 1), (1, -1)],
                            accel_invertido=True),
}


@pytest.mark.parametrize("nombre", list(CONFIGS))
def test_asistente_de_punta_a_punta_con_usuario_robot(nombre):
    cfg = CONFIGS[nombre]
    orientacion = "fisica" if nombre.startswith("fisica") else "lado"
    with SimuladorApp(**cfg) as sim:
        base = PF.perfil_por_defecto(orientacion)
        # Empezar con ejes equivocados a propósito: el asistente debe corregirlos
        base["gyro"].update(perm=[0, 1, 2], signo=[1, 1, 1])
        base["stick"]["matriz"] = [[1, 0], [0, 1]]
        asis, perfil = calibrar_con_robot(sim, base)
        assert perfil["calibrado"] and not asis.error

        # --- ejes del gyro: los que realmente usa el "teléfono"
        ejes = cfg.get("ejes_app", [(2, -1), (1, -1), (0, -1)])
        perm_real = [None] * 3
        signo_real = [None] * 3
        for i_app, (i_std, s) in enumerate(ejes):
            perm_real[i_std], signo_real[i_std] = i_app, s
        assert perfil["gyro"]["perm"] == perm_real
        assert perfil["gyro"]["signo"] == signo_real
        escala = perfil["gyro"]["escala"]
        assert escala == pytest.approx(57.2958 if cfg.get("gyro_en_rad") else 1.0, rel=1e-3)
        assert perfil["accel"]["escala"] == pytest.approx(1 / 9.81 if cfg.get("accel_en_ms2") else 1.0)
        assert perfil["accel"]["signo"] == (-1 if cfg.get("accel_invertido") else 1)

        # --- ya calibrado: lo que sale es lo que hace el usuario
        c = ClienteDSU("127.0.0.1", sim.puerto)
        _leer(c, 0.3)
        sim.stick(0, 1)
        log = transformar(_leer(c, 0.2)[-1], perfil)
        assert log.ly > 0.95 and abs(log.lx) < 0.05
        sim.stick(1, 0)
        log = transformar(_leer(c, 0.2)[-1], perfil)
        assert log.lx > 0.95 and abs(log.ly) < 0.05
        sim.stick(0, 0)
        log = transformar(_leer(c, 0.3)[-1], perfil)
        assert log.accel[1] > 0.9 and abs(log.accel[0]) < 0.15 and abs(log.accel[2]) < 0.15
        for eje in range(3):
            sim.girar(eje, 60, 0.6)                # 100 °/s
            _leer(c, 0.15)                         # (leer en vez de dormir: vacía el buffer)
            muestras = [transformar(e, perfil).gyro for e in _leer(c, 0.3)]
            media = [sum(m[i] for m in muestras) / len(muestras) for i in range(3)]
            assert media[eje] == pytest.approx(100, abs=12), (eje, media)
            assert all(abs(media[i]) < 12 for i in range(3) if i != eje), (eje, media)
            _leer(c, 0.3)
            sim.girar(eje, -60, 0.6)
            _leer(c, 0.8)

        # --- botones
        if orientacion == "lado":
            esperado = {"SL": "L1", "SR": "R1", "ZL": "L2", "VERDE": "R2",
                        "MENOS": "SELECT", "MAS": "START"}
            if nombre == "lado-girado-a-la-derecha":
                esperado.update(F_ARRIBA="B", F_DER="A", F_ABAJO="X", F_IZQ="Y")
            else:
                esperado.update(F_ARRIBA="X", F_DER="Y", F_ABAJO="B", F_IZQ="A")
        else:
            esperado = {"SL": "L1", "SR": "R1", "ZL": "L2", "VERDE": "HOME", "MENOS": "SELECT",
                        "MAS": "START", "F_ARRIBA": "ARRIBA", "F_DER": "DER",
                        "F_ABAJO": "ABAJO", "F_IZQ": "IZQ"}
        for fisico, salida in esperado.items():
            sim.soltar()
            sim.presionar(fisico)
            log = transformar(_leer(c, 0.15)[-1], perfil)
            assert log.presionados() == [salida], fisico
        sim.soltar()
        c.cerrar()


def test_asistente_no_avanza_si_el_giro_es_corto():
    """El problema real: el usuario no giró lo suficiente. El paso NO se completa."""
    from app.core.calibracion import Asistente
    with SimuladorApp() as sim:
        c = ClienteDSU("127.0.0.1", sim.puerto)
        asis = Asistente(PF.perfil_por_defecto("lado"))
        asis.ir_a("gesto:pitch", unico=False)
        sim.girar(0, 15, 0.5)                      # solo 15°
        fin = time.monotonic() + 2.5
        while time.monotonic() < fin:
            e = c.recibir(0.2)
            if e:
                asis.alimentar(e)
        assert asis.paso.id == "gesto:pitch" and asis.paso.estado == "esperando"
        assert 0.2 < asis.paso.info["avance"] < 0.6        # la UI muestra el avance real
        sim.girar(0, 35, 0.6)                      # completa hasta ~50°
        fin = time.monotonic() + 3
        while time.monotonic() < fin and asis.paso.estado == "esperando":
            e = c.recibir(0.2)
            if e:
                asis.alimentar(e)
        assert asis.paso.estado == "presionado" and asis.paso.info["fase"] == "regresar"
        c.cerrar()


def test_asistente_boton_inesperado_y_repetir_un_paso():
    from app.core.calibracion import Asistente
    with SimuladorApp() as sim:
        c = ClienteDSU("127.0.0.1", sim.puerto)

        def correr(asis, segundos, hasta=None):
            fin = time.monotonic() + segundos
            while time.monotonic() < fin and not (hasta and hasta()):
                e = c.recibir(0.2)
                if e:
                    asis.alimentar(e)

        asis = Asistente(PF.perfil_por_defecto("lado"))
        assert asis.paso.id == "boton:ZL"
        correr(asis, 0.3)
        sim.presionar("SR")                         # botón equivocado
        correr(asis, 0.4)
        assert asis.paso.id == "boton:ZL" and asis.paso.info["inesperado"] == "R1"
        assert "SR" in asis.paso.aviso
        asis.aceptar_inesperado()                   # "sí era ese": se reasigna
        assert asis.paso.id == "boton:SL"
        sim.soltar()
        asis._unico = False
        for p in asis.pasos:                        # omitir todo lo demás
            if not asis.terminado:
                asis.omitir()
        perfil = asis.aplicar(PF.perfil_por_defecto("lado"))
        assert perfil["mapeo"]["L2"] == "R1"        # ZL quedó ligado al bit que llegó

        # Repetir SOLO el reposo: termina sin pasar por los gestos
        asis.ir_a("reposo")
        correr(asis, 5, hasta=lambda: asis.terminado)
        assert asis.terminado
        perfil = asis.aplicar(perfil)
        assert perfil["gyro"]["bias"] == pytest.approx([0.8, 0.6, 0.1], abs=0.8)
        assert 1.0 < perfil["gyro"]["ruido"] < 5.0
        c.cerrar()
