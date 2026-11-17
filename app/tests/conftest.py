"""Las pruebas existentes revisan los textos en español; test_i18n prueba el inglés."""
import pytest

from app import i18n


@pytest.fixture(autouse=True)
def _idioma_es():
    i18n.poner("es")
    yield
    i18n.poner("es")
