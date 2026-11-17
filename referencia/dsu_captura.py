#!/usr/bin/env python3
"""
dsu_captura.py — Graba exactamente lo que manda la app DSU Controller para
poder configurar bien el puente. No necesita instalar nada (solo Python 3.8+).

Uso:
    python dsu_captura.py --ip 192.168.1.50 --etiqueta joycon

Genera captura_<etiqueta>.json en la misma carpeta. Ese archivo es el que hay
que revisar. Puedes correrlo una vez por cada modo de la app (Joy-Con, Xbox...).
"""

import argparse
import json
import os
import platform
import socket
import struct
import sys
import time
import zlib

PUERTO_DEFAULT = 26760
CLIENT_ID = 0x4A534232
MSG_VERSION, MSG_INFO, MSG_DATOS = 0x100000, 0x100001, 0x100002

# Bytes del paquete de datos que pueden cambiar con la entrada del usuario
# (botones, sticks, analógicos, touch). Ver cemuhook-protocol.
ZONA_ENTRADA = range(36, 68)
NOMBRE_BYTE = {
    36: "botones1", 37: "botones2", 38: "home", 39: "touch_btn",
    40: "LX", 41: "LY", 42: "RX", 43: "RY",
    44: "an_izq", 45: "an_abajo", 46: "an_der", 47: "an_arriba",
    48: "an_Y", 49: "an_B", 50: "an_A", 51: "an_X",
    52: "an_R1", 53: "an_L1", 54: "an_R2", 55: "an_L2",
}
BITS = {
    36: ["SELECT", "L3", "R3", "START", "ARRIBA", "DER", "ABAJO", "IZQ"],   # bit0..bit7
    37: ["L2", "R2", "L1", "R1", "X", "A", "B", "Y"],
}

# Lo que se pide presionar, por perfil de la app.
# En "joycon-izq" las direcciones son como se ven con el teléfono VERTICAL
# (como en un screenshot), para que no dependan de cómo lo sostengas.
PERFILES = {
    "joycon-izq": {
        "botones": [
            "ZL (botón morado arriba a la izquierda)",
            "L (botón gris arriba a la derecha)",
            "Presionar el STICK (tócalo sin moverlo, o presiónalo)",
            "Flecha ARRIBA △",
            "Flecha ABAJO ▽",
            "Flecha IZQUIERDA ◁",
            "Flecha DERECHA ▷",
            "MENOS (la rayita | a la derecha)",
            "Ícono VERDE (entre la rayita y el +)",
            "MÁS (+)",
            "SL (botón morado de arriba, a la derecha)",
            "SR (botón morado de abajo, a la derecha)",
        ],
        "sticks": [
            "Stick hacia ARRIBA (hacia ZL/L, con el teléfono vertical)",
            "Stick a la DERECHA (hacia el −/+, con el teléfono vertical)",
        ],
        "nota": "Las direcciones se nombran con el teléfono vertical, como en el screenshot.",
    },
    "completo": {
        "botones": [
            "A", "B", "X", "Y", "L", "R", "ZL", "ZR", "MENOS (-)", "MÁS (+)",
            "Presionar stick izquierdo", "Presionar stick derecho",
            "Cruceta ARRIBA", "Cruceta ABAJO", "Cruceta IZQUIERDA", "Cruceta DERECHA",
            "HOME", "CAPTURA", "SL", "SR",
        ],
        "sticks": [
            "Stick IZQUIERDO hacia ARRIBA", "Stick IZQUIERDO a la DERECHA",
            "Stick DERECHO hacia ARRIBA", "Stick DERECHO a la DERECHA",
        ],
        "nota": "",
    },
}
PRUEBAS_GESTOS = [
    "APUNTA HACIA ARRIBA ~45° (la punta sube, como mirar al techo)",
    "APUNTA HACIA LA IZQUIERDA ~45° (gira sobre la mesa, sin inclinar)",
    "INCLINA HACIA LA IZQUIERDA ~45° (como volante: baja el lado izquierdo)",
    "SACUDE el control 2 veces (como un golpe de Joy-Con)",
]


def paquete(tipo, payload=b""):
    cuerpo = struct.pack("<I", tipo) + payload
    cab = struct.pack("<4sHHII", b"DSUC", 1001, len(cuerpo), 0, CLIENT_ID)
    crc = zlib.crc32(cab + cuerpo) & 0xFFFFFFFF
    return struct.pack("<4sHHII", b"DSUC", 1001, len(cuerpo), crc, CLIENT_ID) + cuerpo


def validar(datos):
    """Devuelve (tipo, datos_recortados, crc_ok) o None si no es DSU."""
    if len(datos) < 20 or datos[:4] != b"DSUS":
        return None
    _, _, largo, crc, _ = struct.unpack_from("<4sHHII", datos)
    datos = datos[:16 + largo]
    crc_ok = zlib.crc32(datos[:8] + b"\0\0\0\0" + datos[12:]) & 0xFFFFFFFF == crc
    return struct.unpack_from("<I", datos, 16)[0], datos, crc_ok


def decodificar(d):
    """Resumen legible de un paquete de datos (para el reporte)."""
    if len(d) < 100:
        return {"largo": len(d)}
    return {
        "slot": d[20], "estado_slot": d[21], "modelo": d[22], "conexion": d[23],
        "mac": d[24:30].hex(":"), "bateria": d[30], "conectado": d[31],
        "num": struct.unpack_from("<I", d, 32)[0],
        "ts_us": struct.unpack_from("<Q", d, 68)[0],
        "accel": [round(v, 4) for v in struct.unpack_from("<3f", d, 76)],
        "gyro": [round(v, 4) for v in struct.unpack_from("<3f", d, 88)],
    }


class Captura:
    def __init__(self, ip, puerto):
        self.destino = (ip, puerto)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("0.0.0.0", 0))
        self.sock.settimeout(0.05)
        self.ult = 0.0
        self.otros = {}        # tipo de mensaje -> primer paquete (hex)
        self.crc_malos = 0
        self.slot = None

    def _pedir(self, forzar=False):
        ahora = time.monotonic()
        if not forzar and ahora - self.ult < 1.0:
            return
        self.ult = ahora
        try:
            self.sock.sendto(paquete(MSG_VERSION), self.destino)
            self.sock.sendto(paquete(MSG_INFO, struct.pack("<i", 4) + bytes(range(4))), self.destino)
            self.sock.sendto(paquete(MSG_DATOS, struct.pack("<BB6s", 0, 0, b"\0" * 6)), self.destino)
        except OSError:
            pass

    def leer(self, segundos):
        """Lee paquetes de datos durante `segundos`. Devuelve lista de (t, bytes)."""
        fin = time.monotonic() + segundos
        salida = []
        while time.monotonic() < fin:
            self._pedir()
            try:
                datos, _ = self.sock.recvfrom(2048)
            except (socket.timeout, OSError):
                continue
            r = validar(datos)
            if r is None:
                continue
            tipo, d, crc_ok = r
            if not crc_ok:
                self.crc_malos += 1
            if tipo != MSG_DATOS:
                self.otros.setdefault(hex(tipo), d.hex())
                continue
            if len(d) < 100 or d[31] == 0:
                continue
            if self.slot is None:
                self.slot = d[20]
            if d[20] != self.slot:
                continue
            salida.append((time.monotonic(), d))
        return salida

    def pausa(self, texto):
        input(f"\n{texto}\n  [Enter cuando estés listo] ")
        self._pedir(forzar=True)
        self.leer(0.3)  # tirar lo acumulado


def diferencias(base, paquetes):
    """Qué bytes de entrada cambiaron respecto al reposo y hasta qué valor."""
    cambios = {}
    for _, d in paquetes:
        for i in ZONA_ENTRADA:
            if d[i] != base[i]:
                c = cambios.setdefault(i, {"reposo": base[i], "valores": set()})
                c["valores"].add(d[i])
    resultado = []
    for i, c in sorted(cambios.items()):
        item = {"byte": i, "campo": NOMBRE_BYTE.get(i, f"touch_{i}"),
                "reposo": c["reposo"], "valores": sorted(c["valores"])[:12]}
        if i in BITS:
            bits = set()
            for v in c["valores"]:
                for b in range(8):
                    if (v ^ c["reposo"]) & (1 << b):
                        bits.add(BITS[i][b])
            item["bits_estandar"] = sorted(bits)
        resultado.append(item)
    return resultado


def contar(texto, cap, segundos):
    for n in range(3, 0, -1):
        sys.stdout.write(f"\r  {texto} — empieza en {n} ")
        sys.stdout.flush()
        cap.leer(1)
    sys.stdout.write(f"\r  {texto} — ¡AHORA! ({segundos:.0f} s)        \n")
    sys.stdout.flush()
    return cap.leer(segundos)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ip", required=True)
    ap.add_argument("--puerto", type=int, default=PUERTO_DEFAULT)
    ap.add_argument("--perfil", choices=list(PERFILES), default="joycon-izq",
                    help="qué botones pedir (default: joycon-izq)")
    ap.add_argument("--etiqueta", default=None, help="nombre del archivo (default: el perfil)")
    args = ap.parse_args()
    perfil = PERFILES[args.perfil]
    args.etiqueta = args.etiqueta or args.perfil

    cap = Captura(args.ip, args.puerto)
    reporte = {"etiqueta": args.etiqueta, "perfil": args.perfil, "fecha": time.strftime("%Y-%m-%d %H:%M"),
               "sistema": f"{platform.system()} {platform.release()}", "python": platform.python_version()}

    print(f"CAPTURA DSU — modo '{args.etiqueta}'\nConectando a {args.ip}:{args.puerto} ...")
    p = cap.leer(10)
    if not p:
        print("✗ No llegaron datos en 10 s. Revisa IP, puerto, misma red Wi-Fi y firewall.")
        sys.exit(1)
    print(f"✓ Llegan datos (slot {cap.slot}).")
    reporte["como_lo_sostienes"] = input(
        "\n¿Cómo vas a sostener el teléfono en este modo? (ej. 'horizontal con las dos manos',\n"
        " 'un solo joycon de lado', 'vertical'): ").strip()

    # 1. Reposo
    cap.pausa("PASO 1: Sostén el teléfono como vas a jugar, sin tocar nada, quieto (5 s).")
    reposo = cap.leer(5)
    if len(reposo) < 10:
        print("✗ Muy pocos paquetes en reposo.")
        sys.exit(1)
    # Referencia de reposo: el valor más frecuente de cada byte (robusto si algo
    # se presionó un instante durante la medición)
    base = bytearray(reposo[-1][1])
    for i in ZONA_ENTRADA:
        valores = [d[i] for _, d in reposo]
        base[i] = max(set(valores), key=valores.count)
    base = bytes(base)
    dur = reposo[-1][0] - reposo[0][0]
    reporte["reposo"] = {
        "paquetes": len(reposo),
        "hz": round(len(reposo) / dur, 1) if dur else None,
        "primer_paquete_hex": reposo[0][1].hex(),
        "ultimo_paquete_hex": base.hex(),
        "decodificado": decodificar(base),
        "muestras_movimiento": [decodificar(d) for _, d in reposo[::max(1, len(reposo) // 40)]],
        "bytes_que_cambian_solos": diferencias(base, reposo),
    }
    print(f"  ✓ {len(reposo)} paquetes, ~{reporte['reposo']['hz']} por segundo")

    # 2. Botones
    print("\nPASO 2: BOTONES. Cuando diga ¡AHORA!, presiona y suelta ese botón 2 veces.\n"
          "Si la app no tiene ese botón, no toques nada.")
    if perfil["nota"]:
        print("  " + perfil["nota"])
    cap.pausa("Empezamos con los botones.")
    reporte["botones"] = {}
    for b in perfil["botones"]:
        paquetes = contar(f"Botón {b}", cap, 3)
        dif = diferencias(base, paquetes)
        reporte["botones"][b] = dif
        resumen = ", ".join(
            f"{x['campo']}" + (f"→{x['bits_estandar']}" if x.get("bits_estandar") else "")
            for x in dif) or "nada"
        print(f"    detectado: {resumen}")

    # 3. Sticks
    print("\nPASO 3: STICKS. Mantén el stick hasta el tope durante el tiempo indicado.")
    cap.pausa("Empezamos con los sticks.")
    reporte["sticks"] = {}
    for s in perfil["sticks"]:
        paquetes = contar(s, cap, 2.5)
        reporte["sticks"][s] = diferencias(base, paquetes)
        print(f"    detectado: {', '.join(x['campo'] for x in reporte['sticks'][s]) or 'nada'}")

    # 4. Movimiento
    print("\nPASO 4: MOVIMIENTO. Haz el gesto al ¡AHORA! y luego regresa a la posición normal.")
    reporte["gestos"] = {}
    for g in PRUEBAS_GESTOS:
        cap.pausa("Vuelve a la posición normal.")
        paquetes = contar(g, cap, 3)
        reporte["gestos"][g] = [decodificar(d) for _, d in paquetes]
        print(f"    {len(paquetes)} muestras")

    # 5. Juego libre (por si hay algo que no cubrimos)
    cap.pausa("PASO 5: Juega 10 s como lo harías normalmente: botones, sticks y movimiento.")
    libre = cap.leer(10)
    reporte["libre"] = {
        "bytes_que_cambiaron": diferencias(base, libre),
        "muestras": [decodificar(d) for _, d in libre[::max(1, len(libre) // 60)]],
    }

    reporte["otros_mensajes"] = cap.otros
    reporte["crc_invalidos"] = cap.crc_malos
    nombre = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          f"captura_{args.etiqueta}.json")
    with open(nombre, "w", encoding="utf-8") as f:
        json.dump(reporte, f, indent=1, ensure_ascii=False)
    print(f"\n✓ Listo. Archivo guardado: {nombre}\n  Pásame ese archivo.")


if __name__ == "__main__":
    main()
