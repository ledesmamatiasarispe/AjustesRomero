# session_auto_save.py -- puerto sin cambios de comportamiento de backend/core/session_auto_save.py de
# ajuste_comp_web. Corta y guarda sola una sesión de Ajuste que se dejó abierta más de la cuenta
# (settings.auto_save_hours, configurable desde Opciones). Tarea propia de asyncio -- separada de Carbomax
# automático a propósito, son dos features sin relación entre sí.
import asyncio
from datetime import datetime

from . import datos

_TICK_SECONDS = 60.0


async def _tick_once():
    from .rutas.ajuste import _do_save_session
    from .ws import hub

    settings = datos.load_settings()
    limit_hours = float(settings.get("auto_save_hours", 3.0) or 3.0)
    if limit_hours <= 0:
        limit_hours = 3.0

    st = datos.load_ajuste_session()
    if not st.get("ajustes_log") or not st.get("session_started_at"):
        return
    try:
        started = datetime.strptime(str(st["session_started_at"]), "%Y-%m-%d %H:%M:%S")
    except Exception:
        return
    if (datetime.now() - started).total_seconds() < limit_hours * 3600.0:
        return

    await _do_save_session(st, auto=True)
    await hub.broadcast("ajuste", {"type": "status_message", "message": f"Sesión guardada automáticamente por superar {limit_hours:g} horas."})


async def session_auto_save_loop():
    while True:
        try:
            await _tick_once()
        except Exception as ex:
            print(f"[session_auto_save] tick error: {ex}", flush=True)
        await asyncio.sleep(_TICK_SECONDS)
