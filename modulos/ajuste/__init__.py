"""Módulo "ajuste": todo el negocio de ajuste_comp_web, portado sobre el núcleo de appbase.

Fase 6 (Espectrómetro LMX06): el cuadro "Espectro" ya está completo -- listener de eventos de fondo (thread
de Python, no asyncio: spectro_client.py es código puro socket/threading), conexión/medir/alertas/teclado
remoto, métodos/perfiles. Junto con Carbomax (Modbus, fase 5) eso cierra los dos orígenes de composición
automática. Lo que queda: la vía de red/CGI de Carbomax (descarga de curvas completas para Análisis Térmico,
todavía no portado) sigue sin arrancar a propósito -- mismo criterio que la app vieja desde el 11/09/2026:
Modbus es la vía principal, la red queda disponible solo a demanda.

comun.js tiene que cargar SIEMPRE primero -- define el namespace global "Ajuste"
(apiFetch/waitForApproval/wsConnect) que el resto de los scripts del módulo usan. graph.js/panels.js van ANTES
de ajuste.js porque éste depende de createGraphView()/makeReorderable()."""
import asyncio
from pathlib import Path

from nucleo.modulo import Menu, Modulo

from . import esquema
from . import rutas
from .ws import hub

_bg_tasks = []


def _al_iniciar() -> None:
    """hub.bind_loop deja que los endpoints sincronos (los que FastAPI corre en threadpool) puedan empujar un
    mensaje WS por hub.broadcast_threadsafe() sin tener que ir a buscar el loop por su cuenta. Las tareas de
    fondo (Carbomax Modbus, auto-guardado de sesión) reemplazan a los threads/loops de Tkinter del original --
    arrancan una sola vez acá, dentro del lifespan async de crear_app() (el loop ya está corriendo en ese
    punto, así que asyncio.create_task() funciona aunque esta función en sí sea sincrónica).

    La vía de red/CGI de Carbomax automático (carbomax_auto.carbomax_auto_loop) NO se arranca a propósito --
    mismo criterio que la app vieja desde el 11/09/2026: Modbus es la vía principal, la red queda disponible
    solo a demanda (botón "Descargar" de Análisis Térmico, todavía no portado)."""
    hub.bind_loop(asyncio.get_running_loop())

    from . import carbomax_modbus_auto, session_auto_save, spectro_auto

    _bg_tasks.append(asyncio.create_task(carbomax_modbus_auto.carbomax_modbus_auto_loop()))
    _bg_tasks.append(asyncio.create_task(session_auto_save.session_auto_save_loop()))
    _bg_tasks.append(asyncio.create_task(spectro_auto.spectro_auto_loop()))


def _al_terminar() -> None:
    for task in _bg_tasks:
        task.cancel()
    _bg_tasks.clear()


MODULO = Modulo(
    nombre="ajuste",
    carpeta=Path(__file__).resolve().parent,
    esquema=esquema.ESQUEMA,
    columnas=esquema.COLUMNAS,
    migrar=esquema.migrar,
    router=rutas.router,
    scripts=["comun.js", "settings.js", "dashboard.js", "catalogo.js", "informes.js",
             "colada_search.js", "historicos.js", "termico.js", "graph.js", "panels.js", "ajuste.js",
             "calidad.js", "pie_horno.js", "modbus.js"],
    estilos=["comun.css", "dashboard.css", "catalogo.css", "informes.css", "historicos.css", "termico.css",
             "ajuste.css", "calidad.css", "modbus.css"],
    menu=[
        Menu("dashboard", "Dashboard", orden=5),
        Menu("catalogo", "Catálogo", orden=6),
        Menu("informes", "Informes", orden=7),
        Menu("historicos", "Históricos", orden=8),
        Menu("termico", "Análisis Térmico", orden=9),
        Menu("ajuste", "Ajuste", orden=10),
        Menu("calidad", "Calidad", orden=11),
        Menu("pie_horno", "Pie de Horno", orden=13),
        Menu("modbus", "Delta Modbus", orden=14),
    ],
    al_iniciar=_al_iniciar,
    al_terminar=_al_terminar,
)
