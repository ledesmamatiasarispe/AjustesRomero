# rutas/camara.py -- puerto de backend/routers/camara.py de ajuste_comp_web. Cámara de calidad (kiosko de
# microscopio) -- PÁGINA STANDALONE (frontend/camara.html, servida en la ruta pública /camara.html, no es una
# vista del shell del núcleo) con su propio router, MJPEG/polling de frame, captura, análisis OpenCV (ver
# ..quality_analyzer) y "guardar en informe de Calidad".
#
# CAMBIO DELIBERADO vs. la app vieja: el original (quality_api.py) no tenía NINGÚN Depends(devices.*) -- a
# propósito, documentado en su propio comentario como "cualquiera en la red local que entre puede ver y
# analizar", y ya señalado como una exposición real conocida (escritura sin auth, servidor bindeado a
# 0.0.0.0). Esta migración le dio auth por dispositivo consistente a cada router -- acá también: lecturas
# (calibraciones/stream/frame/report-targets) exigen require_approved_device, escrituras reales
# (capture/analyze/save-to-report) exigen require_editor_device. La PC del microscopio necesita aprobarse una
# vez, como cualquier otra pantalla de esta app -- antes no necesitaba ninguna aprobación.
import threading
import time
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Body, Depends, HTTPException
from fastapi.responses import FileResponse, Response, StreamingResponse

from .. import dispositivos as devices
from .. import quality_analyzer as qa

router = APIRouter(tags=["camara"])
api_router = APIRouter(prefix="/api/camara", tags=["camara"])

_FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

MJPEG_BOUNDARY = "mjpegframe"
STREAM_FPS = 15
# El visor nunca muestra el stream a mas de ~1200px de ancho (ver #viewBox
# en camara.css) -- mandar cada frame del stream en vivo a la resolucion
# completa de captura (hasta 4K) es encode + transferencia desperdiciados.
# El frame full-res sigue disponible sin recortar via get_bgr() (usado por
# /capture y /analyze), que si necesita toda la resolucion para medir bien
# nodulos/laminillas.
PREVIEW_MAX_WIDTH = 1280
# cap.read() de UN solo frame en una resolucion "funciona" aunque la camara
# solo pueda sostenerla a 2-3fps (comun en camaras USB de microscopio que
# anuncian 4K por interpolacion de software pero solo entregan esa
# resolucion muy lento) -- eso es lo que se termina viendo como stream
# "lento y lagueado", no una falla de red. Antes de aceptar una resolucion
# candidata (ver _loop) se mide el ritmo real leyendo unos frames mas.
MIN_SUSTAINED_FPS = 8


# ---------- Página standalone ----------

@router.get("/camara.html", include_in_schema=False)
def pagina_camara():
    """Página pública (sin auth -- servir el HTML no es sensible, igual que cualquier otra página estática)
    en la ruta raíz /camara.html, para que siga siendo la URL que se abre en la pestaña nueva del microscopio.
    Las llamadas que esta página hace después SÍ llevan auth (ver el resto de este router)."""
    return FileResponse(_FRONTEND_DIR / "camara.html", media_type="text/html")


# ---------- Camera streamer (idéntico al original, ver quality_api.py) ----------

class _CameraStreamer:
    def __init__(self):
        self._frame = None
        self._frame_bgr = None
        self._lock = threading.Lock()
        self._clients = 0
        self._running = False
        self._thread = None
        self._cap = None
        self._error = None

    def acquire(self):
        self._clients += 1
        if not self._running:
            self._start()

    def release_client(self):
        self._clients = max(0, self._clients - 1)
        if self._clients == 0:
            self._stop()

    def _start(self):
        if self._running:
            return
        self._error = None
        self._running = True
        self._thread = threading.Thread(target=self._loop, name="quality-cam", daemon=True)
        self._thread.start()

    def _stop(self):
        self._running = False
        if self._cap is not None:
            try:
                self._cap.release()
            except Exception:
                pass
            self._cap = None
        with self._lock:
            self._frame = None
            self._frame_bgr = None

    def _loop(self):
        try:
            import cv2
        except ImportError:
            self._error = "OpenCV no instalado"
            self._running = False
            return

        cap = None
        for idx in range(3):
            for backend in (cv2.CAP_DSHOW, cv2.CAP_MSMF, 0):
                try:
                    c = cv2.VideoCapture(idx, backend) if backend else cv2.VideoCapture(idx)
                    if c.isOpened():
                        ret, _ = c.read()
                        if ret:
                            cap = c
                            break
                    c.release()
                except Exception:
                    pass
            if cap is not None:
                break

        if cap is None:
            self._error = "No se pudo abrir la cámara"
            self._running = False
            return

        for res in ((3840, 2160), (1920, 1080), (1280, 720)):
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, res[0])
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, res[1])
            ret, test = cap.read()
            if not ret or test is None:
                continue
            t0 = time.monotonic()
            n_ok = sum(1 for _ in range(6) if cap.read()[0])
            fps = n_ok / (time.monotonic() - t0 or 1e-6)
            if fps >= MIN_SUSTAINED_FPS:
                break
            # No sostiene el minimo -- se prueba la resolucion siguiente
            # (mas baja); si esta es la ultima de la lista, se sigue
            # usando igual (mismo criterio "mejor esfuerzo" que antes).
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

        self._cap = cap
        interval = 1.0 / STREAM_FPS
        while self._running:
            t0 = time.monotonic()
            ret, frame = cap.read()
            if ret and frame is not None:
                preview = frame
                h, w = frame.shape[:2]
                if w > PREVIEW_MAX_WIDTH:
                    scale = PREVIEW_MAX_WIDTH / w
                    preview = cv2.resize(frame, (PREVIEW_MAX_WIDTH, round(h * scale)), interpolation=cv2.INTER_AREA)
                ok, buf = cv2.imencode(".jpg", preview, [cv2.IMWRITE_JPEG_QUALITY, 75])
                if ok:
                    with self._lock:
                        self._frame = bytes(buf)
                        self._frame_bgr = frame  # full-res, sin recortar: lo usan /capture y /analyze
            elapsed = time.monotonic() - t0
            rest = interval - elapsed
            if rest > 0:
                time.sleep(rest)

        try:
            cap.release()
        except Exception:
            pass
        self._cap = None

    def get_jpeg(self):
        with self._lock:
            return self._frame

    def get_bgr(self):
        with self._lock:
            return self._frame_bgr.copy() if self._frame_bgr is not None else None

    @property
    def error(self):
        return self._error


_streamer = _CameraStreamer()

# Frame congelado por POST /capture
_captured_frame_bgr = None
_captured_lock = threading.Lock()


def _store_captured(frame_bgr):
    global _captured_frame_bgr
    with _captured_lock:
        _captured_frame_bgr = frame_bgr.copy() if frame_bgr is not None else None


def _get_captured():
    with _captured_lock:
        return _captured_frame_bgr.copy() if _captured_frame_bgr is not None else None


def _error_jpeg(message: str) -> bytes:
    import cv2
    import numpy as np
    img = np.zeros((360, 640, 3), dtype=np.uint8)
    lines = [message[i:i + 50] for i in range(0, len(message), 50)]
    y = 160
    for line in lines:
        cv2.putText(img, line, (20, y), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 80, 200), 2)
        y += 36
    _, buf = cv2.imencode(".jpg", img)
    return bytes(buf)


# ---------- endpoints ----------

@api_router.get("/calibraciones")
def get_calibraciones(_: dict = Depends(devices.require_approved_device)):
    cals = qa.load_calibrations()
    effective_id = next((c["id"] for c in cals if c.get("is_default")), None)
    if not effective_id and cals:
        effective_id = cals[0]["id"]
    return {"calibraciones": cals, "effective_id": effective_id}


@api_router.get("/mjpeg")
def mjpeg_stream(_: dict = Depends(devices.require_approved_device)):
    def generate():
        _streamer.acquire()
        try:
            interval = 1.0 / STREAM_FPS
            while True:
                t0 = time.monotonic()
                frame = _streamer.get_jpeg()
                if frame is None:
                    frame = _error_jpeg(_streamer.error) if _streamer.error else None
                    if frame is None:
                        time.sleep(0.1)
                        continue
                header = (
                    f"--{MJPEG_BOUNDARY}\r\n"
                    f"Content-Type: image/jpeg\r\n"
                    f"Content-Length: {len(frame)}\r\n\r\n"
                ).encode()
                yield header + frame + b"\r\n"
                elapsed = time.monotonic() - t0
                rest = interval - elapsed
                if rest > 0:
                    time.sleep(rest)
        except GeneratorExit:
            pass
        finally:
            _streamer.release_client()

    return StreamingResponse(
        generate(),
        media_type=f"multipart/x-mixed-replace; boundary={MJPEG_BOUNDARY}",
        headers={"Cache-Control": "no-store"},
    )


@api_router.post("/stream/start")
def stream_start(_: dict = Depends(devices.require_approved_device)):
    """El frontend llama esto una vez al empezar a hacer polling de /frame
    (reemplaza al <img src="/mjpeg"> persistente, que mantenia la camara
    abierta mientras el <img> siguiera conectado). Sin esto, GET /frame
    nunca dispara _streamer.acquire() y la camara jamas arranca."""
    _streamer.acquire()
    return {"ok": True}


@api_router.post("/stream/stop")
def stream_stop(_: dict = Depends(devices.require_approved_device)):
    """Contraparte de /stream/start -- se llama al pausar (capturar) o al
    cerrar la pagina, para liberar la camara fisica si nadie mas la esta
    usando."""
    _streamer.release_client()
    return {"ok": True}


@api_router.get("/frame")
def get_frame(_: dict = Depends(devices.require_approved_device)):
    """Un frame a la vez, pedido por polling desde el frontend -- reemplaza al <img src="/mjpeg"> persistente
    como mecanismo PRINCIPAL de video en vivo. Requiere que el cliente ya haya llamado a POST /stream/start."""
    frame = _streamer.get_jpeg()
    if frame is None:
        if _streamer.error:
            frame = _error_jpeg(_streamer.error)
        else:
            raise HTTPException(status_code=503, detail={"error": "sin_senial"})
    return Response(content=frame, media_type="image/jpeg", headers={"Cache-Control": "no-store, no-cache"})


@api_router.post("/capture")
def capture(_: dict = Depends(devices.require_editor_device)):
    frame_bgr = _streamer.get_bgr()
    if frame_bgr is None:
        raise HTTPException(status_code=503, detail={"error": "no_frame"})
    _store_captured(frame_bgr)
    import cv2
    ok, buf = cv2.imencode(".jpg", frame_bgr, [cv2.IMWRITE_JPEG_QUALITY, 95])
    if not ok:
        raise HTTPException(status_code=500, detail={"error": "encode_failed"})
    return Response(content=bytes(buf), media_type="image/jpeg")


@api_router.get("/captured")
def get_captured(_: dict = Depends(devices.require_approved_device)):
    frame_bgr = _get_captured()
    if frame_bgr is None:
        raise HTTPException(status_code=404, detail={"error": "sin_captura"})
    import cv2
    ok, buf = cv2.imencode(".jpg", frame_bgr, [cv2.IMWRITE_JPEG_QUALITY, 95])
    if not ok:
        raise HTTPException(status_code=500, detail={"error": "encode_failed"})
    return Response(content=bytes(buf), media_type="image/jpeg")


@api_router.post("/analyze")
def analyze(payload: dict = Body(...), _: dict = Depends(devices.require_editor_device)):
    import base64
    frame_bgr = _get_captured()
    if frame_bgr is None:
        raise HTTPException(status_code=409, detail={"error": "no_captured_frame"})

    mode = str(payload.get("mode", "nodular"))
    threshold = int(payload.get("threshold", 0) or 0)
    min_area = payload.get("min_area")
    min_area = int(min_area) if min_area is not None else None
    use_open = bool(payload.get("use_open", True))
    cal_id = payload.get("cal_id") or None

    px_per_mm = qa.get_px_per_mm(cal_id)

    import cv2

    def _to_b64(img):
        ok2, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 90])
        return base64.b64encode(bytes(buf)).decode() if ok2 else ""

    try:
        if mode == "laminar":
            stats = qa.count_laminar(frame_bgr, px_per_mm=px_per_mm, threshold=threshold, min_area=min_area, use_open=use_open)
            flakes = stats.pop("flakes", []) if stats else []
            overlay_bgr = qa.draw_laminar_overlay(frame_bgr, flakes)
        else:
            contours_data = qa.get_nodule_contours(frame_bgr, threshold=threshold, min_area=min_area, use_open=use_open)
            stats = qa.count_nodules(frame_bgr, px_per_mm=px_per_mm, threshold=threshold, min_area=min_area, use_open=use_open)
            overlay_bgr = qa.draw_nodule_overlay(frame_bgr, contours_data)

        binary_bgr = qa.get_binary_image(frame_bgr, threshold=threshold, use_open=use_open)
        return {
            "stats": stats,
            "overlay_jpeg": _to_b64(overlay_bgr),
            "binary_jpeg": _to_b64(binary_bgr),
            "error": None,
        }
    except Exception as ex:
        return {"stats": None, "overlay_jpeg": None, "binary_jpeg": None, "error": str(ex)}


# ---------- guardar imagen capturada en un informe de Calidad ----------

@api_router.post("/save-to-report/{report_id}")
def save_to_report(report_id: str, payload: dict = Body(...), _: dict = Depends(devices.require_editor_device)):
    """Adjunta la imagen actualmente capturada (con overlay opcional
    quemado encima, ya armado del lado del cliente) a un informe de
    Calidad existente -- puente entre esta página standalone y el ABM de
    informes, ya que a diferencia del popup del original, esta página no
    conoce de antemano a qué informe pertenece la captura."""
    import base64
    import uuid

    from .. import datos
    from .calidad import _normalize_report_images

    image_b64 = payload.get("image_jpeg", "")
    comentario = str(payload.get("comentario", "") or "").strip()
    if not image_b64:
        raise HTTPException(status_code=400, detail={"error": "sin_imagen"})

    reports = datos.load_quality_reports()
    idx = next((i for i, r in enumerate(reports) if r.get("id") == report_id), None)
    if idx is None:
        raise HTTPException(status_code=404, detail={"error": "informe_no_encontrado"})

    try:
        raw = base64.b64decode(image_b64)
    except Exception:
        raise HTTPException(status_code=400, detail={"error": "imagen_invalida"})

    dest_dir = Path(datos.ensure_quality_images_dir())
    dest_name = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex}.jpg"
    dest = dest_dir / dest_name
    dest.write_bytes(raw)

    image = {
        "id": uuid.uuid4().hex,
        "nombre": f"camara_{dest_name}",
        "path": str(dest),
        "comentario": comentario,
        "added_at": datetime.now().isoformat(timespec="seconds"),
    }
    report = dict(reports[idx])
    report["imagenes"] = _normalize_report_images(list(report.get("imagenes", [])) + [image])
    reports[idx] = report
    datos.save_quality_reports(reports)
    return image


@api_router.get("/report-targets")
def report_targets(_: dict = Depends(devices.require_approved_device)):
    """Lista de sesion(colada)/material con informe de Calidad ya creado, para el selector "Guardar en ->
    Sesión / Material" de la cámara -- el destino se elige recién al guardar, con estos dos combos."""
    from .. import datos

    reports = datos.load_quality_reports()
    targets = []
    for r in reports:
        lote = str(r.get("lote", "") or "").strip()
        material = str(r.get("material", "") or "").strip()
        if not lote or not material:
            continue
        targets.append({"report_id": r.get("id"), "lote": lote, "material": material})
    targets.sort(key=lambda t: t["lote"], reverse=True)
    return {"targets": targets}


router.include_router(api_router)
