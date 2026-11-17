"""Idioma de la interfaz / interface language.

English is the default; Spanish can be chosen in Settings (applies after restart).
Usage:  T("Conectar", "Connect")  ->  the text in the current language.
For module-level constants use L("…", "…"): it is translated when it is shown.
"""
IDIOMAS = {"en": "English", "es": "Español"}
_idioma = "en"


def poner(idioma):
    global _idioma
    _idioma = idioma if idioma in IDIOMAS else "en"


def actual():
    return _idioma


def T(es, en):
    return es if _idioma == "es" else en


class L:
    """Texto en dos idiomas que se traduce al usarse (str, f-string, +)."""
    __slots__ = ("es", "en")

    def __init__(self, es, en):
        self.es, self.en = es, en

    def __str__(self):
        return T(self.es, self.en)

    def __format__(self, spec):
        return format(str(self), spec)

    def __add__(self, otro):
        return str(self) + str(otro)

    def __radd__(self, otro):
        return str(otro) + str(self)

    def __len__(self):
        return len(str(self))

    def __eq__(self, otro):
        return str(self) == str(otro)

    def __hash__(self):
        return hash(self.es)

    def __repr__(self):
        return f"L({self.es!r}, {self.en!r})"
