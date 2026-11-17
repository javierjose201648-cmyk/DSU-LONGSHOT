"""Pruebas del núcleo que no necesitan red ni driver."""
import json
import math
import os

import pytest

from app.core import calibracion as C
from app.core import perfiles as PF
from app.core import protocolo as P
from app.core import salidas as S
from app.core.transformar import EstadoLogico, GyroStick, stick_logico, transformar

REF = os.path.join(os.path.dirname(__file__), "..", "..", "referencia")


@pytest.fixture(scope="module")
def captura():
    with open(os.path.join(REF, "captura_joycon-izq.json"), encoding="utf-8") as f:
        return json.load(f)


# ------------------------------------------------------------- protocolo
def test_parser_con_paquete_real_del_telefono(captura):
    crudo = bytes.fromhex(captura["reposo"]["primer_paquete_hex"])
    e = P.parsear_paquete(crudo)
    assert e is not None
    assert e.slot == 1 and e.modelo == 2 and e.conexion == 1
    assert (e.lx, e.ly) == (128, 128)
    assert not any(e.fuente.values())
    mag = math.sqrt(sum(a * a for a in e.accel))
    assert 0.9 < mag < 1.1            # g en reposo
    assert e.ts_us % 1000 == 0        # resolución de 1 ms


def test_crc_invalido_se_descarta(captura):
    crudo = bytearray.fromhex(captura["reposo"]["primer_paquete_hex"])
    crudo[90] ^= 0xFF
    assert P.parsear_paquete(bytes(crudo)) is None
    assert P.parsear_paquete(b"basura") is None
    assert P.parsear_paquete(b"DSUS" + b"\0" * 10) is None


def test_respuestas_reales_de_version_e_info(captura):
    for tipo, hexa in captura["otros_mensajes"].items():
        r = P.validar(bytes.fromhex(hexa))
        assert r is not None and hex(r[0]) == tipo


def test_construir_y_parsear_ida_y_vuelta():
    for boton in P.BOTONES:
        pk = P.construir_datos(1, 7, [boton], lx=10, ly=250, ts_us=123456000,
                               accel=(0.1, -0.9, 0.2), gyro=(1.5, -2.5, 3.5))
        assert len(pk) == 100
        e = P.parsear_paquete(pk)
        assert e.presionados() == [boton], boton
        assert (e.lx, e.ly, e.num_paquete, e.ts_us) == (10, 250, 7, 123456000)
        assert e.gyro == pytest.approx((1.5, -2.5, 3.5))
        assert e.accel == pytest.approx((0.1, -0.9, 0.2))


def test_paquete_de_slot_desconectado_se_ignora():
    pk = bytearray(P.construir_datos(1, 1))
    pk[31] = 0
    # recalcular CRC
    import struct
    import zlib
    pk[8:12] = b"\0\0\0\0"
    pk[8:12] = struct.pack("<I", zlib.crc32(bytes(pk)) & 0xFFFFFFFF)
    assert P.validar(bytes(pk)) is not None
    assert P.parsear_paquete(bytes(pk)) is None


def test_solicitudes_del_cliente_son_validas():
    for pk in (P.solicitud_datos(), P.solicitud_info(), P.solicitud_version()):
        assert P.validar(pk, b"DSUC") is not None
    assert P.validar(P.solicitud_datos()) is None      # magia de servidor


# ------------------------------------------------------------ calibración
def _angulos(perm, signo, escala=1.0, grados=45.0, cruce=0.0):
    """Lo que integraría la app para los 3 gestos con ejes permutados."""
    out = {}
    for i, eje in enumerate(("pitch", "yaw", "roll")):
        a = [cruce * grados / escala] * 3
        a[perm[i]] = signo[i] * grados / escala
        out[eje] = a
    return out


@pytest.mark.parametrize("perm", [[0, 1, 2], [2, 1, 0], [1, 2, 0], [2, 0, 1], [0, 2, 1], [1, 0, 2]])
@pytest.mark.parametrize("signo", [[1, 1, 1], [-1, -1, -1], [1, -1, 1], [-1, 1, -1]])
def test_deducir_ejes_permutados(perm, signo):
    p, s, escala, grados = C.deducir_ejes(_angulos(perm, signo, cruce=0.1))
    assert p == perm and s == signo and escala == 1.0
    assert all(abs(g - 45) < 1 for g in grados)


def test_deducir_ejes_en_radianes():
    rad = 180 / math.pi
    p, s, escala, grados = C.deducir_ejes(_angulos([2, 0, 1], [-1, 1, -1], escala=rad))
    assert p == [2, 0, 1] and s == [-1, 1, -1]
    assert escala == pytest.approx(rad)
    assert all(abs(g - 45) < 1 for g in grados)


def test_deducir_ejes_rechaza_gestos_malos():
    with pytest.raises(ValueError, match="muy pequeño"):
        C.deducir_ejes(_angulos([0, 1, 2], [1, 1, 1], grados=8))
    with pytest.raises(ValueError, match="mismo eje"):
        C.deducir_ejes({"pitch": [45, 0, 0], "yaw": [40, 0, 0], "roll": [0, 0, 45]})
    with pytest.raises(ValueError, match="varios ejes"):
        C.deducir_ejes({"pitch": [30, 30, 0], "yaw": [0, 45, 0], "roll": [0, 0, 45]})


def test_deducir_stick_y_remapeo_de_lado():
    # Teléfono girado a la izquierda: arriba del usuario = +X crudo, derecha = +Y crudo
    m = C.deducir_stick((0.98, 0.1), (0.05, 0.97))
    assert m == PF.STICK_LADO
    r = C.remapeo_joycon(m, "lado")
    # Brief §3.3: △→X, ▷→Y, ▽→B, ◁→A
    assert r == {"X": "ARRIBA", "Y": "DER", "B": "ABAJO", "A": "IZQ"}
    assert {k: PF.MAPEO_LADO_LONGSHOT[k] for k in "ABXY"} == r


def test_remapeo_de_lado_girado_a_la_derecha():
    # Girado al otro lado: arriba del usuario = -X crudo, derecha = -Y crudo
    m = C.deducir_stick((-0.99, 0.0), (0.0, -0.99))
    r = C.remapeo_joycon(m, "lado")
    assert r == {"B": "ARRIBA", "A": "DER", "X": "ABAJO", "Y": "IZQ"}


def test_deducir_stick_y_remapeo_fisico():
    # Teléfono vertical (verificado en la captura): arriba = LY bajo, derecha = LX alto
    m = C.deducir_stick((0.1, -1.0), (0.99, 0.1))
    assert m == PF.STICK_FISICA
    assert C.remapeo_joycon(m, "fisica") == {f: f for f in ("ARRIBA", "ABAJO", "IZQ", "DER")}


def test_stick_de_la_captura_real(captura):
    """Los valores reales del stick (teléfono vertical) dan arriba y derecha."""
    cfg = PF.perfil_por_defecto("fisica")["stick"]
    x, y = stick_logico(143, 1, cfg)       # "Stick hacia ARRIBA": LX≈143, LY=1
    assert y > 0.95 and abs(x) < 0.25
    x, y = stick_logico(254, 140, cfg)     # "Stick a la DERECHA": LX=254
    assert x > 0.95 and abs(y) < 0.2


def test_deducir_stick_rechaza_diagonal_y_corto():
    with pytest.raises(ValueError):
        C.deducir_stick((0.7, 0.7), (0.0, 1.0))
    with pytest.raises(ValueError):
        C.deducir_stick((0.2, 0.0), (0.0, 1.0))
    with pytest.raises(ValueError):
        C.deducir_stick((1.0, 0.0), (-1.0, 0.0))


def test_timestamp_repetido_aporta_dt_cero():
    a = P.parsear_paquete(P.construir_datos(1, 1, ts_us=1000000, gyro=(100, 0, 0)))
    b = P.parsear_paquete(P.construir_datos(1, 2, ts_us=1000000, gyro=(100, 0, 0)))
    c = P.parsear_paquete(P.construir_datos(1, 3, ts_us=1030000, gyro=(100, 0, 0)))
    assert C.dt_entre(a, b) == 0.0
    assert C.dt_entre(b, c) == pytest.approx(0.03)
    assert C.integrar_gesto([a, b, c], [0, 0, 0])[0] == pytest.approx(3.0)


# ------------------------------------------------------------ transformar
def _estado(botones=(), lx=128, ly=128, gyro=(0, 0, 0), accel=(0, 0, 0)):
    return P.parsear_paquete(P.construir_datos(1, 1, botones, lx=lx, ly=ly, gyro=gyro,
                                               accel=accel, ts_us=1000))


def test_mapeo_por_defecto_de_lado_para_longshot():
    perfil = PF.perfil_por_defecto("lado")
    casos = {  # bit que manda la app -> salida DS4
        "IZQ": "A", "ABAJO": "B", "ARRIBA": "X", "DER": "Y", "L1": "L1", "R1": "R1",
        "L2": "L2", "HOME": "R2", "SELECT": "SELECT", "START": "START",
    }
    for fuente, salida in casos.items():
        log = transformar(_estado([fuente]), perfil)
        assert log.presionados() == [salida], fuente
    log = transformar(_estado(["L2"]), perfil)
    assert log.l2 == 255 and log.r2 == 0
    log = transformar(_estado(["HOME"]), perfil)
    assert log.r2 == 255 and log.l2 == 0


def test_stick_de_lado_y_zona_muerta():
    perfil = PF.perfil_por_defecto("lado")
    log = transformar(_estado(lx=254, ly=128), perfil)     # +X crudo = arriba del usuario
    assert log.ly == pytest.approx(1.0) and log.lx == 0
    log = transformar(_estado(lx=128, ly=254), perfil)     # +Y crudo = derecha
    assert log.lx == pytest.approx(1.0) and log.ly == 0
    log = transformar(_estado(lx=133, ly=125), perfil)     # dentro de la zona muerta
    assert (log.lx, log.ly) == (0.0, 0.0)


def test_movimiento_de_lado_usa_las_mediciones_reales(captura):
    """En reposo, sostenido 'horizontal', la gravedad real queda en +Y estándar."""
    perfil = PF.perfil_por_defecto("lado")
    d = captura["reposo"]["decodificado"]
    log = transformar(_estado(gyro=d["gyro"], accel=d["accel"]), perfil)
    assert log.accel[1] > 0.85
    # El gesto real de "inclinar a la izquierda" giró -app0 => +roll
    log = transformar(_estado(gyro=(-50, 0, 0)), perfil)
    assert log.gyro[2] == pytest.approx(50)


def test_gyro_bias_escala_sensibilidad_e_inversion():
    perfil = PF.perfil_por_defecto("lado")
    perfil["gyro"].update(perm=[1, 2, 0], signo=[1, -1, 1], escala=2.0, bias=[1.0, 2.0, 3.0],
                          sensibilidad=1.5, invertir=[False, True, False])
    log = transformar(_estado(gyro=(11, 12, 13), accel=(0.1, 0.2, 0.3)), perfil)
    assert log.gyro == pytest.approx((10 * 2 * 1.5, 10 * 2 * 1.5, 10 * 2 * 1.5))
    assert log.accel == pytest.approx((0.2, -0.3, 0.1))


def test_gyro_stick():
    gs = GyroStick({"max_dps": 100, "zona_muerta": 5})
    assert gs((0, 3, 0)) == (0.0, 0.0)
    x, y = gs((55, 105, 0))            # apuntar arriba e izquierda
    assert x == pytest.approx(-1.0) and y == pytest.approx(0.5)


# ----------------------------------------------------------------- salidas
def test_conversion_ds4_ida_y_vuelta():
    """Lo que leería el driver (con la calibración del DS4 virtual) ≈ lo que entró."""
    log = EstadoLogico()
    for gyro, accel in [((0, 0, 0), (0, 1, 0)), ((123.4, -250.0, 37.5), (0.3, 0.8, -0.5)),
                        ((-1900, 1900, 5), (-2.0, 3.5, 1.0)), ((0.2, -0.2, 0.1), (0, 0, 1))]:
        log.gyro, log.accel = gyro, accel
        v = S.reporte_ds4_valores(log)
        for i in range(3):
            assert S.calibrado_ds4(v["gyro"][i], 1024, S._DS4_GYRO_CAL[i]) == pytest.approx(gyro[i], abs=0.05)
            assert S.calibrado_ds4(v["accel"][i], 8192, S._DS4_ACCEL_CAL[i]) == pytest.approx(accel[i], abs=0.001)


def test_reporte_ds4_botones_sticks_y_gatillos():
    log = EstadoLogico()
    log.botones = {"A": True, "ARRIBA": True, "DER": True, "HOME": True}
    log.lx, log.ly, log.l2 = 1.0, 1.0, 255
    v = S.reporte_ds4_valores(log)
    assert v["botones"] == ["A"] and v["hat"] == 1 and v["ps"] and v["l2_dig"] and not v["r2_dig"]
    assert v["lx"] == 255 and v["ly"] == 0          # DS4: Y = 0 arriba
    assert S.reporte_ds4_valores(EstadoLogico())["hat"] == 8


def test_gyro_satura_sin_desbordar():
    log = EstadoLogico()
    log.gyro = (99999, -99999, 0)
    v = S.reporte_ds4_valores(log)
    assert v["gyro"][0] == 32767 and v["gyro"][1] == -32768


# ---------------------------------------------------------------- perfiles
def test_carga_de_calibracion_vieja_v1(tmp_path, monkeypatch):
    monkeypatch.setenv("DSU_LONGSHOT_DATOS", str(tmp_path))
    p = PF.cargar_archivo(os.path.join(REF, "calibracion.json"))
    assert p["version"] == PF.VERSION_ESQUEMA and p["calibrado"]
    assert p["slot"] == 1
    assert p["gyro"]["perm"] == [2, 1, 0] and p["gyro"]["signo"] == [-1, -1, -1]
    assert p["gyro"]["bias"][0] == pytest.approx(0.3319, abs=1e-3)
    assert p["mapeo"]["A"] == "ABAJO" and p["mapeo"]["Y"] == "ARRIBA"
    # v1 tenía ly invertido: stick arriba (LY bajo) debe dar y positiva
    x, y = stick_logico(128, 1, p["stick"])
    assert y > 0.9
    # y debe poder transformarse sin errores
    transformar(_estado(["ABAJO"]), p)


def test_perfil_ida_y_vuelta_y_gestion(tmp_path, monkeypatch):
    monkeypatch.setenv("DSU_LONGSHOT_DATOS", str(tmp_path))
    p = PF.perfil_por_defecto("lado", "Mi perfil: prueba/1")
    p["gyro"]["bias"] = [0.1, 0.2, 0.3]
    PF.guardar(p)
    assert PF.listar() == ["Mi perfil: prueba/1"]
    assert PF.cargar("Mi perfil: prueba/1") == p
    PF.duplicar("Mi perfil: prueba/1", "Copia")
    PF.renombrar("Copia", "Otro")
    assert sorted(PF.listar()) == ["Mi perfil: prueba/1", "Otro"]
    PF.borrar("Otro")
    assert PF.listar() == ["Mi perfil: prueba/1"]


def test_perfil_v2_incompleto_se_rellena_y_futuro_se_rechaza():
    p = PF.migrar({"version": 2, "nombre": "x", "orientacion": "lado", "stick": {"zona_muerta": 0.2}})
    assert p["stick"]["zona_muerta"] == 0.2 and p["stick"]["matriz"] == PF.STICK_LADO
    assert p["gyro"]["perm"] == [2, 1, 0] and p["salidas"]["ds4"]
    with pytest.raises(ValueError, match="más nueva"):
        PF.migrar({"version": 99})
    with pytest.raises(ValueError):
        PF.migrar({"cualquier": "cosa"})
    with pytest.raises(ValueError):
        PF.migrar([1, 2, 3])


def test_perfil_corrupto_se_sanea():
    p = PF.migrar({"version": 2, "gyro": {"perm": [0, 0, 1], "signo": [5, 1, 1]},
                   "mapeo": {"A": "NOEXISTE", "B": "ABAJO"}})
    assert p["gyro"]["perm"] == [0, 1, 2] and p["gyro"]["signo"] == [1, 1, 1]
    assert p["mapeo"] == {"B": "ABAJO"}
