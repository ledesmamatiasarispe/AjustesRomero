"""Identidad de esta app -- ver app/version.py de appbase (app de ejemplo) para qué significa cada campo.

Migración de ajuste_comp_web sobre el núcleo de appbase (2026-11-24). REPO se deja vacío a propósito: esta app sigue
corriendo como servidor LAN siempre encendido (uvicorn directo), no como .exe instalado/autoactualizable -- no
adoptamos herramientas/compilar.py ni nucleo/actualizador.py por ahora."""
VERSION = "0.2.0"
APP = "AjusteComp"
NOMBRE = "Ajuste de Composición"
SUBTITULO = "Cálculo de composición y seguimiento de coladas"
PREFIJO = "ACOMP"              # variables de entorno: ACOMP_DB, ACOMP_PUERTO, ACOMP_REPO, ACOMP_NAVEGADOR
PUERTO = 50506                  # mismo puerto que ajuste_comp_web, para no romper accesos ya guardados en planta
REPO = ""
LOGIN = "Usuario"
BASE = "ajuste_comp"            # nombre del .db (sin extensión) -- mismo nombre que usaba la app vieja
