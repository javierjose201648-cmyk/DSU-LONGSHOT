"""Ventana principal: Conexión, Control, Calibración, Ajustes, Perfiles, Jugar."""
import copy
import os
import queue
import time

from PySide6.QtCore import QProcess, Qt, QTimer
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QFileDialog, QFrame, QGridLayout,
    QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit, QListWidget, QMainWindow, QMenu,
    QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QRadioButton, QScrollArea, QSlider,
    QSpinBox, QStackedWidget, QSystemTrayIcon, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from app.core import calibracion as C
from app.core import controles as CT
from app.core import perfiles as PF
from app.core import salidas as S
from app.core.motor import BUSCANDO, CONECTADO, DETENIDO, SIN_DATOS, Motor
from app.core.transformar import stick_logico


def stick_fisico(perfil, crudo, cual):
    """Stick físico del teléfono ya rotado con su matriz (sin zona muerta ni intercambio)."""
    cfg = perfil["stick" if cual == "izq" else "stick_der"]
    x, y = (crudo.lx, crudo.ly) if cual == "izq" else (crudo.rx, crudo.ry)
    return stick_logico(x, y, dict(cfg, zona_muerta=0.0, rango=1.0))
from app import i18n
from app.i18n import T
from app.ui.widgets import (AMBAR, MORADO, ROJO, TENUE, VERDE, JoyConWidget, MovimientoWidget,
                            Semaforo, StickWidget)

VERSION = "1.2.1"


def fuente_a_fisicos(perfil):
    """bit del protocolo -> botones físicos que lo mandan (para iluminar el dibujo)."""
    ctrl = CT.control(perfil.get("control"))
    fis = dict(ctrl.fisicos_por_defecto())
    fis.update(perfil.get("fisicos") or {})
    inv = ctrl.fuente_a_fisicos(fis)
    if ctrl.id == "joycon-izq":                      # L llega idéntico a SL
        inv.setdefault(fis.get("SL", "L1"), []).append("L")
    return inv


def nombre_fuente(perfil, bit):
    ctrl = CT.control(perfil.get("control"))
    fis = dict(ctrl.fisicos_por_defecto())
    fis.update(perfil.get("fisicos") or {})
    return ctrl.nombre_fuente(fis, bit)


def pintar_vivo(dibujo, perfil, crudo, log):
    """Ilumina lo presionado y mueve los sticks del dibujo."""
    inv = fuente_a_fisicos(perfil)
    pres = set()
    for fuente in crudo.presionados():
        pres.update(inv.get(fuente, []))
    dibujo.presionados = pres
    if CT.control(perfil.get("control")).stick_vertical:
        c = perfil["stick"]["centro"]
        dibujo.stick = ((crudo.lx - c[0]) / 127.0, (crudo.ly - c[1]) / 127.0)
    else:
        # el dibujo muestra cada stick físico donde está en el teléfono
        dibujo.stick = stick_fisico(perfil, crudo, "izq")
        dibujo.stick_der = stick_fisico(perfil, crudo, "der")


MODELOS = {0: "—", 1: "DS3", 2: "DS4", 3: i18n.L("genérico", "generic")}
CONEXIONES = {0: "—", 1: "USB", 2: "Bluetooth"}
BATERIA = {0: "—", 1: i18n.L("agotándose", "dying"), 2: i18n.L("baja", "low"), 3: i18n.L("media", "medium"),
           4: i18n.L("alta", "high"), 5: i18n.L("llena", "full"),
           0xEE: i18n.L("cargando", "charging"), 0xEF: i18n.L("cargada", "charged")}
PAGINAS_EN = {"Conexión": "Connection", "Control": "Controller", "Calibración": "Calibration",
              "Ajustes": "Settings", "Perfiles": "Profiles", "Jugar": "Play"}


def pixmap_icono(tam=64):
    """El control morado (ícono de la app) dibujado a `tam` píxeles."""
    pm = QPixmap(tam, tam)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.scale(tam / 64.0, tam / 64.0)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor("#8d4fc7"))
    p.drawRoundedRect(6, 14, 52, 36, 12, 12)
    p.setBrush(QColor("#1d1030"))
    p.drawEllipse(14, 23, 18, 18)
    p.setBrush(QColor("#ffffff"))
    for x, y in ((44, 24), (38, 31), (50, 31), (44, 38)):
        p.drawEllipse(x - 3, y - 3, 6, 6)
    p.end()
    return pm


def icono_app():
    ico = QIcon()
    for tam in (16, 24, 32, 48, 64, 128, 256):
        ico.addPixmap(pixmap_icono(tam))
    return ico


def tarjeta(*widgets, titulo=None):
    f = QFrame()
    f.setObjectName("tarjeta")
    lay = QVBoxLayout(f)
    lay.setContentsMargins(16, 14, 16, 14)
    lay.setSpacing(8)
    if titulo:
        t = QLabel(titulo)
        t.setStyleSheet("font-weight: 600; color: #c9b2ea;")
        lay.addWidget(t)
    for w in widgets:
        if isinstance(w, QWidget):
            lay.addWidget(w)
        else:
            lay.addLayout(w)
    return f


def fila(*widgets, estirar=True):
    lay = QHBoxLayout()
    lay.setSpacing(8)
    for w in widgets:
        if w is None:
            lay.addStretch(1)
        elif isinstance(w, QWidget):
            lay.addWidget(w)
        else:
            lay.addLayout(w)
    if estirar and None not in widgets:
        lay.addStretch(1)
    return lay


def etiqueta(texto, nombre=None, envolver=True):
    lab = QLabel(texto)
    if nombre:
        lab.setObjectName(nombre)
    lab.setWordWrap(envolver)
    return lab


class Pagina(QWidget):
    def __init__(self, v, titulo, sub):
        super().__init__()
        self.v = v
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(26, 20, 26, 18)
        self.lay.setSpacing(12)
        self.lay.addWidget(etiqueta(titulo, "titulo"))
        self.lay.addWidget(etiqueta(sub, "sub"))

    def refrescar(self, f):
        pass

    def al_mostrar(self):
        pass

    def al_cambiar_perfil(self):
        pass


# ====================================================================== Conexión
class PaginaConexion(Pagina):
    def __init__(self, v):
        super().__init__(v, T("Conexión", "Connection"),
                         T("Abre la app DSU en tu teléfono (por ejemplo DSU Controller) y escribe aquí la IP que "
                           "muestra.", "Open the DSU app on your phone (for example DSU Controller) and type the IP "
                           "address it shows."))
        a = v.ajustes
        self.ip = QComboBox()
        self.ip.setEditable(True)
        self.ip.setMinimumWidth(200)
        for r in [a["ip"]] + [x for x in a.get("recientes", []) if x != a["ip"]]:
            self.ip.addItem(r)
        self.puerto = QSpinBox()
        self.puerto.setRange(1, 65535)
        self.puerto.setValue(int(a["puerto"]))
        self.boton = QPushButton(T("Conectar", "Connect"))
        self.boton.setObjectName("primario")
        self.boton.clicked.connect(self._alternar)
        self.ip.lineEdit().returnPressed.connect(self._alternar)
        self.auto = QCheckBox(T("Conectar sola al abrir la app", "Connect automatically on startup"))
        self.auto.setChecked(bool(a.get("conectar_al_abrir")))
        self.auto.toggled.connect(self._guardar_auto)
        self.lay.addWidget(tarjeta(
            fila(QLabel(T("IP del dispositivo", "Device IP")), self.ip, QLabel(T("Puerto", "Port")),
                 self.puerto, self.boton),
            self.auto, titulo=T("Dispositivo DSU", "DSU device")))

        self.luz = Semaforo()
        self.estado = etiqueta(T("Sin conectar", "Not connected"), "grande")
        g = QGridLayout()
        g.setHorizontalSpacing(26)
        self.datos = {}
        for i, (k, nombre) in enumerate([("slot", "Slot"), ("pps", T("Paquetes por segundo", "Packets per second")),
                                         ("mps", T("Muestras de movimiento por segundo", "Motion samples per second")),
                                         ("modelo", T("El dispositivo se reporta como", "Device reports itself as")),
                                         ("bateria", T("Batería", "Battery")),
                                         ("malos", T("Paquetes dañados", "Corrupted packets"))]):
            g.addWidget(etiqueta(nombre, "sub"), i // 3 * 2, i % 3)
            self.datos[k] = etiqueta("—", "dato")
            g.addWidget(self.datos[k], i // 3 * 2 + 1, i % 3)
        self.nota_hz = etiqueta("", "sub")
        self.lay.addWidget(tarjeta(fila(self.luz, self.estado), g, self.nota_hz, titulo=T("Estado en vivo", "Live status")))

        self.diag = etiqueta("", "aviso")
        self.diag.setTextFormat(Qt.RichText)
        self.t_diag = tarjeta(self.diag, titulo=T("No llegan datos — revisa esto", "No data arriving — check this"))
        self.t_diag.hide()
        self.lay.addWidget(self.t_diag)

        self.vigem = etiqueta("", None)
        self.b_vigem = QPushButton(T("Instalar ViGEmBus", "Install ViGEmBus"))
        self.b_vigem.clicked.connect(self._instalar_vigem)
        self.b_revisar = QPushButton(T("Volver a revisar", "Check again"))
        self.b_revisar.clicked.connect(self.revisar_vigem)
        self.salida_inst = QPlainTextEdit()
        self.salida_inst.setReadOnly(True)
        self.salida_inst.setMaximumHeight(110)
        self.salida_inst.hide()
        self.lay.addWidget(tarjeta(self.vigem, fila(self.b_vigem, self.b_revisar), self.salida_inst,
                                   titulo=T("Control virtual (driver ViGEmBus)", "Virtual controller (ViGEmBus driver)")))
        self.lay.addStretch(1)
        self._t_conexion = 0.0
        self._proc = None
        self.revisar_vigem()

    def _guardar_auto(self, v):
        self.v.ajustes["conectar_al_abrir"] = bool(v)
        PF.guardar_ajustes(self.v.ajustes)

    def revisar_vigem(self):
        S._vg = None if S._vg is None else S._vg
        ok, msg = S.estado_vigem()
        self.v.vigem_ok = ok
        if ok:
            self.vigem.setText(T("✓ ViGEmBus está instalado y funcionando. La app puede crear el control virtual.",
                                 "✓ ViGEmBus is installed and working. The app can create the virtual controller."))
            self.vigem.setObjectName("ok")
            self.b_vigem.hide()
        else:
            self.vigem.setText(T(
                "✗ No se pudo crear el control virtual. Falta el driver ViGEmBus (o Windows necesita "
                "reiniciarse después de instalarlo).\n"
                "Pulsa «Instalar ViGEmBus», acepta el aviso de Windows, REINICIA la PC y vuelve a abrir la app.\n"
                f"Detalle: {msg}",
                "✗ Could not create the virtual controller. The ViGEmBus driver is missing (or Windows must be "
                "restarted after installing it).\n"
                "Click «Install ViGEmBus», accept the Windows prompt, RESTART the PC and open the app again.\n"
                f"Details: {msg}"))
            self.vigem.setObjectName("error")
            self.b_vigem.show()
        self.vigem.style().unpolish(self.vigem)
        self.vigem.style().polish(self.vigem)

    def _instalar_vigem(self):
        self.salida_inst.show()
        self.salida_inst.setPlainText(T("Ejecutando: winget install ViGEm.ViGEmBus ...\n"
                                        "(Windows va a pedir permiso de administrador)\n",
                                        "Running: winget install ViGEm.ViGEmBus ...\n"
                                        "(Windows will ask for administrator permission)\n"))
        self._proc = QProcess(self)
        self._proc.setProcessChannelMode(QProcess.MergedChannels)
        self._proc.readyReadStandardOutput.connect(
            lambda: self.salida_inst.appendPlainText(
                bytes(self._proc.readAllStandardOutput()).decode("utf-8", "replace").strip()))
        self._proc.finished.connect(self._fin_instalacion)
        self._proc.errorOccurred.connect(lambda _e: self._fin_instalacion(-1, None))
        self._proc.start("winget", ["install", "--id", "ViGEm.ViGEmBus", "-e",
                                    "--accept-source-agreements", "--accept-package-agreements"])

    def _fin_instalacion(self, codigo, _estado):
        if codigo == 0:
            self.salida_inst.appendPlainText(T("\n✓ Instalado. REINICIA Windows y vuelve a abrir la app.",
                                               "\n✓ Installed. RESTART Windows and open the app again."))
        else:
            self.salida_inst.appendPlainText(T(
                "\nNo se pudo instalar con winget. Descarga e instala a mano "
                "ViGEmBus_1.22.0_x64_x86_arm64.exe desde:\n"
                "https://github.com/nefarius/ViGEmBus/releases/tag/v1.22.0\ny luego reinicia Windows.",
                "\nCould not install with winget. Download and install "
                "ViGEmBus_1.22.0_x64_x86_arm64.exe manually from:\n"
                "https://github.com/nefarius/ViGEmBus/releases/tag/v1.22.0\nand then restart Windows."))

    def _alternar(self):
        if self.v.motor.estado == DETENIDO:
            self.conectar()
        else:
            self.v.motor.detener()
            self.t_diag.hide()

    def conectar(self):
        ip = self.ip.currentText().strip()
        if not ip:
            return
        a = self.v.ajustes
        a["ip"], a["puerto"] = ip, self.puerto.value()
        a["recientes"] = ([ip] + [x for x in a.get("recientes", []) if x != ip])[:6]
        PF.guardar_ajustes(a)
        self._t_conexion = time.monotonic()
        self.v.motor.conectar(ip, self.puerto.value(), self.v.perfil)

    def refrescar(self, f):
        self.boton.setText(T("Conectar", "Connect") if f.estado == DETENIDO else T("Desconectar", "Disconnect"))
        self.ip.setEnabled(f.estado == DETENIDO)
        self.puerto.setEnabled(f.estado == DETENIDO)
        textos = {DETENIDO: (T("Sin conectar", "Not connected"), TENUE),
                  BUSCANDO: (T("Buscando el dispositivo…", "Looking for the device…"), AMBAR),
                  CONECTADO: (T("Conectado: llegan datos", "Connected: receiving data"), VERDE),
                  SIN_DATOS: (T("Se dejaron de recibir datos — reintentando sola…",
                                "Data stopped arriving — retrying automatically…"), ROJO)}
        t, color = textos[f.estado]
        self.estado.setText(t)
        self.luz.poner(color)
        con = f.estado == CONECTADO
        self.datos["slot"].setText(str(f.slot) if con else "—")
        self.datos["pps"].setText(str(f.pps) if con else "—")
        self.datos["mps"].setText(str(f.mps) if con else "—")
        self.datos["modelo"].setText(f"{MODELOS.get(f.modelo, f.modelo)} {T('por', 'via')} "
                                     f"{CONEXIONES.get(f.conexion, f.conexion)}" if con else "—")
        self.datos["bateria"].setText(str(BATERIA.get(f.bateria, f.bateria)) if con else "—")
        self.datos["malos"].setText(str(f.paquetes_malos))
        if con and f.mps:
            if f.mps < 20:
                self.nota_hz.setText(T(f"⚠ Solo llegan {f.mps} muestras de movimiento por segundo: el apuntado se va a "
                                       "sentir brincado. Acerca el teléfono al router o usa Wi-Fi de 5 GHz.",
                                       f"⚠ Only {f.mps} motion samples per second: aiming will feel choppy. Move the "
                                       "phone closer to the router or use 5 GHz Wi-Fi."))
            elif f.mps < 50:
                self.nota_hz.setText(T(f"El dispositivo manda el movimiento a ~{f.mps} Hz (un Joy-Con real anda en "
                                       "60–200 Hz). Se puede jugar; solo se siente un poco menos fino.",
                                       f"The device sends motion at ~{f.mps} Hz (a real Joy-Con runs at 60–200 Hz). "
                                       "It is playable; it just feels a bit less smooth."))
            else:
                self.nota_hz.setText(T("Frecuencia de movimiento buena.", "Good motion rate."))
        else:
            self.nota_hz.setText("")
        sin = f.estado in (BUSCANDO, SIN_DATOS) and time.monotonic() - self._t_conexion > 4
        if sin:
            extra = T("<br>• Error de red de Windows: ", "<br>• Windows network error: ") + f.error_red \
                if f.error_red else ""
            ip, puerto = self.v.ajustes["ip"], self.v.ajustes["puerto"]
            self.diag.setText(T(
                f"No ha llegado nada desde <b>{ip}:{puerto}</b>.<br>"
                "• ¿La app DSU está abierta y en primer plano en el teléfono? (si se bloquea la "
                "pantalla deja de mandar)<br>"
                "• ¿La IP y el puerto son los que muestra la app? (cambian si el teléfono se reconecta al Wi-Fi)<br>"
                "• ¿La PC y el teléfono están en la <b>misma red Wi-Fi</b>? (no datos móviles, no red de invitados)<br>"
                "• Firewall de Windows: si al abrir esta app salió un aviso, elige <b>Permitir</b> en redes "
                f"privadas.<br>• Prueba desde la PC: <code>ping {ip}</code>",
                f"Nothing has arrived from <b>{ip}:{puerto}</b>.<br>"
                "• Is the DSU app open and in the foreground on the phone? (it stops sending when the screen "
                "locks)<br>"
                "• Are the IP and port the ones the app shows? (they change if the phone reconnects to Wi-Fi)<br>"
                "• Are the PC and the phone on the <b>same Wi-Fi network</b>? (no mobile data, no guest network)<br>"
                "• Windows Firewall: if a prompt appeared when this app opened, choose <b>Allow</b> on private "
                f"networks.<br>• Try from the PC: <code>ping {ip}</code>") + extra)
        self.t_diag.setVisible(sin)


# ======================================================================= Control
class PaginaControl(Pagina):
    def __init__(self, v):
        super().__init__(v, T("Tipo de control", "Controller type"),
                         T("Elige el mismo control que tienes elegido en la app DSU del teléfono y cómo lo vas a "
                           "sostener.", "Pick the same controller layout you selected in the DSU app on your phone "
                           "and how you will hold it."))
        self.r_ctrl = {}
        textos = {"joycon-izq": T("Joy-Con izquierdo — medio control (Longshot)",
                                  "Left Joy-Con — half controller (Longshot)"),
                  "wii-classic": T("Wii Classic — control completo: 2 sticks, a b x y, L R ZL ZR, cruceta",
                                   "Wii Classic — full controller: 2 sticks, a b x y, L R ZL ZR, d-pad"),
                  "wii-remote": T("Wii Remote — cruceta, A, B, 1, 2 y movimiento",
                                  "Wii Remote — d-pad, A, B, 1, 2 and motion")}
        for cid in CT.CONTROLES:
            r = QRadioButton(textos[cid])
            r.toggled.connect(lambda on, c=cid: on and self._cambio_control(c))
            self.r_ctrl[cid] = r
        self.nota_ctrl = etiqueta("", "sub")
        self.lay.addWidget(tarjeta(*self.r_ctrl.values(), self.nota_ctrl, titulo=T("Control", "Controller")))

        self.o_lado = QRadioButton(T("De lado — para cualquier juego (Longshot)",
                                     "Sideways — for any game (Longshot)"))
        self.o_fis = QRadioButton(T("Física (vertical) — para emuladores de Switch por servidor DSU",
                                    "Physical (upright) — for Switch emulators via the DSU server"))
        self.dibujo = JoyConWidget()
        self.dibujo.setMinimumHeight(240)
        self.explica = etiqueta("", "sub")
        col = QVBoxLayout()
        col.addWidget(self.o_lado)
        col.addWidget(self.o_fis)
        col.addWidget(self.explica)
        col.addStretch(1)
        h = QHBoxLayout()
        h.addLayout(col, 1)
        h.addWidget(self.dibujo, 1)
        self.lay.addWidget(tarjeta(h, titulo=T("Orientación", "Orientation")), 1)
        self.o_lado.toggled.connect(self._cambio)
        self.al_cambiar_perfil()

    def al_cambiar_perfil(self):
        p = self.v.perfil
        lado = p["orientacion"] == "lado"
        ctrl = CT.control(p.get("control"))
        for cid, r in self.r_ctrl.items():
            r.blockSignals(True)
            r.setChecked(cid == ctrl.id)
            r.blockSignals(False)
        self.o_lado.blockSignals(True)
        self.o_lado.setChecked(lado)
        self.o_fis.setChecked(not lado)
        self.o_lado.blockSignals(False)
        es_joycon = ctrl.id == "joycon-izq"
        self.o_lado.setVisible(es_joycon)
        self.o_fis.setVisible(es_joycon)
        self.nota_ctrl.setText(str(ctrl.nota) + ("" if ctrl.verificado else T(
            "  Botones según la documentación de la app DSU Controller; aún no probado con un teléfono real.",
            "  Buttons follow the DSU Controller app documentation; not yet tested with a real phone.")))
        self._pintar()

    def _pintar(self):
        p = self.v.perfil
        lado = p["orientacion"] == "lado"
        self.dibujo.poner_perfil(p)
        cid = CT.control(p.get("control")).id
        if cid == "wii-classic":
            self.dibujo.etiquetas = {"C_A": "○ (A)", "C_B": "✕ (B)", "C_X": "△ (X)", "C_Y": "□ (Y)",
                                     "AL": "L3", "AR": "R3", "VERDE": "Home"}
            self.explica.setText(T(
                "Acuesta el teléfono con la parte de arriba a tu IZQUIERDA: ZL y ZR quedan arriba y los dos sticks "
                "abajo, como un control normal.\n\nCada botón sale como lo que dice: a = A, b = B, x = X, y = Y, "
                "L/R, ZL/ZR, cruceta, − + y Home. AL y AR son el clic de los sticks (L3/R3). Sirve para juegos que "
                "piden un control completo.",
                "Hold the phone landscape with its top to your LEFT: ZL and ZR end up on top and both sticks at "
                "the bottom, like a regular gamepad.\n\nEach button is sent as what it says: a = A, b = B, x = X, "
                "y = Y, L/R, ZL/ZR, d-pad, − + and Home. AL and AR are the stick clicks (L3/R3). Use it for games "
                "that need a full controller."))
        elif cid == "wii-remote":
            self.dibujo.etiquetas = {"W_A": "✕", "W_B": "□", "UNO": "△", "DOS": "○"}
            self.explica.setText(T(
                "El teléfono vertical, apuntando a la pantalla como un Wiimote.\n\nSe manda igual que el perfil de "
                "Dolphin de la app: A = ✕, B = □, 1 = △, 2 = ○, cruceta, − + y Home. En Dolphin usa la salida "
                "«Servidor DSU» (o el DS4) y mapea ahí cada botón.",
                "The phone upright, pointing at the screen like a Wiimote.\n\nSent the same way as the app's "
                "Dolphin profile: A = ✕, B = □, 1 = △, 2 = ○, d-pad, − + and Home. In Dolphin use the «DSU server» "
                "output (or the DS4) and map each button there."))
        elif lado:
            self.dibujo.etiquetas = {"F_IZQ": "✕ (B)", "F_ABAJO": "○ (A)", "F_ARRIBA": "□ (Y)", "F_DER": "△ (X)"}
            self.explica.setText(T(
                "Gira el teléfono a la izquierda: SL y SR quedan arriba, el stick a la izquierda y las flechas a la "
                "derecha, como un control normal.\n\nEl stick se rota solo, las 4 flechas se vuelven los 4 botones "
                "de cara por su posición, SL/SR son L/R, ZL es ZL y el ícono verde hace de ZR.",
                "Turn the phone to the left: SL and SR end up on top, the stick on the left and the arrows on the "
                "right, like a regular gamepad.\n\nThe stick is rotated for you, the 4 arrows become the 4 face "
                "buttons by position, SL/SR are L/R, ZL is ZL and the green icon acts as ZR."))
        else:
            self.dibujo.etiquetas = {}
            self.explica.setText(T(
                "El teléfono vertical, como un Joy-Con suelto. Todo se pasa tal cual (flechas = cruceta, movimiento "
                "sin rotar) y el emulador de Switch hace la rotación. Úsala con la salida «Servidor DSU».",
                "The phone upright, like a single Joy-Con. Everything is passed through (arrows = d-pad, motion "
                "not rotated) and the Switch emulator does the rotation. Use it with the «DSU server» output."))
        self.dibujo.update()

    def _cambio(self, _=None):
        if CT.control(self.v.perfil.get("control")).id != "joycon-izq":
            return
        nueva = "lado" if self.o_lado.isChecked() else "fisica"
        self._restablecer(self.v.perfil["control"], nueva, T("Cambiar orientación", "Change orientation"))

    def _cambio_control(self, cid):
        if cid == self.v.perfil.get("control"):
            return
        self._restablecer(cid, None, T("Cambiar de control", "Change controller"))

    def _restablecer(self, cid, orientacion, titulo):
        p = self.v.perfil
        if orientacion == p["orientacion"] and cid == p.get("control"):
            return
        if p.get("calibrado"):
            r = QMessageBox.question(self, titulo, T(
                "Esto restablece el stick, el mapeo y los ejes de movimiento de ESTE perfil, y hay que volver a "
                "calibrar. (Si quieres conservar el perfil actual, primero usa Perfiles → Nuevo perfil.) ¿Continuar?",
                "This resets the stick, button mapping and motion axes of THIS profile, and you will need to "
                "calibrate again. (To keep the current profile, first use Profiles → New profile.) Continue?"))
            if r != QMessageBox.Yes:
                self.al_cambiar_perfil()
                return
        nombre = p["nombre"]
        if cid != p.get("control") and nombre == PF.NOMBRES_CONTROL.get(p.get("control")):
            nombre = str(PF.NOMBRES_CONTROL[cid])
        base = PF.perfil_por_defecto(orientacion, nombre, cid)
        nueva = base["orientacion"]
        base["slot"] = p.get("slot")
        base["salidas"] = dict(p["salidas"])
        if nueva == "fisica" and cid == "joycon-izq":
            base["salidas"].update(dsu=True)
        base["gyro"]["bias"] = list(p["gyro"]["bias"])
        self.v.poner_perfil(base, sucio=True)


# =================================================================== Calibración
GRUPOS = [("boton", i18n.L("Botones", "Buttons"), "boton:"), ("stick", "Stick", "stick:centro"),
          ("stickd", i18n.L("Stick derecho", "Right stick"), "stickd:centro"),
          ("reposo", i18n.L("Reposo", "Rest"), "reposo"), ("gesto", i18n.L("Giros", "Rotations"), "gesto:pitch")]


class PaginaCalibracion(Pagina):
    def __init__(self, v):
        super().__init__(v, T("Calibración guiada", "Guided calibration"),
                         T("Sigue el dibujo: se ilumina lo que hay que tocar o mover. Tarda unos 2 minutos.",
                           "Follow the drawing: whatever you must press or move lights up. Takes about 2 minutes."))
        self.asis = None
        self.cola = queue.SimpleQueue()
        self.ang_verif = [0.0, 0.0, 0.0]
        self._prev = None

        self.dibujo = JoyConWidget()
        self.mov = MovimientoWidget()
        self.mov.hide()
        self.pila_vis = QStackedWidget()
        self.pila_vis.addWidget(self.dibujo)
        self.pila_vis.addWidget(self.mov)

        self.paso_txt = etiqueta("", "grande")
        self.detalle = etiqueta("", "sub")
        self.aviso = etiqueta("", "aviso")
        self.barra = QProgressBar()
        self.barra.setRange(0, 1000)
        self.barra.setTextVisible(False)
        self.b_iniciar = QPushButton(T("Empezar calibración", "Start calibration"))
        self.b_iniciar.setObjectName("primario")
        self.b_iniciar.clicked.connect(self.iniciar)
        self.b_omitir = QPushButton(T("Omitir este paso", "Skip this step"))
        self.b_omitir.clicked.connect(lambda: self.asis and self.asis.omitir())
        self.b_aceptar = QPushButton(T("Sí toqué el correcto: reasignar", "I pressed the right one: remap"))
        self.b_aceptar.setObjectName("escucha")
        self.b_aceptar.clicked.connect(lambda: self.asis and self.asis.aceptar_inesperado())
        self.b_cero = QPushButton(T("Volver a intentar este giro", "Retry this rotation"))
        self.b_cero.clicked.connect(lambda: self.asis and self.asis.reiniciar_gesto())
        self.b_cancelar = QPushButton(T("Cancelar", "Cancel"))
        self.b_cancelar.clicked.connect(self.cancelar)
        self.b_guardar = QPushButton(T("Guardar perfil", "Save profile"))
        self.b_guardar.setObjectName("primario")
        self.b_guardar.clicked.connect(self._guardar)
        self.b_ir_jugar = QPushButton(T("Ir a Jugar →", "Go to Play →"))
        self.b_ir_jugar.clicked.connect(lambda: self.v.ir("Jugar"))

        self.lista = QVBoxLayout()
        self.marcas = {}
        self.b_rep = {}
        for gid, nombre, primero in GRUPOS:
            m = etiqueta("○ " + nombre)
            b = QPushButton(T("Repetir", "Repeat"))
            b.setFixedWidth(76)
            b.clicked.connect(lambda _=False, pid=primero: self.repetir(pid))
            self.marcas[gid], self.b_rep[gid] = m, b
            self.filas = getattr(self, "filas", {})
            w = QWidget()
            w.setLayout(fila(m, None, b, estirar=False))
            w.layout().setContentsMargins(0, 0, 0, 0)
            self.filas[gid] = w
            self.lista.addWidget(w)
        self.stick_w = StickWidget()
        self.stick_w.setFixedSize(130, 130)
        self.botones_txt = etiqueta("", "dato")

        izq = QVBoxLayout()
        izq.addWidget(self.paso_txt)
        izq.addWidget(self.detalle)
        izq.addWidget(self.barra)
        izq.addWidget(self.aviso)
        izq.addWidget(self.pila_vis, 1)
        izq.addLayout(fila(self.b_iniciar, self.b_aceptar, self.b_cero, self.b_omitir, None,
                           self.b_guardar, self.b_ir_jugar, self.b_cancelar, estirar=False))
        der = QVBoxLayout()
        der.addWidget(tarjeta(self.lista, titulo=T("Pasos", "Steps")))
        der.addWidget(tarjeta(fila(self.stick_w), self.botones_txt,
                              titulo=T("En vivo (ya calibrado)", "Live (calibrated)")))
        der.addStretch(1)
        h = QHBoxLayout()
        h.addLayout(izq, 3)
        h.addLayout(der, 1)
        self.lay.addLayout(h, 1)
        self._modo("inicio")
        self._grupos_visibles()

    # ---- flujo
    def _oyente(self, e):
        self.cola.put(e)

    def iniciar(self):
        if not self._requiere_conexion():
            return
        self.asis = C.Asistente(self.v.perfil)
        self._enganchar()
        self._modo("pasos")

    def repetir(self, paso_id):
        if not self._requiere_conexion():
            return
        if paso_id == "boton:":
            paso_id += CT.control(self.v.perfil.get("control")).botones[0].id
        if self.asis is None:
            self.asis = C.Asistente(self.v.perfil)
        self.asis.perfil = copy.deepcopy(self.v.perfil)
        self.asis.ir_a(paso_id, unico=True)
        self._enganchar()
        self._modo("pasos")

    def _requiere_conexion(self):
        if self.v.motor.estado != CONECTADO:
            QMessageBox.information(self, T("Sin conexión", "Not connected"),
                                    T("Primero conecta con el dispositivo en la página «Conexión» "
                                      "(tienen que estar llegando datos).",
                                      "First connect to the device on the «Connection» page "
                                      "(data must be arriving)."))
            self.v.ir("Conexión")
            return False
        return True

    def _enganchar(self):
        while not self.cola.empty():
            self.cola.get_nowait()
        self.v.motor.dejar_de_escuchar(self._oyente)
        self.v.motor.escuchar(self._oyente)

    def cancelar(self):
        self.v.motor.dejar_de_escuchar(self._oyente)
        self.asis = None
        self._modo("inicio")

    def _terminar(self):
        self.v.motor.dejar_de_escuchar(self._oyente)
        perfil = self.asis.aplicar(self.v.perfil)
        self.v.poner_perfil(perfil, sucio=True)
        self.ang_verif = [0.0, 0.0, 0.0]
        self._prev = None
        self._modo("verificar")

    def _guardar(self):
        self.v.guardar_perfil()

    def _modo(self, modo):
        self.modo = modo
        pasos = modo == "pasos"
        self.b_iniciar.setVisible(not pasos)
        self.b_iniciar.setText(T("Empezar calibración", "Start calibration") if modo == "inicio"
                               else T("Repetir todo", "Repeat everything"))
        self.b_omitir.setVisible(pasos)
        self.b_cancelar.setVisible(pasos)
        self.b_aceptar.setVisible(False)
        self.b_cero.setVisible(False)
        self.b_guardar.setVisible(modo == "verificar")
        self.b_ir_jugar.setVisible(modo == "verificar")
        self.barra.setVisible(pasos)
        for b in self.b_rep.values():
            b.setEnabled(not pasos)
        self.dibujo.resaltado = None
        self.dibujo.flecha_stick = None
        self.dibujo.hechos = set()
        if modo == "inicio":
            self.pila_vis.setCurrentWidget(self.dibujo)
            cal = self.v.perfil.get("calibrado")
            self.paso_txt.setText(T("Este perfil ya está calibrado", "This profile is calibrated") if cal else
                                  T("Este perfil aún no está calibrado", "This profile is not calibrated yet"))
            self.detalle.setText(
                T("Puedes repetir todo o solo un grupo de pasos con los botones «Repetir».",
                  "You can repeat everything or just one group of steps with the «Repeat» buttons.") if cal else
                T("Sostén el teléfono como vas a jugar y pulsa «Empezar calibración». Sin calibrar, los botones y el "
                  "stick ya funcionan con los valores por defecto, pero el movimiento puede salir desviado o al revés.",
                  "Hold the phone the way you will play and click «Start calibration». Without calibrating, buttons "
                  "and stick already work with the defaults, but motion may be off or inverted."))
            self.aviso.setText("")
        elif modo == "verificar":
            self.pila_vis.setCurrentWidget(self.mov)
            self.paso_txt.setText(T("Verificación: mueve el control y toca botones",
                                    "Check: move the controller and press buttons"))
            self.detalle.setText(T(
                "El dibujo debe moverse igual que tu teléfono: apuntar arriba lo sube, apuntar a la izquierda lo "
                "lleva a la izquierda, inclinarlo lo inclina. Si algo sale mal, repite solo ese grupo. "
                "Si todo está bien, guarda el perfil.",
                "The drawing must move like your phone: pointing up raises it, pointing left moves it left, tilting "
                "tilts it. If something is wrong, repeat just that group. If everything looks right, save the "
                "profile."))
            self.aviso.setText(getattr(self.asis, "aviso_accel", "") if self.asis else "")

    def _grupos_visibles(self):
        ctrl = CT.control(self.v.perfil.get("control"))
        dos = len(ctrl.sticks) > 1
        vis = {"boton": True, "stick": "izq" in ctrl.sticks, "stickd": "der" in ctrl.sticks,
               "reposo": True, "gesto": True}
        for gid, w in self.filas.items():
            w.setVisible(vis[gid])
        self.nombres_grupo = {g: n for g, n, _ in GRUPOS}
        if dos:
            self.nombres_grupo["stick"] = T("Stick izquierdo", "Left stick")
        self.dibujo.poner_perfil(self.v.perfil)
        self.mov.orientacion = self.v.perfil["orientacion"]

    def al_mostrar(self):
        self._grupos_visibles()
        if self.modo != "pasos":
            self._modo("inicio" if self.modo == "inicio" else self.modo)

    def al_cambiar_perfil(self):
        if self.modo == "inicio":
            self.asis = None
            self._modo("inicio")
        self._grupos_visibles()

    # ---- dibujo
    def refrescar(self, f):
        self.dibujo.fase = (time.monotonic() * 1.3) % 1.0
        crudo, log = f.crudo, f.logico
        vivo = f.estado == CONECTADO and crudo is not None
        if vivo:
            pintar_vivo(self.dibujo, self.v.perfil, crudo, log)
            self.stick_w.x, self.stick_w.y = log.lx, log.ly
            self.stick_w.zona_muerta = self.v.perfil["stick"]["zona_muerta"]
            self.stick_w.rango = self.v.perfil["stick"]["rango"]
            self.botones_txt.setText(" ".join(log.presionados()) or "—")
        else:
            self.dibujo.presionados = set()
        self.stick_w.update()

        if self.modo == "pasos" and self.asis:
            n = 0
            while n < 400:
                try:
                    e = self.cola.get_nowait()
                except queue.Empty:
                    break
                self.asis.alimentar(e)
                n += 1
                if self.asis.terminado:
                    break
            if self.asis.terminado:
                self._terminar()
            else:
                self._pintar_paso(f)
        elif self.modo == "verificar" and vivo:
            if self._prev is not None and crudo is not self._prev:
                dt = C.dt_entre(self._prev, crudo) or 0.0
                dt = min(dt, 0.1)
                for i in range(3):
                    if abs(log.gyro[i]) > 2.5 * max(1.0, self.v.perfil["gyro"]["ruido"]):
                        self.ang_verif[i] += log.gyro[i] * dt
                    else:
                        self.ang_verif[i] *= 0.985        # vuelve sola al centro en reposo
            self._prev = crudo
            self.mov.angulos = list(self.ang_verif)
            self.mov.meta = None
            self.mov.update()
        self._pintar_marcas()
        self.dibujo.update()

    def _pintar_marcas(self):
        actual = self.asis.paso.id.split(":")[0] if (self.asis and self.modo == "pasos") else None
        cal = self.v.perfil.get("calibrado")
        for gid, _n, _ in GRUPOS:
            nombre = getattr(self, "nombres_grupo", {}).get(gid, _n)
            if gid == actual:
                txt, color = "▶ " + nombre, "#ffb020"
            elif self.asis and self._grupo_hecho(gid) or (cal and self.modo != "pasos"):
                txt, color = "✓ " + nombre, "#2fbf71"
            else:
                txt, color = "○ " + nombre, "#9a9aa6"
            self.marcas[gid].setText(txt)
            self.marcas[gid].setStyleSheet(f"color: {color};")

    def _grupo_hecho(self, gid):
        pasos = [p for p in self.asis.pasos if p.id.split(":")[0] == gid]
        return all(p.estado == C.HECHO for p in pasos)

    def _pintar_paso(self, f):
        a, p = self.asis, self.asis.paso
        self.barra.setValue(int(p.progreso * 1000))
        self.aviso.setText(p.aviso or a.error or
                           (T("⚠ No llegan datos del dispositivo", "⚠ No data from the device")
                            if f.estado != CONECTADO else ""))
        self.b_aceptar.setVisible(p.tipo == "boton" and bool(p.info.get("inesperado")))
        self.b_cero.setVisible(p.tipo == "gesto")
        self.dibujo.hechos = {x.info["fisico"] for x in a.pasos if x.tipo == "boton" and x.estado == C.HECHO}
        self.dibujo.flecha_stick = None
        self.dibujo.resaltado = None
        indice = a.indice + 1
        paso_n = T(f"Paso {indice} de {len(a.pasos)}", f"Step {indice} of {len(a.pasos)}")
        self.paso_txt.setText(f"{p.texto}")
        if p.tipo == "boton":
            self.pila_vis.setCurrentWidget(self.dibujo)
            self.dibujo.resaltado = p.info["fisico"]
            self.detalle.setText(paso_n + T(" · Toca y suelta el botón iluminado en el teléfono.",
                                            " · Press and release the highlighted button on the phone.")
                                 + (T("  ✓ Detectado, suéltalo.", "  ✓ Detected, release it.")
                                    if p.estado == "presionado" else ""))
            self.barra.setValue(1000 if p.estado == "presionado" else 0)
        elif p.tipo == "stick_centro":
            self.pila_vis.setCurrentWidget(self.dibujo)
            self.dibujo.resaltado = "STICK" if p.info.get("cual", "izq") == "izq" else "STICK_DER"
            self.detalle.setText(paso_n + T(" · Midiendo el centro del stick.", " · Measuring the stick center."))
        elif p.tipo == "stick_dir":
            self.pila_vis.setCurrentWidget(self.dibujo)
            self.dibujo.resaltado = "STICK" if p.info.get("cual", "izq") == "izq" else "STICK_DER"
            if p.estado == "presionado":
                self.paso_txt.setText(T("✓ Detectado. Suelta el stick", "✓ Detected. Release the stick"))
            else:
                self.dibujo.flecha_stick = (0, 1) if p.info["direccion"] == "arriba" else (1, 0)
            self.detalle.setText(paso_n + T(" · «Tu arriba» y «tu derecha» son las de la pantalla del juego, tal "
                                            "como sostienes el teléfono. Si el dibujo se mueve hacia otro lado no "
                                            "importa: el asistente aprende la dirección real.",
                                            " · «Your up» and «your right» are those of the game screen, the way "
                                            "you hold the phone. If the drawing moves another way, that's fine: the "
                                            "wizard learns the real direction."))
        elif p.tipo == "reposo":
            self.pila_vis.setCurrentWidget(self.mov)
            self.mov.angulos, self.mov.meta = [0, 0, 0], None
            ruido = p.info.get("ruido")
            self.detalle.setText(paso_n + T(" · Midiendo 3 segundos", " · Measuring for 3 seconds")
                                 + (T(f" · ruido del giroscopio: {ruido:.1f}", f" · gyro noise: {ruido:.1f}")
                                    if ruido is not None else ""))
            self.mov.update()
        elif p.tipo == "gesto":
            self.pila_vis.setCurrentWidget(self.mov)
            self.detalle.setText(paso_n + f" · {p.texto} " + T(
                "Gira unos 45°, quédate quieto un momento y luego regresa. La barra avanza con el giro real.",
                "Rotate about 45°, hold still for a moment and then come back. The bar follows the real rotation."))
            self.paso_txt.setText(str(p.titulo) if p.info.get("fase") != "regresar"
                                  else T("✓ Giro detectado. Regresa a la posición normal",
                                         "✓ Rotation detected. Return to the normal position"))
            eje = {"pitch": 0, "yaw": 1, "roll": 2}[p.info["eje"]]
            ang_app = p.info.get("angulo", [0, 0, 0])
            # Aún no se conocen los ejes: se muestra el giro como si fuera el eje pedido
            mag = max(ang_app, key=abs) if ang_app else 0.0
            vis = [0.0, 0.0, 0.0]
            vis[eje] = abs(mag) * (57.3 if abs(mag) < 3 and p.info.get("avance", 0) > 0.9 else 1.0)
            self.mov.angulos = vis
            self.mov.meta = (eje, p.info.get("avance", 0.0), p.info.get("fase", "girar"))
            self.mov.update()


# ======================================================================= Ajustes
class PaginaAjustes(Pagina):
    def __init__(self, v):
        super().__init__(v, T("Ajustes", "Settings"),
                         T("Idioma, mapeo de botones, stick y movimiento. Los cambios se aplican al instante; "
                           "guarda el perfil para conservarlos.",
                           "Language, button mapping, stick and motion. Changes apply instantly; save the profile "
                           "to keep them."))
        self.escuchando = None
        self.t_escucha = 0.0
        cont = QWidget()
        cl = QVBoxLayout(cont)
        cl.setContentsMargins(0, 0, 8, 0)
        cl.setSpacing(12)
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        sc.setWidget(cont)
        self.lay.addWidget(sc, 1)

        # --- idioma
        self.idioma = QComboBox()
        for cod, nombre in i18n.IDIOMAS.items():
            self.idioma.addItem(nombre, cod)
        self.idioma.setCurrentIndex(max(0, self.idioma.findData(i18n.actual())))
        self.idioma.activated.connect(self._cambio_idioma)
        cl.addWidget(tarjeta(fila(QLabel(T("Idioma de la interfaz", "Interface language")), self.idioma),
                             titulo=T("Idioma / Language", "Language / Idioma")))

        # --- mapeo
        self.tabla = QTableWidget(len(PF.SALIDAS), 3)
        self.tabla.setHorizontalHeaderLabels([T("El juego recibe (DS4)", "Game receives (DS4)"),
                                              T("Botón del teléfono", "Phone button"), ""])
        self.tabla.verticalHeader().hide()
        self.tabla.setSelectionMode(QAbstractItemView.NoSelection)
        self.tabla.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tabla.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tabla.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.tabla.horizontalHeader().setSectionResizeMode(2, QHeaderView.Fixed)
        self.tabla.setColumnWidth(2, 84)
        self.tabla.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.tabla.setMinimumWidth(300)
        self.tabla.setMinimumHeight(420)
        self.b_map = {}
        for i, s in enumerate(PF.SALIDAS):
            self.tabla.setItem(i, 0, QTableWidgetItem(str(PF.DESCRIPCION_SALIDA[s])))
            b = QPushButton("—")
            b.setStyleSheet("padding: 2px 8px;")
            b.setToolTip(T("Clic y luego toca el botón en el teléfono", "Click, then press the button on the phone"))
            b.clicked.connect(lambda _=False, sal=s: self._escuchar(sal))
            q = QPushButton(T("Quitar", "Clear"))
            q.setStyleSheet("padding: 2px 6px;")
            q.clicked.connect(lambda _=False, sal=s: self._asignar(sal, None))
            self.tabla.setCellWidget(i, 1, b)
            self.tabla.setCellWidget(i, 2, q)
            self.b_map[s] = b
            self.tabla.setRowHeight(i, 38)
        b_def = QPushButton(T("Restablecer mapeo recomendado", "Reset to recommended mapping"))
        b_def.clicked.connect(self._mapeo_defecto)
        self.nota_map = etiqueta("", "sub")
        cl.addWidget(tarjeta(self.nota_map, self.tabla, fila(b_def), titulo=T("Mapeo de botones", "Button mapping")))

        # --- sticks: vista en vivo y reasignación de cada stick físico
        self.s_zm = self._slider(0, 50, "stick", "zona_muerta", 100)
        self.s_rango = self._slider(50, 100, "stick", "rango", 100)
        g = QGridLayout()
        g.addWidget(QLabel(T("Zona muerta", "Dead zone")), 0, 0)
        g.addLayout(self.s_zm[2], 0, 1)
        g.addWidget(QLabel(T("Rango (tope)", "Range (max)")), 1, 0)
        g.addLayout(self.s_rango[2], 1, 1)
        self.c_sticks = []
        self.col_stick = {}
        self.stick_ws = {}
        cols = QHBoxLayout()
        for cual, sec in (("izq", "stick"), ("der", "stick_der")):
            w = StickWidget()
            w.setFixedSize(150, 150)
            titulo_st = etiqueta("", "sub")
            checks = [self._check(T("Invertir horizontal", "Invert horizontal"), sec, "invertir_x"),
                      self._check(T("Invertir vertical", "Invert vertical"), sec, "invertir_y"),
                      self._check(T("Intercambiar ejes (X ↔ Y)", "Swap axes (X ↔ Y)"), sec, "intercambiar_ejes")]
            self.c_sticks += checks
            caja = QWidget()
            v = QVBoxLayout(caja)
            v.setContentsMargins(0, 0, 0, 0)
            v.addWidget(titulo_st)
            v.addWidget(w)
            for c in checks:
                v.addWidget(c)
            self.col_stick[cual] = (caja, titulo_st)
            self.stick_ws[cual] = w
            cols.addWidget(caja)
        cols.addStretch(1)
        self.stick_w = self.stick_ws["izq"]
        self.c_swap = self._check(T("Intercambiar stick izquierdo y derecho", "Swap left and right sticks"),
                                  None, "sticks_intercambiados")
        self.c_sticks.append(self.c_swap)
        cl.addWidget(tarjeta(cols, self.c_swap, g, etiqueta(T(
            "Si un stick va al revés o de lado, corrígelo aquí mientras lo mueves y miras el círculo (o repite "
            "Calibración → Stick). Muchos juegos aplican además su propia zona muerta.",
            "If a stick moves inverted or sideways, fix it here while you move it and watch the circle (or repeat "
            "Calibration → Stick). Many games also apply their own dead zone."), "sub"), titulo="Sticks"))

        # --- movimiento
        self.mov = MovimientoWidget()
        self.mov.setFixedSize(260, 190)
        self.ang = [0.0, 0.0, 0.0]
        self._prev = None
        self.s_sens = self._slider(20, 300, "gyro", "sensibilidad", 100)
        self.c_inv = [self._check(t, "gyro", "invertir", i) for i, t in
                      enumerate((T("Invertir arriba/abajo", "Invert up/down"),
                                 T("Invertir izquierda/derecha", "Invert left/right"),
                                 T("Invertir inclinación", "Invert tilt")))]
        self.c_gs = self._check(T("Giroscopio → stick derecho (juegos sin movimiento)",
                                  "Gyro → right stick (games without motion)"), "gyro_stick", "activo")
        self.s_gs_max = self._slider(40, 400, "gyro_stick", "max_dps", 1)
        self.s_gs_zm = self._slider(0, 30, "gyro_stick", "zona_muerta", 1)
        self.c_gsx = self._check("Invertir X", "gyro_stick", "invertir_x")
        self.c_gsy = self._check("Invertir Y", "gyro_stick", "invertir_y")
        g = QGridLayout()
        g.addWidget(QLabel(T("Sensibilidad", "Sensitivity")), 0, 0)
        g.addLayout(self.s_sens[2], 0, 1)
        for i, c in enumerate(self.c_inv):
            g.addWidget(c, 1 + i, 1)
        g.addWidget(self.c_gs, 4, 0, 1, 2)
        g.addWidget(QLabel(T("°/s al tope", "°/s at full tilt")), 5, 0)
        g.addLayout(self.s_gs_max[2], 5, 1)
        g.addWidget(QLabel(T("Zona muerta (°/s)", "Dead zone (°/s)")), 6, 0)
        g.addLayout(self.s_gs_zm[2], 6, 1)
        g.addLayout(fila(self.c_gsx, self.c_gsy), 7, 1)
        b_cero = QPushButton(T("Centrar dibujo", "Re-center drawing"))
        b_cero.clicked.connect(lambda: self.ang.__setitem__(slice(None), [0.0, 0.0, 0.0]))
        col = QVBoxLayout()
        col.addWidget(self.mov)
        col.addWidget(b_cero)
        h = QHBoxLayout()
        h.addLayout(col)
        h.addLayout(g, 1)
        cl.addWidget(tarjeta(h, etiqueta(T("Si en el juego el apuntado va al revés, invierte aquí el eje (o usa la "
                                           "opción de invertir del propio juego).",
                                           "If aiming is inverted in the game, invert the axis here (or use the "
                                           "game's own invert option)."), "sub"),
                             titulo=T("Movimiento (giroscopio)", "Motion (gyroscope)")))

        # --- salidas
        self.c_ds4 = self._check(T("DualShock 4 virtual con giroscopio (recomendado)",
                                   "Virtual DualShock 4 with gyro (recommended)"), "salidas", "ds4")
        self.c_xbox = self._check(T("Xbox 360 virtual (sin giroscopio)", "Virtual Xbox 360 (no gyro)"),
                                  "salidas", "xbox")
        self.c_dsu = self._check(T("Servidor DSU (Dolphin, Cemu…), puerto:", "DSU server (Dolphin, Cemu…), port:"),
                                 "salidas", "dsu")
        self.sp_dsu = QSpinBox()
        self.sp_dsu.setRange(1024, 65535)
        self.sp_dsu.valueChanged.connect(lambda val: self._poner("salidas", "dsu_puerto", int(val)))
        self.aviso_sal = etiqueta("", "aviso")
        cl.addWidget(tarjeta(self.c_ds4, self.c_xbox, fila(self.c_dsu, self.sp_dsu), self.aviso_sal,
                             titulo=T("Salidas", "Outputs")))
        b_g = QPushButton(T("Guardar perfil", "Save profile"))
        b_g.setObjectName("primario")
        b_g.clicked.connect(self.v.guardar_perfil)
        cl.addLayout(fila(None, b_g, estirar=False))
        self.al_cambiar_perfil()

    def _cambio_idioma(self, _i):
        cod = self.idioma.currentData()
        if cod == i18n.actual():
            return
        self.v.ajustes["idioma"] = cod
        PF.guardar_ajustes(self.v.ajustes)
        r = QMessageBox.question(self, "Idioma / Language",
                                 "El idioma cambia al reiniciar la app. ¿Reiniciar ahora?\n"
                                 "The language changes when the app restarts. Restart now?")
        if r == QMessageBox.Yes:
            self.v.reiniciar()

    # -- helpers de controles ligados al perfil
    def _slider(self, minimo, maximo, seccion, clave, factor):
        s = QSlider(Qt.Horizontal)
        s.setRange(minimo, maximo)
        lab = QLabel("")
        lab.setFixedWidth(52)

        def cambio(val):
            real = val / factor
            lab.setText(f"{val}%" if factor == 100 else f"{val}")
            self._poner(seccion, clave, real)
        s.valueChanged.connect(cambio)
        return s, lab, fila(s, lab, estirar=False), (seccion, clave, factor)

    def _check(self, texto, seccion, clave, indice=None):
        c = QCheckBox(texto)
        c.toggled.connect(lambda val: self._poner(seccion, clave, bool(val), indice))
        c._liga = (seccion, clave, indice)
        return c

    @staticmethod
    def _valor(p, seccion, clave):
        return p.get(clave) if seccion is None else p[seccion].get(clave)

    def _poner(self, seccion, clave, valor, indice=None):
        if getattr(self, "_cargando", False):
            return
        p = copy.deepcopy(self.v.perfil)
        if seccion == "stick" and clave in ("zona_muerta", "rango") and "stick_der" in p:
            p["stick_der"][clave] = valor       # la zona muerta y el rango valen para los dos sticks
        if seccion is None:                     # opción del perfil, no de una sección
            if p.get(clave) == valor:
                return
            p[clave] = valor
        elif indice is None:
            if p[seccion].get(clave) == valor:
                return
            p[seccion][clave] = valor
        else:
            if p[seccion][clave][indice] == valor:
                return
            p[seccion][clave][indice] = valor
        self.v.poner_perfil(p, sucio=True, avisar=False)
        self._avisos()

    def al_cambiar_perfil(self):
        self._cargando = True
        p = self.v.perfil
        for s, lab, _, (sec, clave, factor) in (self.s_zm, self.s_rango, self.s_sens, self.s_gs_max, self.s_gs_zm):
            val = int(round(p[sec][clave] * factor))
            s.setValue(val)
            lab.setText(f"{val}%" if factor == 100 else f"{val}")
        for c in [self.c_gs, self.c_gsx, self.c_gsy, self.c_ds4, self.c_xbox,
                  self.c_dsu] + self.c_inv + self.c_sticks:
            sec, clave, idx = c._liga
            c.setChecked(bool(self._valor(p, sec, clave) if idx is None else p[sec][clave][idx]))
        ctrl = CT.control(p.get("control"))
        dos = len(ctrl.sticks) > 1
        self.col_stick["izq"][0].setVisible(bool(ctrl.sticks))
        self.col_stick["der"][0].setVisible(dos)
        self.c_swap.setVisible(dos)
        self.col_stick["izq"][1].setText(T("Stick izquierdo del teléfono", "Phone's left stick") if dos
                                         else T("Stick del teléfono", "Phone stick"))
        self.col_stick["der"][1].setText(T("Stick derecho del teléfono", "Phone's right stick"))
        self.sp_dsu.setValue(int(p["salidas"].get("dsu_puerto", 26761)))
        self._cargando = False
        self._pintar_mapeo()
        self._avisos()
        self.mov.orientacion = p["orientacion"]
        cid = CT.control(p.get("control")).id
        self.nota_map.setText(
            T("Clic en un botón de la columna central y toca en el teléfono el botón que quieres usar. ",
              "Click a button in the middle column and press the button you want on the phone. ") +
            {"joycon-izq": T("SL y L llegan idénticos (la app no los distingue) y presionar el stick no manda nada.",
                             "SL and L arrive identical (the app does not tell them apart) and clicking the stick "
                             "sends nothing."),
             "wii-classic": T("Si un stick va al revés, corrígelo en la sección Sticks de abajo.",
                              "If a stick is inverted, fix it in the Sticks section below."),
             "wii-remote": T("El Wii Remote no tiene stick: la sección Stick no hace nada con este control.",
                             "The Wii Remote has no stick: the Stick section does nothing for this controller.")}[cid])

    def _avisos(self):
        s = self.v.perfil["salidas"]
        t = []
        if s.get("ds4") and s.get("xbox"):
            t.append(T("⚠ DS4 y Xbox activos a la vez: el juego va a ver DOS controles. Deja solo uno.",
                       "⚠ DS4 and Xbox both active: the game will see TWO controllers. Keep only one."))
        if s.get("xbox") and not self.v.perfil["gyro_stick"]["activo"]:
            t.append(T("El control Xbox no tiene giroscopio: activa «Giroscopio → stick derecho» si quieres apuntar "
                       "con movimiento.", "The Xbox controller has no gyro: enable «Gyro → right stick» if you want "
                       "motion aiming."))
        if not (s.get("ds4") or s.get("xbox") or s.get("dsu")):
            t.append(T("⚠ No hay ninguna salida activa: el juego no va a ver ningún control.",
                       "⚠ No output is active: the game will not see any controller."))
        self.aviso_sal.setText("\n".join(t))

    def _pintar_mapeo(self):
        m = self.v.perfil["mapeo"]
        for s, b in self.b_map.items():
            if self.escuchando == s:
                b.setText(T("Toca el botón en el teléfono…  (Esc cancela)", "Press the button on the phone…  (Esc cancels)"))
                b.setObjectName("escucha")
            else:
                f = m.get(s)
                b.setText(nombre_fuente(self.v.perfil, f) if f else T("— sin asignar —", "— unassigned —"))
                b.setObjectName("")
            b.style().unpolish(b)
            b.style().polish(b)

    def _escuchar(self, salida):
        self.escuchando = None if self.escuchando == salida else salida
        self.t_escucha = time.monotonic()
        self._soltado = False
        self._pintar_mapeo()

    def _asignar(self, salida, fuente):
        p = copy.deepcopy(self.v.perfil)
        if fuente is None:
            p["mapeo"].pop(salida, None)
        else:
            p["mapeo"][salida] = fuente
        self.escuchando = None
        self.v.poner_perfil(p, sucio=True, avisar=False)
        self._pintar_mapeo()

    def _mapeo_defecto(self):
        p = copy.deepcopy(self.v.perfil)
        p["mapeo"] = C.mapeo_recomendado(p)
        self.v.poner_perfil(p, sucio=True, avisar=False)
        self._pintar_mapeo()

    def keyPressEvent(self, ev):
        if ev.key() == Qt.Key_Escape and self.escuchando:
            self.escuchando = None
            self._pintar_mapeo()
        else:
            super().keyPressEvent(ev)

    def refrescar(self, f):
        crudo, log = f.crudo, f.logico
        if f.estado != CONECTADO or crudo is None:
            return
        if self.escuchando:
            pres = crudo.presionados()
            if not self._soltado:
                self._soltado = not pres
            elif pres:
                self._asignar(self.escuchando, pres[0])
            elif time.monotonic() - self.t_escucha > 12:
                self.escuchando = None
                self._pintar_mapeo()
        p = self.v.perfil
        # cada círculo muestra un stick FÍSICO del teléfono, con sus ajustes aplicados
        for cual, sec in (("izq", "stick"), ("der", "stick_der")):
            st = p[sec]
            w = self.stick_ws[cual]
            x, y = (crudo.lx, crudo.ly) if cual == "izq" else (crudo.rx, crudo.ry)
            w.x, w.y = stick_logico(x, y, st)
            w.crudo = stick_logico(x, y, dict(st, zona_muerta=0.0, rango=1.0))
            w.zona_muerta, w.rango = st["zona_muerta"], st["rango"]
            w.update()
        if self._prev is not None and crudo is not self._prev:
            dt = min(C.dt_entre(self._prev, crudo) or 0.0, 0.1)
            for i in range(3):
                if abs(log.gyro[i]) > 2.5 * max(1.0, self.v.perfil["gyro"]["ruido"]):
                    self.ang[i] += log.gyro[i] * dt
                else:
                    self.ang[i] *= 0.985
        self._prev = crudo
        self.mov.angulos = list(self.ang)
        self.mov.update()


# ====================================================================== Perfiles
class PaginaPerfiles(Pagina):
    def __init__(self, v):
        super().__init__(v, T("Perfiles", "Profiles"),
                         T("Un perfil guarda la calibración, el mapeo y los ajustes. Con un perfil guardado ya no "
                           "hace falta recalibrar.", "A profile stores calibration, mapping and settings. With a saved "
                           "profile you don't need to calibrate again."))
        self.lista = QListWidget()
        self.lista.itemDoubleClicked.connect(lambda _i: self._usar())
        self.info = etiqueta("", "sub")
        botones = QVBoxLayout()
        for texto, fn, primario in [
                (T("Usar este perfil", "Use this profile"), self._usar, True),
                (T("Guardar cambios", "Save changes"), self.v.guardar_perfil, False),
                (T("Guardar como…", "Save as…"), self._guardar_como, False),
                (T("Nuevo perfil", "New profile"), self._nuevo, False),
                (T("Renombrar…", "Rename…"), self._renombrar, False),
                (T("Duplicar…", "Duplicate…"), self._duplicar, False),
                (T("Usar al abrir la app", "Use on startup"), self._por_defecto, False),
                (T("Exportar .json…", "Export .json…"), self._exportar, False),
                (T("Importar .json…", "Import .json…"), self._importar, False),
                (T("Borrar", "Delete"), self._borrar, False)]:
            b = QPushButton(texto)
            if primario:
                b.setObjectName("primario")
            b.clicked.connect(fn)
            botones.addWidget(b)
        botones.addStretch(1)
        h = QHBoxLayout()
        h.addWidget(self.lista, 1)
        h.addLayout(botones)
        self.lay.addLayout(h, 1)
        self.lay.addWidget(self.info)
        self.recargar()

    def recargar(self):
        self.lista.clear()
        defecto = self.v.ajustes.get("perfil_por_defecto")
        for n in PF.listar():
            marca = (T("  ★ se usa al abrir", "  ★ used on startup") if n == defecto else "") + \
                    (T("  ● en uso", "  ● in use") if n == self.v.perfil["nombre"] else "")
            self.lista.addItem(n + marca)
            self.lista.item(self.lista.count() - 1).setData(Qt.UserRole, n)
        p = self.v.perfil
        sucio = T(" (con cambios sin guardar)", " (unsaved changes)") if self.v.sucio else ""
        orient = (T("de lado", "sideways") if p["orientacion"] == "lado" else T("física", "physical"))
        cal = T("calibrado", "calibrated") if p.get("calibrado") else T("SIN calibrar", "NOT calibrated")
        self.info.setText(
            T("En uso", "In use") + f": «{p['nombre']}»{sucio} · {CT.control(p.get('control')).nombre} · "
            + T("orientación", "orientation") + f" {orient} · {cal} · " + T("carpeta", "folder") +
            f": {os.path.join(PF.carpeta_datos(), 'perfiles')}")

    def al_mostrar(self):
        self.recargar()

    def al_cambiar_perfil(self):
        self.recargar()

    def _sel(self):
        it = self.lista.currentItem()
        if not it:
            QMessageBox.information(self, T("Perfiles", "Profiles"),
                                    T("Selecciona un perfil de la lista.", "Select a profile from the list."))
            return None
        return it.data(Qt.UserRole)

    def _pedir(self, titulo, inicial=""):
        nombre, ok = QInputDialog.getText(self, titulo, T("Nombre del perfil:", "Profile name:"), text=inicial)
        nombre = nombre.strip()
        if not ok or not nombre:
            return None
        if nombre in PF.listar() and nombre != inicial:
            if QMessageBox.question(self, titulo, T(f"Ya existe «{nombre}». ¿Reemplazarlo?",
                                                    f"«{nombre}» already exists. Replace it?")) != QMessageBox.Yes:
                return None
        return nombre

    def _usar(self):
        n = self._sel()
        if n:
            try:
                self.v.poner_perfil(PF.cargar(n), sucio=False)
            except (ValueError, OSError) as err:
                QMessageBox.warning(self, T("Perfiles", "Profiles"), T("No se pudo cargar: ", "Could not load: ") + str(err))

    def _guardar_como(self):
        n = self._pedir(T("Guardar como", "Save as"), self.v.perfil["nombre"])
        if n:
            p = copy.deepcopy(self.v.perfil)
            p["nombre"] = n
            self.v.poner_perfil(p, sucio=True, avisar=False)
            self.v.guardar_perfil()

    def _nuevo(self):
        n = self._pedir(T("Nuevo perfil", "New profile"), T("Perfil nuevo", "New profile"))
        if n:
            self.v.poner_perfil(PF.perfil_por_defecto(None, n, self.v.perfil.get("control", "joycon-izq")),
                                sucio=True)
            self.v.guardar_perfil()

    def _renombrar(self):
        n = self._sel()
        nuevo = n and self._pedir(T("Renombrar", "Rename"), n)
        if nuevo and nuevo != n:
            p = PF.renombrar(n, nuevo)
            if self.v.ajustes.get("perfil_por_defecto") == n:
                self.v.ajustes["perfil_por_defecto"] = nuevo
                PF.guardar_ajustes(self.v.ajustes)
            if self.v.perfil["nombre"] == n:
                self.v.poner_perfil(p, sucio=False)
            self.recargar()

    def _duplicar(self):
        n = self._sel()
        nuevo = n and self._pedir(T("Duplicar", "Duplicate"), n + T(" (copia)", " (copy)"))
        if nuevo:
            PF.duplicar(n, nuevo)
            self.recargar()

    def _por_defecto(self):
        n = self._sel()
        if n:
            self.v.ajustes["perfil_por_defecto"] = n
            PF.guardar_ajustes(self.v.ajustes)
            self.recargar()

    def _exportar(self):
        n = self._sel()
        if not n:
            return
        ruta, _ = QFileDialog.getSaveFileName(self, T("Exportar perfil", "Export profile"), n + ".json",
                                              T("Perfil (*.json)", "Profile (*.json)"))
        if ruta:
            PF.guardar(PF.cargar(n), ruta)

    def _importar(self):
        ruta, _ = QFileDialog.getOpenFileName(self, T("Importar perfil", "Import profile"), "",
                                              T("Perfil (*.json)", "Profile (*.json)"))
        if not ruta:
            return
        try:
            p = PF.cargar_archivo(ruta)
        except (ValueError, OSError) as err:
            QMessageBox.warning(self, T("Importar", "Import"),
                                T("Ese archivo no se pudo leer como perfil:\n", "That file could not be read as a "
                                  "profile:\n") + str(err))
            return
        base = p["nombre"]
        i = 2
        while p["nombre"] in PF.listar():
            p["nombre"] = f"{base} ({i})"
            i += 1
        PF.guardar(p)
        self.recargar()

    def _borrar(self):
        n = self._sel()
        if n and QMessageBox.question(self, T("Borrar", "Delete"),
                                      T(f"¿Borrar el perfil «{n}»? No se puede deshacer.",
                                        f"Delete profile «{n}»? This cannot be undone.")) == QMessageBox.Yes:
            PF.borrar(n)
            if self.v.ajustes.get("perfil_por_defecto") == n:
                self.v.ajustes["perfil_por_defecto"] = None
                PF.guardar_ajustes(self.v.ajustes)
            self.recargar()


# ========================================================================= Jugar
class PaginaJugar(Pagina):
    def __init__(self, v):
        super().__init__(v, T("Jugar", "Play"), T("Elige el perfil, activa el control y abre el juego.",
                                                  "Pick the profile, enable the controller and open the game."))
        self.combo = QComboBox()
        self.combo.setMinimumWidth(260)
        self.combo.activated.connect(self._elegir)
        self.boton = QPushButton(T("▶  Activar control", "▶  Enable controller"))
        self.boton.setObjectName("verde")
        self.boton.clicked.connect(self._alternar)
        self.b_bandeja = QPushButton(T("Minimizar a la bandeja", "Minimize to tray"))
        self.b_bandeja.clicked.connect(self.v.a_bandeja)
        self.lay.addWidget(tarjeta(fila(QLabel(T("Perfil", "Profile")), self.combo, None, self.b_bandeja, self.boton,
                                        estirar=False)))
        self.luz_con, self.t_con = Semaforo(), etiqueta("", None, False)
        self.luz_sal, self.t_sal = Semaforo(), etiqueta("", None, False)
        self.t_err = etiqueta("", "error")
        self.lay.addWidget(tarjeta(fila(self.luz_con, self.t_con), fila(self.luz_sal, self.t_sal), self.t_err,
                                   titulo=T("Estado", "Status")))
        self.dibujo = JoyConWidget()
        self.stick_w = StickWidget()
        self.stick_w.setFixedSize(150, 150)
        self.bot = etiqueta("—", "dato")
        self.gyro = etiqueta("", "dato")
        col = QVBoxLayout()
        col.addWidget(self.stick_w)
        col.addWidget(etiqueta(T("El juego recibe:", "The game receives:"), "sub"))
        col.addWidget(self.bot)
        col.addWidget(self.gyro)
        col.addStretch(1)
        h = QHBoxLayout()
        h.addWidget(self.dibujo, 2)
        h.addLayout(col, 1)
        self.lay.addWidget(tarjeta(h, titulo=T("En vivo", "Live")), 1)
        self.lay.addWidget(etiqueta(T(
            "Abre el juego DESPUÉS de activar el control: lo verá como un DualShock 4 con giroscopio. Si el juego "
            "tiene una opción de «control en segundo plano», actívala para no perder el control al cambiar de ventana.",
            "Open the game AFTER enabling the controller: it will see a DualShock 4 with gyro. If the game has a "
            "«background input» option, enable it so you keep control when switching windows."), "sub"))

    def al_mostrar(self):
        self._llenar()
        self.dibujo.poner_perfil(self.v.perfil)
        self._etiquetas()

    def al_cambiar_perfil(self):
        self._llenar()
        self.dibujo.poner_perfil(self.v.perfil)
        self._etiquetas()

    def _etiquetas(self):
        inv = {}
        corto = {"A": "✕ (B)", "B": "○ (A)", "X": "□ (Y)", "Y": "△ (X)", "L1": "L", "R1": "R", "L2": "ZL",
                 "R2": "ZR", "SELECT": "−", "START": "+", "HOME": "Home", "ARRIBA": "↑", "ABAJO": "↓",
                 "IZQ": "←", "DER": "→", "L3": "L3", "R3": "R3", "TOUCH": "Touch"}
        f2f = fuente_a_fisicos(self.v.perfil)
        for salida, fuente in self.v.perfil["mapeo"].items():
            for fis in f2f.get(fuente, []):
                if fis != "L":
                    inv.setdefault(fis, []).append(corto.get(salida, salida))
        cid = CT.control(self.v.perfil.get("control")).id
        if cid == "joycon-izq":
            mostrar = lambda k: k.startswith("F_") or k == "VERDE"  # noqa: E731
        else:
            mostrar = lambda k: k in ("C_A", "C_B", "C_X", "C_Y", "AL", "AR", "W_A", "W_B", "UNO", "DOS")  # noqa: E731
        self.dibujo.etiquetas = {k: " ".join(val) for k, val in inv.items() if mostrar(k)}

    def _llenar(self):
        self.combo.blockSignals(True)
        self.combo.clear()
        nombres = PF.listar()
        actual = self.v.perfil["nombre"]
        if actual not in nombres:
            nombres = [actual] + nombres
        self.combo.addItems(nombres)
        self.combo.setCurrentText(actual)
        self.combo.blockSignals(False)

    def _elegir(self, _i):
        n = self.combo.currentText()
        if n != self.v.perfil["nombre"] and n in PF.listar():
            self.v.poner_perfil(PF.cargar(n), sucio=False)

    def _alternar(self):
        m = self.v.motor
        if m.jugando:
            m.jugar(False)
            return
        if m.estado == DETENIDO:
            self.v.paginas["Conexión"].conectar()
        m.jugar(True)

    def refrescar(self, f):
        self.dibujo.fase = 0
        self.boton.setText(T("■  Desactivar control", "■  Disable controller") if f.jugando
                           else T("▶  Activar control", "▶  Enable controller"))
        self.boton.setObjectName("rojo" if f.jugando else "verde")
        self.boton.style().unpolish(self.boton)
        self.boton.style().polish(self.boton)
        ip = self.v.ajustes["ip"]
        textos = {DETENIDO: (T("Sin conectar con el dispositivo (se conecta sola al activar)",
                               "Not connected to the device (connects automatically when enabled)"), TENUE),
                  BUSCANDO: (T(f"Buscando el dispositivo en {ip}…", f"Looking for the device at {ip}…"), AMBAR),
                  CONECTADO: (T(f"Dispositivo conectado · {f.pps} paquetes/s · movimiento {f.mps} Hz",
                                f"Device connected · {f.pps} packets/s · motion {f.mps} Hz"), VERDE),
                  SIN_DATOS: (T("Sin datos del dispositivo: control en neutro, reconectando sola…",
                                "No data from the device: controller neutral, reconnecting…"), ROJO)}
        t, c = textos[f.estado]
        self.t_con.setText(t)
        self.luz_con.poner(c)
        if not f.jugando:
            self.t_sal.setText(T("Control desactivado: el juego no ve ningún control de esta app.",
                                 "Controller disabled: the game sees no controller from this app."))
            self.luz_sal.poner(TENUE)
        elif f.salidas:
            puerto = self.v.perfil["salidas"]["dsu_puerto"]
            extra = T(f" · {f.clientes_dsu} cliente(s) DSU en el puerto {puerto}",
                      f" · {f.clientes_dsu} DSU client(s) on port {puerto}") if "Servidor DSU" in f.salidas else ""
            nombres = [T(s, {"Servidor DSU": "DSU server"}.get(s, s)) for s in f.salidas]
            self.t_sal.setText(T("Activo: ", "Active: ") + " + ".join(nombres) + extra)
            self.luz_sal.poner(VERDE if f.estado == CONECTADO else AMBAR)
        else:
            self.t_sal.setText(T("Ninguna salida pudo activarse.", "No output could be enabled."))
            self.luz_sal.poner(ROJO)
        err = f.error_salida
        if err and ("ViGEm" in err or "virtual" in err):
            err += T("\n→ Ve a «Conexión» para instalar ViGEmBus (y reinicia Windows).",
                     "\n→ Go to «Connection» to install ViGEmBus (and restart Windows).")
        self.t_err.setText(err)
        if not self.v.perfil.get("calibrado") and f.jugando:
            self.t_err.setText((err + "\n" if err else "") +
                               T("Aviso: este perfil no está calibrado; el movimiento puede salir desviado o al revés.",
                                 "Warning: this profile is not calibrated; motion may be off or inverted."))
        crudo, log = f.crudo, f.logico
        if f.estado == CONECTADO and crudo is not None:
            pintar_vivo(self.dibujo, self.v.perfil, crudo, log)
            self.stick_w.x, self.stick_w.y = log.lx, log.ly
            self.stick_w.zona_muerta = self.v.perfil["stick"]["zona_muerta"]
            self.stick_w.rango = self.v.perfil["stick"]["rango"]
            self.bot.setText(" ".join(log.presionados()) or "—")
            self.gyro.setText(f"giro {log.gyro[0]:+5.0f} {log.gyro[1]:+5.0f} {log.gyro[2]:+5.0f} °/s")
        else:
            self.dibujo.presionados = set()
            self.dibujo.stick = self.dibujo.stick_der = (0, 0)
            self.stick_w.x = self.stick_w.y = 0
            self.bot.setText("—")
        self.dibujo.update()
        self.stick_w.update()


# ====================================================================== Ventana
class Ventana(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"DSU Pad {VERSION}")
        self.setWindowIcon(icono_app())
        self.resize(1080, 760)
        self.setMinimumSize(940, 640)
        self.ajustes = PF.cargar_ajustes()
        self.motor = Motor()
        self.vigem_ok = False
        self.sucio = False
        self.perfil = self._perfil_inicial()

        central = QWidget()
        central.setObjectName("central")
        self.setCentralWidget(central)
        h = QHBoxLayout(central)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)
        self.nav = QListWidget()
        self.nav.setObjectName("nav")
        self.nav.setFixedWidth(170)
        self.pila = QStackedWidget()
        h.addWidget(self.nav)
        h.addWidget(self.pila, 1)
        self.paginas = {}
        for nombre, clase in [("Conexión", PaginaConexion), ("Control", PaginaControl),
                              ("Calibración", PaginaCalibracion), ("Ajustes", PaginaAjustes),
                              ("Perfiles", PaginaPerfiles), ("Jugar", PaginaJugar)]:
            pag = clase(self)
            self.paginas[nombre] = pag
            self.pila.addWidget(pag)
            self.nav.addItem(T(nombre, PAGINAS_EN[nombre]))
        self.nav.currentRowChanged.connect(self._cambio_pagina)
        self.nav.setCurrentRow(0)

        self.bandeja = QSystemTrayIcon(icono_app(), self)
        menu = QMenu()
        a1 = QAction(T("Mostrar", "Show"), self)
        a1.triggered.connect(self.de_bandeja)
        a2 = QAction(T("Salir", "Quit"), self)
        a2.triggered.connect(self._salir)
        menu.addAction(a1)
        menu.addAction(a2)
        self._menu_bandeja = menu
        self.bandeja.setContextMenu(menu)
        self.bandeja.activated.connect(
            lambda r: self.de_bandeja() if r in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick) else None)
        self.bandeja.setToolTip("DSU Pad")

        self.reloj = QTimer(self)
        self.reloj.timeout.connect(self._tic)
        self.reloj.start(33)
        self._saliendo = False

        if self.ajustes.get("conectar_al_abrir") and self.ajustes.get("ip"):
            self.paginas["Conexión"].conectar()
            if self.perfil.get("calibrado"):
                self.motor.jugar(True)
                self.ir("Jugar")

    def _perfil_inicial(self):
        nombre = self.ajustes.get("perfil_por_defecto")
        nombres = PF.listar()
        for n in ([nombre] if nombre else []) + nombres:
            if n in nombres:
                try:
                    return PF.cargar(n)
                except (ValueError, OSError):
                    continue
        return PF.perfil_por_defecto("lado")

    def reiniciar(self):
        """Vuelve a abrir la app (para aplicar el idioma)."""
        import sys
        if getattr(sys, "frozen", False):
            prog, args = sys.executable, sys.argv[1:]
        else:
            prog, args = sys.executable, ["-m", "app.main"] + sys.argv[1:]
        raiz = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        QProcess.startDetached(prog, args, raiz)
        self._salir()

    # -- perfil
    def poner_perfil(self, perfil, sucio, avisar=True):
        self.perfil = perfil
        self.sucio = sucio
        self.motor.poner_perfil(perfil)
        if avisar:
            for p in self.paginas.values():
                p.al_cambiar_perfil()
        self._titulo()

    def guardar_perfil(self):
        try:
            PF.guardar(self.perfil)
        except OSError as err:
            QMessageBox.warning(self, T("Guardar", "Save"), T("No se pudo guardar el perfil: ",
                                                               "Could not save the profile: ") + str(err))
            return
        self.sucio = False
        if not self.ajustes.get("perfil_por_defecto") or self.ajustes["perfil_por_defecto"] not in PF.listar():
            self.ajustes["perfil_por_defecto"] = self.perfil["nombre"]
            PF.guardar_ajustes(self.ajustes)
        self.paginas["Perfiles"].recargar()
        self.paginas["Jugar"]._llenar()
        self._titulo()
        self.statusBar().showMessage(T(f"Perfil «{self.perfil['nombre']}» guardado",
                                       f"Profile «{self.perfil['nombre']}» saved"), 4000)

    def _titulo(self):
        self.setWindowTitle(f"DSU Pad {VERSION} — {self.perfil['nombre']}{' *' if self.sucio else ''}")

    # -- navegación
    def ir(self, nombre):
        self.nav.setCurrentRow(list(self.paginas).index(nombre))

    def _cambio_pagina(self, i):
        self.pila.setCurrentIndex(i)
        self.pila.currentWidget().al_mostrar()

    def _tic(self):
        f = self.motor.foto()
        self.pila.currentWidget().refrescar(f)
        cal = self.paginas["Calibración"]
        if cal.modo == "pasos" and self.pila.currentWidget() is not cal:
            cal.refrescar(f)       # el asistente sigue consumiendo datos aunque se cambie de página

    # -- bandeja y cierre
    def a_bandeja(self):
        if not QSystemTrayIcon.isSystemTrayAvailable():
            self.showMinimized()
            return
        self.bandeja.show()
        self.hide()
        self.bandeja.showMessage("DSU Pad", T("Sigo funcionando aquí. Doble clic para volver a abrir.",
                                                   "Still running here. Double-click to open again."),
                                 QSystemTrayIcon.Information, 3000)

    def de_bandeja(self):
        self.showNormal()
        self.activateWindow()
        self.bandeja.hide()

    def _salir(self):
        self._saliendo = True
        self.close()

    def closeEvent(self, ev):
        if self.sucio and self.isVisible():
            r = QMessageBox.question(self, T("Cambios sin guardar", "Unsaved changes"),
                                     T(f"El perfil «{self.perfil['nombre']}» tiene cambios sin guardar. ¿Guardarlos?",
                                       f"Profile «{self.perfil['nombre']}» has unsaved changes. Save them?"),
                                     QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel)
            if r == QMessageBox.Cancel:
                ev.ignore()
                return
            if r == QMessageBox.Yes:
                self.guardar_perfil()
        self.reloj.stop()
        self.motor.detener()
        self.bandeja.hide()
        ev.accept()
        QApplication.quit()
