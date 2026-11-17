#!/usr/bin/env python3
"""Compila la app con PyInstaller (carpeta onedir) y arma el .zip de la release.

    python build.py            -> dist/DSU-Pad/  y  dist/DSU-Pad-<versión>-windows.zip
"""
import os
import shutil
import subprocess
import sys
import zipfile

RAIZ = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, RAIZ)
from app.ui.ventana import VERSION  # noqa: E402

NOMBRE = "DSU-Pad"


def main():
    dist = os.path.join(RAIZ, "dist")
    if os.name == "nt":
        corriendo = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {NOMBRE}.exe", "/NH"],
                                   capture_output=True, text=True).stdout
        if f"{NOMBRE}.exe" in corriendo:
            sys.exit(f"{NOMBRE}.exe está abierto: ciérralo antes de compilar (si no, se borra a medias).")
    shutil.rmtree(os.path.join(dist, NOMBRE), ignore_errors=True)
    import vgamepad
    carpeta_vg = os.path.dirname(vgamepad.__file__)
    cmd = [
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir", "--windowed",
        "--name", NOMBRE,
        "--icon", os.path.join(RAIZ, "assets", "icono.ico"),   # ícono del .exe y de los accesos directos
        "--distpath", dist, "--workpath", os.path.join(RAIZ, "build", "pyinstaller"),
        "--specpath", os.path.join(RAIZ, "build"),
        # vgamepad carga ViGEmClient.dll desde su propia carpeta
        "--add-data", f"{os.path.join(carpeta_vg, 'win')}{os.pathsep}vgamepad/win",
        "--hidden-import", "app.tests.simulador",
        "--exclude-module", "pytest", "--exclude-module", "tkinter", "--exclude-module", "sdl2",
        "--exclude-module", "numpy",
        os.path.join(RAIZ, "lanzar.py"),
    ]
    print(" ".join(cmd))
    subprocess.check_call(cmd, cwd=RAIZ)
    destino = os.path.join(dist, NOMBRE)
    shutil.copy(os.path.join(RAIZ, "LEEME.txt"), os.path.join(destino, "README.txt"))
    # Los __pycache__ copiados con --add-data guardan rutas absolutas de la PC que compila
    for base, dirs, _ in os.walk(destino):
        for d in list(dirs):
            if d == "__pycache__":
                shutil.rmtree(os.path.join(base, d))
                dirs.remove(d)
    zip_ruta = os.path.join(dist, f"{NOMBRE}-{VERSION}-windows.zip")
    if os.path.exists(zip_ruta):
        os.remove(zip_ruta)
    with zipfile.ZipFile(zip_ruta, "w", zipfile.ZIP_DEFLATED) as z:
        for base, _, archivos in os.walk(destino):
            for a in archivos:
                ruta = os.path.join(base, a)
                z.write(ruta, os.path.relpath(ruta, dist))
    print(f"\nListo: {destino}\nZip:   {zip_ruta} ({os.path.getsize(zip_ruta) / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
