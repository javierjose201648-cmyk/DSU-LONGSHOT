"""Lanzador para PyInstaller (importa el paquete `app` como paquete)."""
import sys

from app.main import main

if __name__ == "__main__":
    sys.exit(main())
