"""Motor: hilo que lee del teléfono, transforma y alimenta las salidas.

La UI nunca toca sockets ni el control virtual: solo lee `motor.foto()` y
manda órdenes (conectar, cambiar perfil, activar salidas).
"""
import collections
import threading
import time

from . import salidas as S
from .protocolo import ClienteDSU
from .transformar import transformar

DETENIDO, BUSCANDO, CONECTADO, SIN_DATOS = "detenido", "buscando", "conectado", "sin_datos"
T_NEUTRO = 2.0      # s sin datos antes de poner el control en neutro


class Foto:
    """Copia del estado del motor para dibujar (se crea en el hilo de la UI)."""
    __slots__ = ("estado", "crudo", "logico", "pps", "mps", "slot", "bateria", "modelo",
                 "conexion", "paquetes_malos", "salidas", "error_salida", "clientes_dsu",
                 "error_red", "t_sin_datos", "jugando")


class Motor:
    def __init__(self):
        self.estado = DETENIDO
        self._hilo = None
        self._activo = False
        self._candado = threading.Lock()
        self._perfil = None
        self._destino = None
        self._quiere_jugar = False
        self._reconfigurar = False
        self._salidas = []
        self._servidor = None
        self.error_salida = ""
        self._crudo = None
        self._logico = None
        self._llegadas = collections.deque(maxlen=400)       # t de cada paquete
        self._movimientos = collections.deque(maxlen=400)    # t de cada muestra nueva
        self._ts_prev = None
        self._oyentes = []            # funciones(Estado) llamadas en el hilo del motor
        self._cliente = None
        self._t_ultimo = 0.0

    # ------------------------------------------------------------ órdenes
    def conectar(self, ip, puerto, perfil):
        self.detener()
        self._destino = (ip, int(puerto))
        self._perfil = perfil
        self._activo = True
        self.estado = BUSCANDO
        self._crudo = self._logico = None
        self._llegadas.clear()
        self._movimientos.clear()
        self._hilo = threading.Thread(target=self._correr, name="motor-dsu", daemon=True)
        self._hilo.start()

    def detener(self):
        self._activo = False
        if self._hilo and self._hilo.is_alive():
            self._hilo.join(timeout=3)
        self._hilo = None
        self.estado = DETENIDO

    def poner_perfil(self, perfil):
        """Cambia el perfil en caliente (asignación atómica)."""
        viejo = self._perfil
        self._perfil = perfil
        if viejo is None or viejo.get("salidas") != perfil.get("salidas") \
                or viejo.get("gyro_stick") != perfil.get("gyro_stick") \
                or viejo.get("orientacion") != perfil.get("orientacion"):
            self._reconfigurar = True

    def jugar(self, activo):
        """Activa o desactiva las salidas (control virtual / servidor DSU)."""
        self._quiere_jugar = bool(activo)
        self._reconfigurar = True

    @property
    def jugando(self):
        return self._quiere_jugar

    def escuchar(self, funcion):
        self._oyentes.append(funcion)

    def dejar_de_escuchar(self, funcion):
        if funcion in self._oyentes:
            self._oyentes.remove(funcion)

    # ------------------------------------------------------------- lectura
    def foto(self):
        f = Foto()
        ahora = time.monotonic()
        f.estado = self.estado
        f.crudo, f.logico = self._crudo, self._logico
        f.pps = sum(1 for t in list(self._llegadas) if ahora - t <= 1.0)
        f.mps = sum(1 for t in list(self._movimientos) if ahora - t <= 1.0)
        c = self._crudo
        f.slot = c.slot if c else None
        f.bateria = c.bateria if c else None
        f.modelo = c.modelo if c else None
        f.conexion = c.conexion if c else None
        cli = self._cliente
        f.paquetes_malos = cli.paquetes_malos if cli else 0
        f.error_red = cli.error_red if cli else None
        f.salidas = [s.nombre for s in self._salidas]
        f.error_salida = self.error_salida
        f.clientes_dsu = len(self._servidor.clientes()) if self._servidor else 0
        f.t_sin_datos = (ahora - self._t_ultimo) if self._t_ultimo else None
        f.jugando = self._quiere_jugar
        return f

    # --------------------------------------------------------------- hilo
    def _cerrar_salidas(self):
        for s in self._salidas:
            try:
                s.cerrar()
            except Exception:
                pass
        self._salidas = []
        self._servidor = None

    def _configurar_salidas(self):
        self._reconfigurar = False
        self._cerrar_salidas()
        self.error_salida = ""
        if not self._quiere_jugar or self._perfil is None:
            return
        cfg = self._perfil["salidas"]
        gs = self._perfil["gyro_stick"] if self._perfil["gyro_stick"].get("activo") else None
        errores = []
        if cfg.get("ds4"):
            try:
                self._salidas.append(S.SalidaDS4(gyro_stick_cfg=gs))
            except Exception as err:
                errores.append(str(err))
        if cfg.get("xbox"):
            try:
                self._salidas.append(S.SalidaXbox(gyro_stick_cfg=gs))
            except Exception as err:
                errores.append(str(err))
        if cfg.get("dsu"):
            try:
                self._servidor = S.ServidorDSU(cfg.get("dsu_puerto", 26761),
                                               crudo=self._perfil["orientacion"] == "fisica")
                self._salidas.append(self._servidor)
            except Exception as err:
                errores.append(str(err))
        self.error_salida = " | ".join(errores)

    def _correr(self):
        ip, puerto = self._destino
        cliente = self._cliente = ClienteDSU(ip, puerto, self._perfil.get("slot"))
        en_neutro = True
        try:
            while self._activo:
                if self._reconfigurar:
                    self._configurar_salidas()
                    en_neutro = True
                e = cliente.recibir(0.25)
                ahora = time.monotonic()
                if e is None:
                    if self.estado == CONECTADO and ahora - self._t_ultimo > 0.6:
                        self.estado = SIN_DATOS
                    if not en_neutro and ahora - self._t_ultimo > T_NEUTRO:
                        en_neutro = True          # que no se queden botones pegados
                        for s in self._salidas:
                            try:
                                s.neutral()
                            except Exception:
                                pass
                    continue
                self._t_ultimo = ahora
                self.estado = CONECTADO
                self._llegadas.append(ahora)
                if e.ts_us != self._ts_prev:
                    self._movimientos.append(ahora)
                    self._ts_prev = e.ts_us
                perfil = self._perfil
                try:
                    log = transformar(e, perfil)
                except Exception:
                    continue                      # perfil a medio editar; siguiente paquete
                self._crudo, self._logico = e, log
                for s in self._salidas:
                    try:
                        s.actualizar(log)
                        en_neutro = False
                    except Exception as err:
                        self.error_salida = f"{s.nombre}: {err}"
                for f in list(self._oyentes):
                    try:
                        f(e)
                    except Exception:
                        pass
        finally:
            self._cerrar_salidas()
            cliente.cerrar()
            self._cliente = None
