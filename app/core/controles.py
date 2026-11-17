"""Tipos de control de la app DSU Controller: botones, sticks, dibujo y mapeo.

Qué bit del protocolo manda cada botón (`esperado`) sale de los perfiles
oficiales de Dolphin del desarrollador de la app:
https://github.com/breeze2/dsu-controller-guides/tree/master/configs/dolphin
(DSUController.ini = Wii Remote, DSUController_with_Classic.ini = Wii Classic).
El Joy-Con izquierdo se verificó con el teléfono real (referencia/captura_joycon-izq.json).
El Wii Classic se verificó con un teléfono real en la 1.2.1. El Wii Remote es un SUPUESTO: el
asistente de calibración vuelve a medir cada botón de todos modos.

Coordenadas del dibujo: píxeles del screenshot del teléfono en vertical.
"""
import copy

from app.i18n import L

# Matrices del stick: lógico(x derecha, y arriba) = M · crudo(x, y), crudo centrado.
STICK_LADO = [[0, 1], [1, 0]]      # Joy-Con: la app no rota el stick y usa Y = 0 arriba
STICK_FISICA = [[1, 0], [0, -1]]   # Joy-Con vertical (Y = 0 arriba)
STICK_ESTANDAR = [[1, 0], [0, 1]]  # protocolo DSU estándar: Y = 255 arriba
# DSU Controller manda Y = 0 arriba también en el Classic (probado con un teléfono real, 1.2.1)
STICK_Y_ARRIBA_CERO = [[1, 0], [0, -1]]

GYRO_LADO = {"perm": [2, 1, 0], "signo": [-1, -1, -1]}   # teléfono acostado, arriba del teléfono a la izquierda
GYRO_FISICA = {"perm": [0, 1, 2], "signo": [1, 1, 1]}


class Boton:
    __slots__ = ("id", "texto", "etiqueta", "esperado", "forma", "geo", "color", "corto")

    def __init__(self, ident, texto, etiqueta, esperado, forma, geo, color="gris", corto=None):
        # texto: lo que pide el asistente («Toca …»); etiqueta: nombre en tablas; corto: texto del dibujo
        self.id, self.esperado = ident, esperado
        self.texto = texto if isinstance(texto, L) else L(texto, texto)
        self.etiqueta = etiqueta
        self.forma, self.geo, self.color = forma, geo, color
        self.corto = corto if corto is not None else (str(etiqueta) if len(str(etiqueta)) <= 3 else "")


class Control:
    """Descripción de un tipo de control de la app del teléfono."""

    def __init__(self, ident, nombre, ancho, alto, botones, sticks, orientaciones,
                 stick_matriz, gyro, stick_vertical=False, verificado=False, nota=""):
        self.id, self.nombre = ident, nombre
        self.ancho, self.alto = float(ancho), float(alto)
        self.botones = botones                 # lista de Boton, en el orden del asistente
        self.sticks = sticks                   # {"izq"|"der": (cx, cy, r)}
        self.orientaciones = orientaciones     # {"lado"|"fisica": texto}
        self.stick_matriz = stick_matriz       # orientación -> matriz por defecto
        self.gyro = gyro                       # orientación -> ejes por defecto
        self.stick_vertical = stick_vertical   # True = el crudo del stick viene en el marco del teléfono vertical
        self.verificado = verificado           # True = bits medidos con el teléfono real
        self.nota = nota

    def boton(self, fid):
        for b in self.botones:
            if b.id == fid:
                return b
        raise KeyError(fid)

    def fisicos_por_defecto(self):
        return {b.id: b.esperado for b in self.botones}

    def nombre_fuente(self, fisicos, bit):
        """Nombre legible del bit `bit` según qué botón físico lo manda."""
        nombres = [str(self.boton(f).etiqueta) for f, b in fisicos.items() if b == bit and _existe(self, f)]
        return " / ".join(nombres) if nombres else bit

    def fuente_a_fisicos(self, fisicos):
        inv = {}
        for f, b in fisicos.items():
            if _existe(self, f):
                inv.setdefault(b, []).append(f)
        return inv


def _existe(control, fid):
    return any(b.id == fid for b in control.botones)


B = Boton
# ------------------------------------------------------------ Joy-Con izquierdo
JOYCON_IZQ = Control(
    "joycon-izq", L("Joy-Con izquierdo", "Left Joy-Con"), 591, 1280,
    [
        B("ZL", "ZL", "ZL", "L2", "rect", (180, 142, 140, 76), "morado"),
        B("SL", "SL", "SL / L", "L1", "rect", (476, 840, 78, 157), "morado", "SL"),
        B("SR", "SR", "SR", "R1", "rect", (476, 1035, 78, 157), "morado"),
        B("MENOS", L("− (la rayita)", "− (minus)"), "−", "SELECT", "circ", (515, 565, 30), "fondo"),
        B("VERDE", L("el ícono verde", "the green icon"), L("Ícono verde", "Green icon"), "HOME", "circ",
          (515, 667, 30), "fondo", "⌂"),
        B("MAS", "+", "+", "START", "circ", (515, 770, 30), "fondo"),
        B("F_ARRIBA", L("la flecha △", "the △ arrow"), L("Flecha △", "Arrow △"), "ARRIBA", "circ", (238, 927, 53),
          corto="△"),
        B("F_DER", L("la flecha ▷", "the ▷ arrow"), L("Flecha ▷", "Arrow ▷"), "DER", "circ", (344, 1033, 53),
          corto="▷"),
        B("F_ABAJO", L("la flecha ▽", "the ▽ arrow"), L("Flecha ▽", "Arrow ▽"), "ABAJO", "circ", (238, 1139, 53),
          corto="▽"),
        B("F_IZQ", L("la flecha ◁", "the ◁ arrow"), L("Flecha ◁", "Arrow ◁"), "IZQ", "circ", (132, 1033, 53),
          corto="◁"),
        # L manda lo mismo que SL: no se pide en el asistente, solo se dibuja
    ],
    {"izq": (238, 547, 72)},
    {"lado": "De lado — para cualquier juego (Longshot)",
     "fisica": "Física (vertical) — para emuladores de Switch por servidor DSU"},
    {"lado": STICK_LADO, "fisica": STICK_FISICA},
    {"lado": GYRO_LADO, "fisica": GYRO_FISICA},
    stick_vertical=True, verificado=True)
# El botón L se dibuja pero no se pide (llega idéntico a SL)
BOTON_L_JOYCON = B("L", "L", "L", "L1", "rect", (358, 142, 140, 76))

# ------------------------------------------------------------------ Wii Classic
# Se usa acostado: arriba del teléfono a la izquierda (ZL/ZR quedan arriba).
# Cruceta: el pétalo de arriba del teléfono vertical queda a TU izquierda.
WII_CLASSIC = Control(
    "wii-classic", L("Wii Classic (control completo)", "Wii Classic (full controller)"), 739, 1600,
    [
        B("C_A", L("el botón a", "the a button"), "a", "B", "circ", (640, 1328, 53)),
        B("C_B", L("el botón b", "the b button"), "b", "A", "circ", (532, 1435, 53)),
        B("C_X", L("el botón x", "the x button"), "x", "Y", "circ", (532, 1220, 53)),
        B("C_Y", L("el botón y", "the y button"), "y", "X", "circ", (425, 1328, 53)),
        B("L", "L", "L", "L1", "rect", (405, 453, 120, 97)),
        B("R", "R", "R", "R1", "rect", (405, 1036, 120, 97)),
        B("ZL", "ZL", "ZL", "L2", "rect", (540, 453, 120, 140), "morado"),
        B("ZR", "ZR", "ZR", "R2", "rect", (540, 993, 120, 140), "morado"),
        B("AL", L("AL (junto a L)", "AL (next to L)"), "AL", "L3", "rect", (428, 565, 97, 82)),
        B("AR", L("AR (junto a R)", "AR (next to R)"), "AR", "R3", "rect", (428, 938, 97, 82)),
        B("MENOS", "−", "−", "SELECT", "circ", (330, 675, 26), "fondo"),
        B("VERDE", L("el ícono verde (en medio)", "the green icon (center)"), L("Ícono verde", "Green icon"), "HOME",
          "circ", (330, 792, 26), "fondo", "⌂"),
        B("MAS", "+", "+", "START", "circ", (330, 908, 26), "fondo"),
        B("D_ARRIBA", L("la flecha de TU arriba", "the arrow pointing to YOUR up"), L("Cruceta ↑", "D-pad ↑"),
          "ARRIBA", "circ", (612, 276, 44), corto="↑"),
        B("D_DER", L("la flecha de TU derecha", "the arrow pointing to YOUR right"), L("Cruceta →", "D-pad →"),
          "DER", "circ", (531, 345, 44), corto="→"),
        B("D_ABAJO", L("la flecha de TU abajo", "the arrow pointing to YOUR down"), L("Cruceta ↓", "D-pad ↓"),
          "ABAJO", "circ", (450, 276, 44), corto="↓"),
        B("D_IZQ", L("la flecha de TU izquierda", "the arrow pointing to YOUR left"), L("Cruceta ←", "D-pad ←"),
          "IZQ", "circ", (531, 207, 44), corto="←"),
    ],
    {"izq": (145, 470, 62), "der": (145, 1200, 62)},
    {"lado": "Acostado (ZL y ZR arriba) — como un control completo"},
    {"lado": STICK_Y_ARRIBA_CERO},
    {"lado": GYRO_LADO},
    verificado=True,       # 17 botones y 2 sticks probados con un teléfono real (1.2.1)
    nota=L("Parecido a un Pro Controller: 2 sticks, a b x y, L R ZL ZR, cruceta, − + y Home. "
           "AL y AR llegan como L3 y R3 (clic de los sticks).",
           "Similar to a Pro Controller: 2 sticks, a b x y, L R ZL ZR, d-pad, − + and Home. "
           "AL and AR arrive as L3 and R3 (stick clicks)."))

# ------------------------------------------------------------------ Wii Remote
WII_REMOTE = Control(
    "wii-remote", "Wii Remote", 739, 1600,
    [
        B("W_A", L("el botón A (morado)", "the A button (purple)"), "A", "A", "circ", (604, 290, 88), "morado"),
        B("W_B", L("la barra B", "the B bar"), "B", "X", "rect", (46, 548, 646, 118)),
        B("UNO", L("el botón 1", "the 1 button"), "1", "Y", "circ", (528, 1355, 88)),
        B("DOS", L("el botón 2", "the 2 button"), "2", "B", "circ", (210, 1355, 88)),
        B("MENOS", "−", "−", "SELECT", "circ", (199, 810, 30), "fondo"),
        B("HOME", L("la casita verde", "the green house"), "Home", "HOME", "circ", (369, 810, 30), "fondo", "⌂"),
        B("MAS", "+", "+", "START", "circ", (540, 810, 30), "fondo"),
        B("D_ARRIBA", L("la flecha de arriba", "the up arrow"), L("Cruceta ↑", "D-pad ↑"), "ARRIBA", "circ",
          (200, 205, 48), corto="↑"),
        B("D_DER", L("la flecha de la derecha", "the right arrow"), L("Cruceta →", "D-pad →"), "DER", "circ",
          (285, 290, 48), corto="→"),
        B("D_ABAJO", L("la flecha de abajo", "the down arrow"), L("Cruceta ↓", "D-pad ↓"), "ABAJO", "circ",
          (200, 375, 48), corto="↓"),
        B("D_IZQ", L("la flecha de la izquierda", "the left arrow"), L("Cruceta ←", "D-pad ←"), "IZQ", "circ",
          (115, 290, 48), corto="←"),
    ],
    {},
    {"fisica": "Vertical, apuntando a la pantalla como un Wiimote"},
    {"fisica": STICK_ESTANDAR},
    {"fisica": GYRO_FISICA},
    nota=L("Sin stick. Para juegos de Wii en Dolphin o juegos que se manejen con cruceta y movimiento.",
           "No stick. For Wii games in Dolphin or games played with d-pad and motion."))

CONTROLES = {c.id: c for c in (JOYCON_IZQ, WII_CLASSIC, WII_REMOTE)}


def control(ident):
    return CONTROLES.get(ident, JOYCON_IZQ)


def mapeo_generico(ctrl, fisicos=None):
    """Mapeo salida -> fuente: cada botón sale como el botón que la app dice ser
    (el mismo que usan los perfiles de Dolphin), pero con el bit que se midió."""
    f = ctrl.fisicos_por_defecto()
    f.update(fisicos or {})
    return {b.esperado: f[b.id] for b in ctrl.botones}


def stick_por_defecto(ctrl, orientacion):
    return copy.deepcopy(ctrl.stick_matriz.get(orientacion, STICK_ESTANDAR))
