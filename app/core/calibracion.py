"""Calibración: análisis puro + asistente por pasos (sin UI).

El asistente es una máquina de estados que se alimenta con cada Estado que
llega del teléfono. La UI solo dibuja `paso_actual()` y llama a
`alimentar()`; un "usuario robot" lo prueba igual contra el simulador.
"""
import copy
import math

from app.i18n import L, T

from . import controles as CT
from . import perfiles as PF

# ------------------------------------------------------------------ análisis


def analizar_reposo(muestras):
    """muestras: lista de (gyro3, accel3). Devuelve bias, ruido, gravedad media."""
    n = len(muestras)
    bias = [sum(m[0][i] for m in muestras) / n for i in range(3)]
    var = [sum((m[0][i] - bias[i]) ** 2 for m in muestras) / n for i in range(3)]
    ruido = max(math.sqrt(v) for v in var)
    grav = [sum(m[1][i] for m in muestras) / n for i in range(3)]
    return bias, ruido, grav


def dt_entre(prev, e):
    """Segundos entre dos Estados. Un timestamp repetido aporta 0 (la app del
    teléfono repite la misma muestra de movimiento en varios paquetes)."""
    if prev is None:
        return 0.0
    if e.ts_us and prev.ts_us:
        if e.ts_us == prev.ts_us:
            return 0.0
        if e.ts_us > prev.ts_us:
            dt = (e.ts_us - prev.ts_us) / 1e6
            if dt < 0.2:
                return dt
    return max(0.0, min(0.2, e.t_llegada - prev.t_llegada))


def integrar_gesto(muestras, bias):
    """muestras: lista de Estado. Devuelve el ángulo girado en cada eje de la app."""
    angulo = [0.0, 0.0, 0.0]
    prev = None
    for e in muestras:
        dt = dt_entre(prev, e)
        for i in range(3):
            angulo[i] += (e.gyro[i] - bias[i]) * dt
        prev = e
    return angulo


def deducir_ejes(angulos):
    """angulos: {'pitch': [a0,a1,a2], 'yaw': [...], 'roll': [...]} medidos con
    gestos en la dirección POSITIVA de cada eje estándar. Devuelve
    (perm, signo, escala, grados) o lanza ValueError con la explicación."""
    perm, signo, magnitudes = [], [], []
    nombres = {"pitch": T("apuntar arriba", "point up"), "yaw": T("apuntar a la izquierda", "point left"),
               "roll": T("inclinar a la izquierda", "tilt left")}
    for eje in ("pitch", "yaw", "roll"):
        a = angulos[eje]
        idx = max(range(3), key=lambda i: abs(a[i]))
        total = math.sqrt(sum(x * x for x in a))
        if total == 0 or abs(a[idx]) / total < 0.75:
            raise ValueError(T(f"el gesto de {nombres[eje]} movió varios ejes a la vez; hazlo más 'puro'",
                               f"the '{nombres[eje]}' gesture moved several axes at once; make it cleaner"))
        perm.append(idx)
        signo.append(1 if a[idx] > 0 else -1)
        magnitudes.append(abs(a[idx]))
    if len(set(perm)) != 3:
        raise ValueError(T("dos gestos movieron el mismo eje; repite con giros más claros",
                           "two gestures moved the same axis; repeat with clearer rotations"))
    med = sorted(magnitudes)[1]
    escala = 180 / math.pi if med < 5 else 1.0   # ~0.8 para 45° => la app manda rad/s
    grados = [m * escala for m in magnitudes]
    if min(grados) < 15:
        raise ValueError(T("algún giro fue muy pequeño; gira unos 45°", "a rotation was too small; rotate about 45°"))
    return perm, signo, escala, grados


def deducir_stick(arriba, derecha):
    """arriba/derecha: vector crudo centrado (x, y) al empujar hacia el arriba y
    la derecha DEL USUARIO. Devuelve la matriz 2x2 lógico = M · crudo."""
    def dominante(v):
        i = 0 if abs(v[0]) >= abs(v[1]) else 1
        if abs(v[i]) < 0.5:
            raise ValueError(T("el stick no llegó lo bastante lejos; empújalo hasta el tope",
                               "the stick did not go far enough; push it all the way"))
        if abs(v[1 - i]) > 0.7 * abs(v[i]):
            raise ValueError(T("el stick fue en diagonal; empújalo en una sola dirección",
                               "the stick went diagonally; push it in a single direction"))
        return i, (1 if v[i] > 0 else -1)
    iy, sy = dominante(arriba)
    ix, sx = dominante(derecha)
    if ix == iy:
        raise ValueError(T("'arriba' y 'derecha' movieron el mismo eje; repite las dos direcciones",
                           "'up' and 'right' moved the same axis; repeat both directions"))
    m = [[0, 0], [0, 0]]
    m[0][ix] = sx
    m[1][iy] = sy
    return m


# Dirección cruda (x, y con Y = 0 arriba) hacia donde apunta cada flecha de la
# app con el teléfono vertical.
_FLECHAS = {"ARRIBA": (0, -1), "DER": (1, 0), "ABAJO": (0, 1), "IZQ": (-1, 0)}
# Botón de cara según la posición que ocupa para el usuario (estilo Xbox/DS4)
_CARA_POR_POSICION = {(0, 1): "Y", (1, 0): "B", (0, -1): "A", (-1, 0): "X"}


def remapeo_joycon(matriz, orientacion="lado"):
    """Mapeo salida -> fuente para las 4 flechas del Joy-Con izquierdo.

    De lado: cada flecha se vuelve el botón de cara de la posición donde queda
    para el usuario (la misma rotación que se dedujo para el stick).
    Física: las flechas siguen siendo la cruceta, sin rotar.
    """
    if orientacion != "lado":
        return {f: f for f in _FLECHAS}
    mapeo = {}
    for fuente, (vx, vy) in _FLECHAS.items():
        pos = (matriz[0][0] * vx + matriz[0][1] * vy, matriz[1][0] * vx + matriz[1][1] * vy)
        mapeo[_CARA_POR_POSICION[pos]] = fuente
    return mapeo


def mapeo_por_defecto(matriz, orientacion, fisicos=None):
    """Mapeo completo salida -> fuente. `fisicos`: botón físico -> bit detectado
    (por si la app manda algún botón distinto a lo esperado)."""
    f = dict(PF.FISICOS_JOYCON_IZQ)
    f.update(fisicos or {})
    if orientacion == "lado":
        base = {"L1": f["SL"], "R1": f["SR"], "L2": f["ZL"], "R2": f["VERDE"],
                "SELECT": f["MENOS"], "START": f["MAS"]}
    else:
        base = {"L1": f["L"], "R1": f["SR"], "L2": f["ZL"], "HOME": f["VERDE"],
                "SELECT": f["MENOS"], "START": f["MAS"]}
    traduccion = {"ARRIBA": f["F_ARRIBA"], "ABAJO": f["F_ABAJO"], "IZQ": f["F_IZQ"], "DER": f["F_DER"]}
    for salida, flecha in remapeo_joycon(matriz, orientacion).items():
        base[salida] = traduccion[flecha]
    return base


def mapeo_recomendado(perfil, fisicos=None):
    """Mapeo por defecto para el control y la orientación del perfil."""
    ctrl = CT.control(perfil.get("control"))
    f = dict(perfil.get("fisicos") or {})
    f.update(fisicos or {})
    if ctrl.id == "joycon-izq":
        return mapeo_por_defecto(perfil["stick"]["matriz"], perfil["orientacion"], f)
    return CT.mapeo_generico(ctrl, f)


# ------------------------------------------------------------------ asistente
ESPERANDO, HECHO = "esperando", "hecho"

# (id físico, texto) en el orden en que se piden
BOTONES_JOYCON_IZQ = [
    ("ZL", "ZL"), ("SL", "SL"), ("SR", "SR"), ("MENOS", "− (la rayita)"),
    ("VERDE", "el ícono verde"), ("MAS", "+"),
    ("F_ARRIBA", "la flecha △"), ("F_DER", "la flecha ▷"),
    ("F_ABAJO", "la flecha ▽"), ("F_IZQ", "la flecha ◁"),
]

GESTOS = [
    ("pitch", L("Apunta hacia ARRIBA", "Point UP"),
     L("Levanta la parte de enfrente del control, como para mirar al techo.",
       "Raise the front of the controller, as if looking at the ceiling.")),
    ("yaw", L("Apunta hacia la IZQUIERDA", "Point LEFT"),
     L("Gira el control hacia tu izquierda, como si estuviera sobre una mesa (sin inclinarlo).",
       "Turn the controller to your left, as if it were lying on a table (without tilting it).")),
    ("roll", L("Inclina hacia la IZQUIERDA", "Tilt LEFT"),
     L("Como un volante: baja el lado izquierdo y sube el derecho.",
       "Like a steering wheel: lower the left side and raise the right side.")),
]

ANGULO_META = 40.0        # ° que hay que alcanzar en cada gesto
ANGULO_META_RAD = 0.65    # lo mismo si la app mandara rad/s
T_REPOSO = 3.0


class Paso:
    """Un paso del asistente. `info` lleva los datos en vivo para dibujar."""

    def __init__(self, ident, tipo, titulo, texto, **extra):
        self.id, self.tipo, self.titulo, self.texto = ident, tipo, titulo, texto
        self.estado = ESPERANDO
        self.progreso = 0.0
        self.aviso = ""
        self.info = dict(extra)
        self.resultado = None


class Asistente:
    """Asistente de calibración (Joy-Con izquierdo, Wii Classic o Wii Remote).

    Uso: crear, llamar `alimentar(estado)` con cada paquete; mirar `paso` (el
    actual), `terminado` y, al final, `aplicar(perfil)`.
    Cada paso se puede repetir suelto con `ir_a(id)`.
    """

    def __init__(self, perfil):
        self.perfil = copy.deepcopy(perfil)
        self.orientacion = self.perfil["orientacion"]
        self.control = CT.control(self.perfil.get("control"))
        lado = self.orientacion == "lado"
        if self.control.id == "joycon-izq":
            como = (T("de lado (SL y SR arriba, stick a la izquierda)", "sideways (SL and SR on top, stick on the left)")
                    if lado else T("vertical (ZL y L arriba)", "upright (ZL and L on top)"))
        elif self.control.id == "wii-classic":
            como = T("acostado (ZL y ZR arriba, sticks abajo)", "landscape (ZL and ZR on top, sticks at the bottom)")
        else:
            como = T("vertical, apuntando a la pantalla", "upright, pointing at the screen")
        fis = self.perfil.get("fisicos") or {}
        self.pasos = []
        for b in self.control.botones:
            self.pasos.append(Paso("boton:" + b.id, "boton", L("Botones", "Buttons"),
                                   L(f"Toca {b.texto.es}", f"Press {b.texto.en}"), fisico=b.id,
                                   esperado=fis.get(b.id, b.esperado)))
        dos = len(self.control.sticks) > 1
        for cual, grupo in (("izq", "stick"), ("der", "stickd")):
            if cual not in self.control.sticks:
                continue
            es = ("stick IZQUIERDO" if cual == "izq" else "stick DERECHO") if dos else "stick"
            en = ("LEFT stick" if cual == "izq" else "RIGHT stick") if dos else "stick"
            titulo = L(es[0].upper() + es[1:], en[0].upper() + en[1:])
            self.pasos += [
                Paso(grupo + ":centro", "stick_centro", titulo,
                     L(f"Suelta el {es} (sin tocarlo)", f"Let go of the {en} (don't touch it)"), cual=cual),
                Paso(grupo + ":arriba", "stick_dir", titulo,
                     L(f"Empuja el {es} hacia TU arriba y sostenlo", f"Push the {en} toward YOUR up and hold it"),
                     direccion="arriba", cual=cual),
                Paso(grupo + ":derecha", "stick_dir", titulo,
                     L(f"Empuja el {es} hacia TU derecha y sostenlo", f"Push the {en} toward YOUR right and hold it"),
                     direccion="derecha", cual=cual),
            ]
        self.pasos.append(Paso("reposo", "reposo", L("Reposo", "Rest"),
                               T(f"Sostén el teléfono como vas a jugar, {como}, y quédate quieto",
                                 f"Hold the phone the way you will play, {como}, and stay still")))
        self.matrices = {}
        for eje, titulo, texto in GESTOS:
            self.pasos.append(Paso("gesto:" + eje, "gesto", titulo, texto, eje=eje))
        self.indice = 0
        self.terminado = False
        self.error = ""            # error al deducir (stick o ejes)
        self._unico = False        # True = se está repitiendo un paso suelto
        self._prev = None
        self._reiniciar_paso()

    # ---- navegación
    @property
    def paso(self):
        return self.pasos[self.indice]

    def _por_id(self, ident):
        for i, p in enumerate(self.pasos):
            if p.id == ident:
                return i
        raise KeyError(ident)

    def ir_a(self, ident, unico=True):
        """Salta a un paso para repetirlo. Con unico=True se repite solo su
        grupo (botones, stick, reposo o giros) y el asistente vuelve a quedar
        terminado, sin pasar por los demás."""
        self.indice = self._por_id(ident)
        self.terminado = False
        self.error = ""
        self._unico = unico
        self._reiniciar_paso()

    def _reiniciar_paso(self):
        p = self.paso
        p.estado, p.progreso, p.aviso, p.resultado = ESPERANDO, 0.0, "", None
        self._prev = None
        self._t_inicio = None
        self._t_estable = None
        self._fase = 0
        self._muestras = []
        self._angulo = [0.0, 0.0, 0.0]
        self._pico = 0.0
        self._soltado = False
        if p.tipo == "gesto":
            p.info.update(angulo=[0.0, 0.0, 0.0], avance=0.0, fase="girar")
        if p.tipo == "boton":
            p.info.pop("inesperado", None)

    def omitir(self):
        """Salta el paso actual dejando su valor por defecto."""
        self.paso.estado = HECHO
        self.paso.aviso = T("omitido", "skipped")
        self._avanzar()

    def aceptar_inesperado(self):
        """El botón pedido llegó como otro bit: se acepta y se reasigna."""
        p = self.paso
        if p.tipo == "boton" and p.info.get("inesperado"):
            p.resultado = p.info["inesperado"]
            p.estado = HECHO
            self._avanzar()

    def _grupo(self, p):
        return p.id.split(":")[0]

    def _avanzar(self):
        actual = self.paso
        # Fin de grupo: deducir
        fin_stick = actual.tipo == "stick_dir" and actual.info.get("direccion") == "derecha"
        fin_gestos = actual.id == "gesto:roll"
        if fin_stick and not self._deducir_stick(self._grupo(actual)):
            return
        if fin_gestos and not self._deducir_ejes():
            return
        siguiente = self.indice + 1
        if self._unico:
            mismo_grupo = (siguiente < len(self.pasos)
                           and self._grupo(self.pasos[siguiente]) == self._grupo(actual)
                           and self._grupo(actual) in ("boton", "stick", "stickd", "gesto"))
            if not mismo_grupo:
                self.terminado = True
                return
        if siguiente >= len(self.pasos):
            self.terminado = True
            return
        self.indice = siguiente
        self._reiniciar_paso()

    # ---- deducciones de grupo
    def _res(self, ident):
        return self.pasos[self._por_id(ident)].resultado

    @property
    def matriz(self):
        return self.matrices.get("stick")

    def _deducir_stick(self, grupo="stick"):
        arriba, derecha = self._res(grupo + ":arriba"), self._res(grupo + ":derecha")
        if arriba is None or derecha is None:
            return True   # alguno se omitió: se queda la matriz del perfil
        try:
            self.matrices[grupo] = deducir_stick(arriba, derecha)
        except ValueError as err:
            self.error = f"Stick: {err}."  # noqa
            self.indice = self._por_id(grupo + ":arriba")
            self._reiniciar_paso()
            self.paso.aviso = self.error
            return False
        self.error = ""
        return True

    def _deducir_ejes(self):
        ang = {eje: self._res("gesto:" + eje) for eje, _, _ in GESTOS}
        if any(a is None for a in ang.values()):
            return True   # se omitió alguno: se quedan los ejes del perfil
        try:
            self.ejes = deducir_ejes(ang)
        except ValueError as err:
            self.error = T(f"No quedó claro: {err}. Repite los tres giros.",
                           f"Not clear: {err}. Repeat the three rotations.")
            self.indice = self._por_id("gesto:pitch")
            self._reiniciar_paso()
            self.paso.aviso = self.error
            return False
        self.error = ""
        return True

    # ---- alimentación
    def alimentar(self, e):
        if self.terminado:
            return
        p = self.paso
        getattr(self, "_paso_" + p.tipo)(p, e)
        self._prev = e

    def _paso_boton(self, p, e):
        activos = [b for b, v in e.fuente.items() if v]
        if not self._soltado:            # esperar a que no haya nada presionado
            if not activos:
                self._soltado = True
            return
        if p.estado == ESPERANDO:
            if p.info["esperado"] in activos:
                p.resultado = p.info["esperado"]
                p.estado = "presionado"
                p.info.pop("inesperado", None)
                p.aviso = ""
            elif activos:
                p.info["inesperado"] = activos[0]
                nombre = self.control.nombre_fuente(self.perfil.get("fisicos") or {}, activos[0])
                p.aviso = T(f"Llegó «{nombre}» en vez del botón pedido. Si tocaste el correcto, acepta la "
                            "reasignación.", f"Got «{nombre}» instead of the requested button. If you pressed the "
                            "right one, accept the remap.")
        elif p.estado == "presionado" and not activos:
            p.estado = HECHO
            self._avanzar()

    @staticmethod
    def _xy(e, cual):
        return (e.lx, e.ly) if cual == "izq" else (e.rx, e.ry)

    def _centro(self, cual="izq"):
        r = self._res(("stick" if cual == "izq" else "stickd") + ":centro")
        return r if r else self.perfil["stick" if cual == "izq" else "stick_der"]["centro"]

    def _paso_stick_centro(self, p, e):
        x, y = self._xy(e, p.info.get("cual", "izq"))
        quieto = abs(x - 128) < 40 and abs(y - 128) < 40
        if not quieto:
            self._muestras = []
            self._t_inicio = None
            p.progreso = 0.0
            p.aviso = T("Suelta el stick", "Let go of the stick")
            return
        p.aviso = ""
        if self._t_inicio is None:
            self._t_inicio = e.t_llegada
        self._muestras.append((x, y))
        p.progreso = min(1.0, (e.t_llegada - self._t_inicio) / 0.7)
        if p.progreso >= 1.0:
            n = len(self._muestras)
            p.resultado = [round(sum(m[0] for m in self._muestras) / n),
                           round(sum(m[1] for m in self._muestras) / n)]
            p.estado = HECHO
            self._avanzar()

    def _paso_stick_dir(self, p, e):
        cual = p.info.get("cual", "izq")
        cx, cy = self._centro(cual)
        x, y = self._xy(e, cual)
        v = ((x - cx) / 127.0, (y - cy) / 127.0)
        p.info["vector"] = v
        mag = math.hypot(*v)
        if self._fase == 0:                       # fase 0: empujar y sostener
            if mag < 0.6:
                self._t_inicio = None
                p.progreso = min(0.5, mag / 0.6 * 0.5)
                return
            if self._t_inicio is None:
                self._t_inicio = e.t_llegada
                self._muestras = []
            self._muestras.append(v)
            p.progreso = 0.5 + min(0.5, (e.t_llegada - self._t_inicio) / 0.35 * 0.5)
            if e.t_llegada - self._t_inicio >= 0.35:
                n = len(self._muestras)
                p.resultado = (sum(m[0] for m in self._muestras) / n,
                               sum(m[1] for m in self._muestras) / n)
                p.estado = "presionado"
                p.texto_fase = "Suéltalo"
                self._fase = 1
        elif mag < 0.25:                          # fase 1: soltar
            p.estado = HECHO
            self._avanzar()

    def _paso_reposo(self, p, e):
        nuevo = self._prev is None or e.ts_us != self._prev.ts_us
        if self._t_inicio is None:
            self._t_inicio = e.t_llegada
        if nuevo:
            self._muestras.append((e.gyro, e.accel))
            # Si se mueve mucho durante la medición, se empieza de nuevo
            if len(self._muestras) >= 8:
                ult = self._muestras[-8:]
                medio = [sum(m[0][i] for m in ult) / 8 for i in range(3)]
                inicio = [sum(m[0][i] for m in self._muestras[:8]) / 8 for i in range(3)]
                dif = max(abs(medio[i] - inicio[i]) for i in range(3))
                rad = max(abs(x) for m in self._muestras for x in m[0]) < 3.0
                if dif > (0.35 if rad else 20.0):
                    self._muestras = []
                    self._t_inicio = e.t_llegada
                    p.aviso = T("Se movió: quédate quieto", "It moved: stay still")
                    p.progreso = 0.0
                    return
        p.progreso = min(1.0, (e.t_llegada - self._t_inicio) / T_REPOSO)
        if len(self._muestras) >= 4:
            _, ruido, _ = analizar_reposo(self._muestras)
            p.info["ruido"] = ruido
        if p.progreso >= 1.0:
            if len(self._muestras) < 20:
                p.aviso = T("Llegan muy pocas muestras de movimiento. ¿La app tiene el movimiento activado?",
                            "Very few motion samples are arriving. Is motion enabled in the app?")
                self._muestras, self._t_inicio, p.progreso = [], e.t_llegada, 0.0
                return
            if all(abs(x) < 1e-6 for m in self._muestras for x in m[0] + m[1]):
                p.aviso = T("El giroscopio manda puros ceros. Activa el movimiento en la app del teléfono.",
                            "The gyro sends only zeros. Enable motion in the phone app.")
                self._muestras, self._t_inicio, p.progreso = [], e.t_llegada, 0.0
                return
            bias, ruido, grav = analizar_reposo(self._muestras)
            p.resultado = {"bias": bias, "ruido": ruido, "grav": grav}
            p.aviso = ""
            p.estado = HECHO
            self._avanzar()

    def _bias(self):
        r = self._res("reposo")
        return r["bias"] if r else self.perfil["gyro"]["bias"]

    def _paso_gesto(self, p, e):
        bias = self._bias()
        dt = dt_entre(self._prev, e)
        for i in range(3):
            self._angulo[i] += (e.gyro[i] - bias[i]) * dt
        vel = max(abs(e.gyro[i] - bias[i]) for i in range(3))
        self._pico = max(self._pico, vel)
        dom = max(abs(a) for a in self._angulo)
        # ¿La app manda rad/s? Solo si TODO es pequeño: velocidades < 8, ángulo
        # entre 0.65 y 3 y quietud casi perfecta (imposible a mano en °/s).
        en_rad = self._pico < 8.0 and ANGULO_META_RAD <= dom < 3.0 and vel < 0.25
        meta = ANGULO_META_RAD if en_rad else ANGULO_META
        quieto = vel < (0.25 if en_rad else 14.0)
        p.info["angulo"] = list(self._angulo)
        p.info["avance"] = min(1.0, dom / meta)
        if self._fase == 0:                       # girar hasta la meta y estabilizar
            p.info["fase"] = "girar"
            p.progreso = min(0.8, dom / meta * 0.8)
            if dom >= meta:
                if quieto:
                    if self._t_estable is None:
                        self._t_estable = e.t_llegada
                    p.progreso = 0.8 + min(0.2, (e.t_llegada - self._t_estable) / 0.4 * 0.2)
                    if e.t_llegada - self._t_estable >= 0.4:
                        p.resultado = list(self._angulo)
                        p.estado = "presionado"
                        self._fase = 1
                        self._t_estable = None
                        p.info["fase"] = "regresar"
                else:
                    self._t_estable = None
        else:                                     # regresar a la posición normal
            p.info["fase"] = "regresar"
            regreso = max(abs(self._angulo[i]) for i in range(3)) < 0.45 * max(abs(a) for a in p.resultado)
            if regreso and quieto:
                if self._t_estable is None:
                    self._t_estable = e.t_llegada
                if e.t_llegada - self._t_estable >= 0.4:
                    p.estado = HECHO
                    self._avanzar()
            else:
                self._t_estable = None

    def reiniciar_gesto(self):
        """Pone en cero el ángulo acumulado del gesto actual."""
        if self.paso.tipo == "gesto":
            self._reiniciar_paso()

    # ---- resultado
    def aplicar(self, perfil=None):
        """Devuelve una copia del perfil con todo lo que se calibró."""
        p = copy.deepcopy(perfil if perfil is not None else self.perfil)
        antes = copy.deepcopy(p)
        p["orientacion"] = self.orientacion
        p["control"] = self.control.id
        for grupo, cfg in (("stick", "stick"), ("stickd", "stick_der")):
            if not any(x.id == grupo + ":centro" for x in self.pasos):
                continue
            centro = self._res(grupo + ":centro")
            if centro:
                p[cfg]["centro"] = list(centro)
            if self.matrices.get(grupo):
                p[cfg]["matriz"] = self.matrices[grupo]
        fisicos = {}
        for paso in self.pasos:
            if paso.tipo == "boton" and paso.resultado:
                fisicos[paso.info["fisico"]] = paso.resultado
        if fisicos and self.control.id == "joycon-izq":
            fisicos.setdefault("L", fisicos.get("SL", "L1"))
        p.setdefault("fisicos", {}).update(fisicos)
        # El mapeo solo se regenera si cambió la rotación o algún bit; así no
        # se pisan los cambios que el usuario hizo a mano en Ajustes.
        nuevo = mapeo_recomendado(p)
        viejo = mapeo_recomendado(antes)
        if nuevo != viejo or not p.get("mapeo"):
            p["mapeo"] = nuevo
        reposo = self._res("reposo")
        if reposo:
            p["gyro"]["bias"] = list(reposo["bias"])
            mag = math.sqrt(sum(g * g for g in reposo["grav"]))
            p["accel"]["escala"] = 1 / 9.81 if 7 < mag < 12.5 else 1.0
        if getattr(self, "ejes", None):
            perm, signo, escala, _ = self.ejes
            p["gyro"].update(perm=perm, signo=signo, escala=escala)
        if reposo:
            p["gyro"]["ruido"] = reposo["ruido"] * p["gyro"]["escala"]
            # Signo del acelerómetro: en reposo y más o menos plano, la gravedad
            # debe quedar positiva en Y del marco estándar.
            perm, signo = p["gyro"]["perm"], p["gyro"]["signo"]
            g_map = [signo[i] * reposo["grav"][perm[i]] for i in range(3)]
            dominante = max(range(3), key=lambda i: abs(g_map[i]))
            if dominante == 1:
                p["accel"]["signo"] = 1 if g_map[1] > 0 else -1
                self.aviso_accel = ""
            else:
                self.aviso_accel = T("No sostuviste el teléfono plano en el reposo, así que no se pudo "
                                     "verificar el signo del acelerómetro.",
                                     "The phone was not held flat during the rest step, so the accelerometer "
                                     "sign could not be checked.")
        p["calibrado"] = True
        return p
