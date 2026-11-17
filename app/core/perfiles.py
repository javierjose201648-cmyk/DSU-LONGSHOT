"""Perfiles: esquema versionado, valores por defecto, migración y archivos.

Un perfil guarda TODO lo necesario para jugar sin recalibrar: slot, orientación,
stick, mapeo de botones, ejes del giroscopio y salidas activas.
"""
import copy
import json
import os
import re

from app.i18n import L

VERSION_ESQUEMA = 2

# Salidas lógicas (lo que ve el juego). Letras por POSICIÓN estilo Xbox/DS4:
# A = abajo (✕), B = derecha (○), X = izquierda (□), Y = arriba (△).
SALIDAS = ["A", "B", "X", "Y", "L1", "R1", "L2", "R2", "SELECT", "START",
           "L3", "R3", "ARRIBA", "ABAJO", "IZQ", "DER", "HOME", "TOUCH"]

DESCRIPCION_SALIDA = {
    "A": L("✕ / abajo  (Switch: B)", "✕ / bottom  (Switch: B)"),
    "B": L("○ / derecha  (Switch: A)", "○ / right  (Switch: A)"),
    "X": L("□ / izquierda  (Switch: Y)", "□ / left  (Switch: Y)"),
    "Y": L("△ / arriba  (Switch: X)", "△ / top  (Switch: X)"),
    "L1": "L1  (Switch: L)",
    "R1": "R1  (Switch: R)",
    "L2": "L2  (Switch: ZL)",
    "R2": "R2  (Switch: ZR)",
    "SELECT": "Share  (Switch: −)",
    "START": "Options  (Switch: +)",
    "L3": L("L3 (clic stick izq.)", "L3 (left stick click)"),
    "R3": L("R3 (clic stick der.)", "R3 (right stick click)"),
    "ARRIBA": L("Cruceta ↑", "D-pad ↑"),
    "ABAJO": L("Cruceta ↓", "D-pad ↓"),
    "IZQ": L("Cruceta ←", "D-pad ←"),
    "DER": L("Cruceta →", "D-pad →"),
    "HOME": "PS / Home",
    "TOUCH": L("Clic del touchpad", "Touchpad click"),
}

# Botones físicos de la app DSU Controller en modo Joy-Con izquierdo y el bit
# del protocolo con el que llegan (verificado con captura_joycon-izq.json).
FISICOS_JOYCON_IZQ = {
    "ZL": "L2", "L": "L1", "SL": "L1", "SR": "R1", "MENOS": "SELECT", "MAS": "START",
    "VERDE": "HOME", "F_ARRIBA": "ARRIBA", "F_ABAJO": "ABAJO", "F_IZQ": "IZQ", "F_DER": "DER",
}
NOMBRE_FUENTE_JOYCON = {
    "L2": "ZL", "L1": "SL / L", "R1": "SR", "SELECT": "−", "START": "+", "HOME": "Ícono verde",
    "ARRIBA": "Flecha △", "ABAJO": "Flecha ▽", "IZQ": "Flecha ◁", "DER": "Flecha ▷",
}

from .controles import (GYRO_FISICA, GYRO_LADO, STICK_ESTANDAR, STICK_FISICA,  # noqa: E402,F401
                        STICK_LADO, control as _control, mapeo_generico, stick_por_defecto)

# Mapeo por defecto "de lado" pensado para Longshot (ver docs/DECISIONES.md):
# las 4 flechas son los 4 botones de cara por POSICIÓN, SL/SR = L/R, ZL = ZL
# y el ícono verde hace de ZR, para cubrir los 10 botones de un control de Switch.
MAPEO_LADO_LONGSHOT = {
    "A": "IZQ",        # flecha que queda ABAJO de lado  -> ✕ (Switch B)
    "B": "ABAJO",      # flecha que queda a la DERECHA   -> ○ (Switch A)
    "X": "ARRIBA",     # flecha que queda a la IZQUIERDA -> □ (Switch Y)
    "Y": "DER",        # flecha que queda ARRIBA         -> △ (Switch X)
    "L1": "L1", "R1": "R1", "L2": "L2", "R2": "HOME",
    "SELECT": "SELECT", "START": "START",
}
# Orientación física: todo pasa tal cual (el emulador de Switch rota solo).
MAPEO_FISICA = {
    "ARRIBA": "ARRIBA", "ABAJO": "ABAJO", "IZQ": "IZQ", "DER": "DER",
    "L1": "L1", "R1": "R1", "L2": "L2", "SELECT": "SELECT", "START": "START", "HOME": "HOME",
}

NOMBRES_CONTROL = {"joycon-izq": L("Joy-Con izquierdo (Longshot)", "Left Joy-Con (Longshot)"),
                   "wii-classic": "Wii Classic", "wii-remote": "Wii Remote"}


def _stick_cfg(matriz):
    return {"centro": [128, 128], "matriz": copy.deepcopy(matriz), "zona_muerta": 0.08,
            "rango": 0.95,           # fracción del recorrido que ya cuenta como tope
            "invertir_x": False, "invertir_y": False}


def perfil_por_defecto(orientacion=None, nombre=None, control="joycon-izq"):
    ctrl = _control(control)
    if orientacion not in ctrl.orientaciones:
        orientacion = next(iter(ctrl.orientaciones))
    nombre = nombre or str(NOMBRES_CONTROL.get(ctrl.id, ctrl.nombre))
    lado = orientacion == "lado"
    g = ctrl.gyro[orientacion]
    if ctrl.id == "joycon-izq":
        mapeo = dict(MAPEO_LADO_LONGSHOT if lado else MAPEO_FISICA)
    else:
        mapeo = mapeo_generico(ctrl)
    return {
        "version": VERSION_ESQUEMA,
        "nombre": nombre,
        "control": ctrl.id,
        "orientacion": orientacion,
        "calibrado": False,          # True cuando se completó el asistente
        "slot": None,                # None = el primero que mande datos
        "stick": _stick_cfg(stick_por_defecto(ctrl, orientacion)),
        "stick_der": _stick_cfg(stick_por_defecto(ctrl, orientacion)),   # solo si el control lo tiene
        "fisicos": ctrl.fisicos_por_defecto(),   # botón físico -> bit que manda la app (lo mide el asistente)
        "mapeo": mapeo,
        "gyro": {
            "perm": list(g["perm"]),         # eje de la app que alimenta pitch, yaw, roll
            "signo": list(g["signo"]),
            "escala": 1.0,                   # 57.2958 si la app manda rad/s
            "bias": [0.0, 0.0, 0.0],         # en unidades de la app, ejes de la app
            "ruido": 3.0,                    # °/s en reposo
            "sensibilidad": 1.0,
            "invertir": [False, False, False],   # pitch, yaw, roll
            "zona_muerta": 0.0,              # °/s; 0 = sin zona muerta (recomendado en DS4)
        },
        "accel": {"escala": 1.0, "signo": 1},
        "gyro_stick": {"activo": False, "max_dps": 150.0, "zona_muerta": 6.0,
                       "invertir_x": False, "invertir_y": False},
        "salidas": {"ds4": True, "xbox": False, "dsu": False, "dsu_puerto": 26761},
    }


def _mezclar(base, extra):
    """Copia `extra` sobre `base` recursivamente (solo claves conocidas de dicts)."""
    for k, v in extra.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict) and k not in ("mapeo",):
            _mezclar(base[k], v)
        else:
            base[k] = v
    return base


def migrar(datos):
    """Convierte cualquier versión anterior al esquema actual. Lanza ValueError
    si el archivo no es un perfil reconocible."""
    if not isinstance(datos, dict):
        raise ValueError("el archivo no contiene un perfil")
    version = datos.get("version")
    if version is None:
        if "remapeo" not in datos and "gyro_perm" not in datos:
            raise ValueError("el archivo no parece un perfil ni una calibración")
        return _migrar_v1(datos)
    if not isinstance(version, int) or version < 1:
        raise ValueError(f"versión de perfil inválida: {version!r}")
    if version > VERSION_ESQUEMA:
        raise ValueError(f"el perfil es de una versión más nueva ({version}); actualiza la app")
    if version == 1:
        return _migrar_v1(datos)
    p = perfil_por_defecto(datos.get("orientacion"), datos.get("nombre"), datos.get("control", "joycon-izq"))
    _mezclar(p, datos)
    p["version"] = VERSION_ESQUEMA
    _sanear(p)
    return p


def _migrar_v1(c):
    """v1 = calibracion.json de dsu_bridge.py (sin número de versión)."""
    rem = c.get("remapeo", {})
    inv = c.get("invertir", {})
    cen = c.get("centro", {})
    # En v1 no existía la orientación: si las flechas alimentan A/B/X/Y era
    # "vertical con flechas como botones"; lo tratamos como orientación física.
    p = perfil_por_defecto("fisica", c.get("nombre", "Calibración importada (v1)"), "joycon-izq")
    p["slot"] = c.get("slot")
    p["stick"]["centro"] = [cen.get("lx", 128), cen.get("ly", 128)]
    # v1: x = (lx-c)/127 (± invertir), y = (ly-c)/127 (± invertir), con + = arriba
    p["stick"]["matriz"] = [[-1 if inv.get("lx") else 1, 0], [0, -1 if inv.get("ly") else 1]]
    mapeo = {}
    for salida in SALIDAS:
        mapeo[salida] = rem.get(salida, salida)   # v1: lo no remapeado pasaba tal cual
    p["mapeo"] = mapeo
    p["gyro"].update({
        "perm": list(c.get("gyro_perm", [0, 1, 2])),
        "signo": list(c.get("gyro_signo", [1, 1, 1])),
        "escala": float(c.get("gyro_escala", 1.0)),
        "bias": list(c.get("gyro_bias", [0.0, 0.0, 0.0])),
        "ruido": float(c.get("gyro_ruido", 3.0)),
    })
    p["accel"] = {"escala": float(c.get("accel_escala", 1.0)), "signo": int(c.get("accel_signo", 1))}
    p["calibrado"] = True
    _sanear(p)
    return p


def _sanear(p):
    g = p["gyro"]
    if sorted(g.get("perm", [])) != [0, 1, 2]:
        g["perm"] = [0, 1, 2]
    if len(g.get("signo", [])) != 3 or any(s not in (1, -1) for s in g["signo"]):
        g["signo"] = [1, 1, 1]
    if len(g.get("bias", [])) != 3:
        g["bias"] = [0.0, 0.0, 0.0]
    if len(g.get("invertir", [])) != 3:
        g["invertir"] = [False, False, False]
    ctrl = _control(p.get("control"))
    p["control"] = ctrl.id
    if p.get("orientacion") not in ctrl.orientaciones:
        p["orientacion"] = next(iter(ctrl.orientaciones))
    for k in ("stick", "stick_der"):
        m = p[k].get("matriz")
        if (not isinstance(m, list) or len(m) != 2 or any(not isinstance(f, list) or len(f) != 2 for f in m)):
            p[k]["matriz"] = stick_por_defecto(ctrl, p["orientacion"])
    p["mapeo"] = {k: v for k, v in p.get("mapeo", {}).items() if k in SALIDAS and v in SALIDAS}
    validos = {b.id for b in ctrl.botones} | ({"L"} if ctrl.id == "joycon-izq" else set())
    f = ctrl.fisicos_por_defecto()
    f.update({k: v for k, v in (p.get("fisicos") or {}).items() if k in validos and v in SALIDAS})
    p["fisicos"] = f


# ---------------------------------------------------------------- archivos
def carpeta_datos():
    base = os.environ.get("DSU_LONGSHOT_DATOS")
    if not base:
        base = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "DSU-Longshot")
    os.makedirs(os.path.join(base, "perfiles"), exist_ok=True)
    return base


def _archivo_seguro(nombre):
    limpio = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", nombre).strip(" .") or "perfil"
    return limpio[:80] + ".json"


def ruta_perfil(nombre):
    return os.path.join(carpeta_datos(), "perfiles", _archivo_seguro(nombre))


def listar():
    carpeta = os.path.join(carpeta_datos(), "perfiles")
    nombres = []
    for f in sorted(os.listdir(carpeta)):
        if f.lower().endswith(".json"):
            try:
                nombres.append(cargar_archivo(os.path.join(carpeta, f))["nombre"])
            except (ValueError, OSError, KeyError):
                continue
    return nombres


def cargar_archivo(ruta):
    with open(ruta, encoding="utf-8") as f:
        try:
            datos = json.load(f)
        except json.JSONDecodeError as err:
            raise ValueError(f"JSON inválido: {err}") from err
    p = migrar(datos)
    if not p.get("nombre"):
        p["nombre"] = os.path.splitext(os.path.basename(ruta))[0]
    return p


def cargar(nombre):
    return cargar_archivo(ruta_perfil(nombre))


def guardar(perfil, ruta=None):
    perfil["version"] = VERSION_ESQUEMA
    ruta = ruta or ruta_perfil(perfil["nombre"])
    tmp = ruta + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(perfil, f, indent=2, ensure_ascii=False)
    os.replace(tmp, ruta)
    return ruta


def borrar(nombre):
    ruta = ruta_perfil(nombre)
    if os.path.exists(ruta):
        os.remove(ruta)


def renombrar(nombre, nuevo):
    p = cargar(nombre)
    p["nombre"] = nuevo
    guardar(p)
    if _archivo_seguro(nombre) != _archivo_seguro(nuevo):
        borrar(nombre)
    return p


def duplicar(nombre, nuevo):
    p = cargar(nombre)
    p["nombre"] = nuevo
    guardar(p)
    return p


# ------------------------------------------------- ajustes generales de la app
def _ruta_ajustes():
    return os.path.join(carpeta_datos(), "ajustes.json")


AJUSTES_DEFAULT = {"ip": "", "idioma": "en", "puerto": 26760, "recientes": [],
                   "perfil_por_defecto": None, "conectar_al_abrir": False}


def cargar_ajustes():
    a = dict(AJUSTES_DEFAULT)
    try:
        with open(_ruta_ajustes(), encoding="utf-8") as f:
            a.update(json.load(f))
    except (OSError, ValueError):
        pass
    return a


def guardar_ajustes(a):
    tmp = _ruta_ajustes() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(a, f, indent=2, ensure_ascii=False)
    os.replace(tmp, _ruta_ajustes())
