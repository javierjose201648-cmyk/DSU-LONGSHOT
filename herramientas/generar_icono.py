#!/usr/bin/env python3
"""Genera assets/icono.ico (el control morado de la app) para el .exe y los accesos directos.

    python herramientas/generar_icono.py
"""
import os
import struct
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QBuffer, QIODevice  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402

TAMANOS = (16, 24, 32, 48, 64, 128, 256)


def png(pm):
    buf = QBuffer()
    buf.open(QIODevice.WriteOnly)
    pm.save(buf, "PNG")
    return bytes(buf.data())


def main(destino=os.path.join(RAIZ, "assets", "icono.ico")):
    app = QGuiApplication.instance() or QGuiApplication([])  # noqa: F841
    from app.ui.ventana import pixmap_icono
    imagenes = [(t, png(pixmap_icono(t))) for t in TAMANOS]
    # Formato ICO con imágenes PNG dentro (Windows Vista en adelante)
    cab = struct.pack("<HHH", 0, 1, len(imagenes))
    offset = 6 + 16 * len(imagenes)
    entradas, datos = b"", b""
    for t, d in imagenes:
        lado = 0 if t >= 256 else t
        entradas += struct.pack("<BBBBHHII", lado, lado, 0, 0, 1, 32, len(d), offset + len(datos))
        datos += d
    os.makedirs(os.path.dirname(destino), exist_ok=True)
    with open(destino, "wb") as f:
        f.write(cab + entradas + datos)
    print("ok", destino)
    return destino


if __name__ == "__main__":
    main()
