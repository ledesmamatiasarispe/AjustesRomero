"""Ajuste de Composición sobre el núcleo de appbase: el núcleo + el módulo "ajuste" (todo el negocio de la app vieja
ajuste_comp_web, portado acá en fases -- ver modulos/ajuste/)."""
from pathlib import Path

import nucleo

from . import version as v

nucleo.configurar(app=v.APP, nombre=v.NOMBRE, prefijo=v.PREFIJO, puerto=v.PUERTO, version=v.VERSION, repo=v.REPO,
                  subtitulo=v.SUBTITULO, login=v.LOGIN, base=v.BASE, raiz=Path(__file__).resolve().parent.parent)

from modulos import ajuste  # noqa: E402  (después de configurar)
from nucleo.aplicacion import crear_app  # noqa: E402

MODULOS = [ajuste.MODULO]
app = crear_app(MODULOS)
