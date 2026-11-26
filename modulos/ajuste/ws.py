# ws.py
# Hub de WebSocket generico, por "canal" (un string libre, ej. "ajuste",
# "cucharas", "thermal"). Portado sin cambios de backend/ws.py de
# ajuste_comp_web -- el nucleo no da nada equivalente, asi que esta pieza
# queda tal cual, como codigo propio del modulo.
#
# Todo el estado compartido de la app (modelo de "una sola sesion de
# trabajo para todos los dispositivos conectados", confirmado con el
# usuario) vive del lado del servidor; este hub es solo el mecanismo de
# entrega, no el dueño del estado — cada router es responsable de llamar a
# hub.broadcast(canal, mensaje) despues de cualquier cambio.
import asyncio
import json
import logging
from typing import Any

from fastapi import WebSocket

log = logging.getLogger("ws")


class ConnectionManager:
    def __init__(self):
        self._channels: dict[str, set[WebSocket]] = {}
        self._lock = asyncio.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop):
        """Guarda una referencia al loop principal de FastAPI -- se llama
        una sola vez, al arrancar la app. Es lo que le permite a
        broadcast_threadsafe() funcionar sin que cada llamador sincrono
        tenga que ir a buscar el loop por su cuenta."""
        self._loop = loop

    async def connect(self, channel: str, websocket: WebSocket):
        await websocket.accept()
        async with self._lock:
            self._channels.setdefault(channel, set()).add(websocket)

    async def disconnect(self, channel: str, websocket: WebSocket):
        async with self._lock:
            conns = self._channels.get(channel)
            if conns is not None:
                conns.discard(websocket)
                if not conns:
                    self._channels.pop(channel, None)

    async def broadcast(self, channel: str, message: dict[str, Any]):
        """Manda `message` (se serializa a JSON una sola vez) a todos los
        clientes conectados al canal. Las conexiones que fallan al enviar
        (cliente ya se fue sin que el servidor se haya enterado todavia)
        se descartan en silencio — se van a limpiar solas en el proximo
        disconnect del loop de lectura de cada conexion."""
        async with self._lock:
            conns = list(self._channels.get(channel, ()))
        if not conns:
            return
        payload = json.dumps(message, ensure_ascii=False, default=str)
        dead = []
        for ws in conns:
            try:
                await ws.send_text(payload)
            except Exception:
                dead.append(ws)
        if dead:
            async with self._lock:
                live = self._channels.get(channel)
                if live is not None:
                    for ws in dead:
                        live.discard(ws)

    def broadcast_threadsafe(self, channel: str, message: dict[str, Any]):
        """Para llamar desde codigo sincrono que corre en un thread aparte
        del loop principal -- ej. un endpoint FastAPI declarado como "def"
        en vez de "async def" (FastAPI lo corre en un threadpool), o una
        integracion bloqueante como la automatizacion COM de Access.
        Requiere que bind_loop() ya se haya llamado al arrancar la app. El
        resto de la app (loop de Carbomax auto, etc.) deberia preferir una
        tarea asyncio en vez de un thread, y llamar a broadcast() directo."""
        if self._loop is None:
            log.warning("broadcast_threadsafe(%s) llamado antes de bind_loop() -- se ignora", channel)
            return
        asyncio.run_coroutine_threadsafe(self.broadcast(channel, message), self._loop)


hub = ConnectionManager()
