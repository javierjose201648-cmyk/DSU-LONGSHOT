"""Idioma: inglés por defecto, español elegible en Ajustes (se guarda en ajustes.json)."""
import os

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from app import i18n  # noqa: E402
from app.core import calibracion as C  # noqa: E402
from app.core import perfiles as PF  # noqa: E402


@pytest.fixture(scope="module")
def qt():
    return QApplication.instance() or QApplication([])


def test_ingles_por_defecto(tmp_path, monkeypatch):
    monkeypatch.setenv("DSU_PAD_DATOS", str(tmp_path))
    assert PF.cargar_ajustes()["idioma"] == "en"
    assert PF.cargar_ajustes()["ip"] == ""          # sin IP de nadie por defecto


def test_textos_en_ingles_y_espanol():
    i18n.poner("en")
    asis = C.Asistente(PF.perfil_por_defecto(control="wii-classic"))
    assert str(asis.paso.texto) == "Press the a button"
    assert str(PF.DESCRIPCION_SALIDA["IZQ"]) == "D-pad ←"
    i18n.poner("es")
    assert str(asis.paso.texto) == "Toca el botón a"
    assert str(PF.DESCRIPCION_SALIDA["IZQ"]) == "Cruceta ←"


def test_ventana_en_ingles_y_cambio_a_espanol(qt, tmp_path, monkeypatch):
    monkeypatch.setenv("DSU_PAD_DATOS", str(tmp_path))
    i18n.poner("en")
    from app.ui.ventana import Ventana
    v = Ventana()
    try:
        assert [v.nav.item(i).text() for i in range(v.nav.count())] == \
            ["Connection", "Controller", "Calibration", "Settings", "Profiles", "Play"]
        assert v.paginas["Conexión"].boton.text() == "Connect"
        aj = v.paginas["Ajustes"]
        monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.No)
        aj.idioma.setCurrentIndex(aj.idioma.findData("es"))
        aj._cambio_idioma(0)
        assert PF.cargar_ajustes()["idioma"] == "es"
    finally:
        v.sucio = False
        v.close()
