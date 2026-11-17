"""'Usuario robot': completa el asistente de calibración contra el simulador
leyendo solo lo que el asistente pide (igual que una persona leería la UI)."""
import time

from app.core.calibracion import Asistente
from app.core.protocolo import ClienteDSU

EJE = {"pitch": 0, "yaw": 1, "roll": 2}


def calibrar_con_robot(sim, perfil, limite=90.0, grados=50.0, al_avanzar=None, cliente=None):
    """Corre el asistente completo. Devuelve (asistente, perfil_calibrado)."""
    propio = cliente is None
    cliente = cliente or ClienteDSU("127.0.0.1", sim.puerto)
    asis = Asistente(perfil)
    fin = time.monotonic() + limite
    visto = None        # (id del paso, estado/fase) ya atendido
    try:
        while not asis.terminado and time.monotonic() < fin:
            e = cliente.recibir(0.3)
            if e is None:
                continue
            asis.alimentar(e)
            if asis.terminado:
                break
            p = asis.paso
            clave = (p.id, p.estado, p.info.get("fase"))
            if clave == visto:
                continue
            visto = clave
            if al_avanzar:
                al_avanzar(asis)
            if p.tipo == "boton":
                if p.estado == "esperando":
                    sim.soltar()
                    time.sleep(0.08)
                    sim.presionar(p.info["fisico"])
                else:
                    sim.soltar()
            elif p.tipo == "stick_centro":
                sim.stick(0, 0, p.info.get("cual", "izq"))
            elif p.tipo == "stick_dir":
                cual = p.info.get("cual", "izq")
                if p.estado == "esperando":
                    sim.stick(*((0, 1) if p.info["direccion"] == "arriba" else (1, 0)), cual)
                else:
                    sim.stick(0, 0, cual)
            elif p.tipo == "gesto":
                if p.info.get("fase") == "regresar":
                    sim.girar(EJE[p.info["eje"]], -grados, 0.7)
                else:
                    sim.girar(EJE[p.info["eje"]], grados, 0.7)
        sim.soltar()
        sim.stick(0, 0)
        sim.stick(0, 0, "der")
        if not asis.terminado:
            raise TimeoutError(f"el asistente se quedó en el paso {asis.paso.id} "
                               f"({asis.paso.estado}) aviso={asis.paso.aviso!r} error={asis.error!r}")
        return asis, asis.aplicar(perfil)
    finally:
        if propio:
            cliente.cerrar()
