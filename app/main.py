"""Punto de entrada de la app de escritorio."""
import argparse
import os
import sys
import traceback


def _registrar_errores():
    """En el .exe no hay consola: los errores inesperados van a un archivo."""
    from app.core import perfiles as PF
    ruta = os.path.join(PF.carpeta_datos(), "errores.log")

    def gancho(tipo, valor, tb):
        try:
            with open(ruta, "a", encoding="utf-8") as f:
                f.write("".join(traceback.format_exception(tipo, valor, tb)) + "\n")
        except OSError:
            pass
        sys.__excepthook__(tipo, valor, tb)
    sys.excepthook = gancho


def main(argv=None):
    ap = argparse.ArgumentParser(description="DSU Longshot: use any DSU (cemuhook) device as a PC controller")
    ap.add_argument("--simulador", action="store_true",
                    help="start a simulated DSU device on this PC (to try the app without a phone)")
    ap.add_argument("--control", default="joycon-izq",
                    choices=["joycon-izq", "wii-classic", "wii-remote"],
                    help="with --simulador: which controller layout to simulate")
    ap.add_argument("--jugar", action="store_true",
                    help="on startup: connect to the last IP and enable the controller")
    args = ap.parse_args(argv)

    from PySide6.QtWidgets import QApplication

    from app.ui.tema import ESTILO
    from app.ui.ventana import Ventana, icono_app

    _registrar_errores()
    from app import i18n
    from app.core import perfiles as PF
    i18n.poner(PF.cargar_ajustes().get("idioma", "en"))
    qt = QApplication(sys.argv[:1])
    qt.setApplicationName("DSU Longshot")
    qt.setStyle("Fusion")
    qt.setStyleSheet(ESTILO)
    qt.setWindowIcon(icono_app())
    qt.setQuitOnLastWindowClosed(False)

    sim = None
    if args.simulador:
        from app.tests.simulador import SimuladorApp, _demo
        import threading
        try:
            sim = SimuladorApp(26760, "127.0.0.1", control=args.control).iniciar()
        except OSError:            # 26760 ocupado: cualquier puerto libre
            sim = SimuladorApp(0, "127.0.0.1", control=args.control).iniciar()
        threading.Thread(target=_demo, args=(sim,), daemon=True).start()

    v = Ventana()
    if sim:
        v.paginas["Conexión"].ip.setCurrentText("127.0.0.1")
        v.paginas["Conexión"].puerto.setValue(sim.puerto)
    if sim and v.motor.estado != "detenido":
        v.motor.detener()          # "conectar al abrir" apuntaba al dispositivo real
        v.paginas["Conexión"].conectar()
    if args.jugar:
        if v.motor.estado == "detenido":
            v.paginas["Conexión"].conectar()
        v.motor.jugar(True)
        v.ir("Jugar")
    v.show()
    codigo = qt.exec()
    if sim:
        sim.detener()
    return codigo


if __name__ == "__main__":
    sys.exit(main())
