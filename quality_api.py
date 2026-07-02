"""
Servidor HTTP para la app web de cámara de calidad — puerto 50501.
Patrón idéntico a host_api.py (http.server + ThreadingHTTPServer).
"""
import base64
import json
import re
import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import quality_analyzer as qa

QUALITY_API_HOST = "0.0.0.0"
QUALITY_API_PORT = 50501
QUALITY_WEB_DIR = Path(__file__).resolve().parent / "web_quality"
MAX_BODY_BYTES = 4 * 1024           # body de /api/analyze (solo JSON pequeño)
MJPEG_BOUNDARY = b"mjpegframe"
STREAM_FPS = 15                     # fps para el stream MJPEG

# ---------- Estado de calibración activa (sincronizado con el popup desktop) ----------
_active_camera_cal_id: str | None = None
_desktop_camera_open: bool = False


def set_active_camera_cal(cal_id: str | None):
    global _active_camera_cal_id, _desktop_camera_open
    _active_camera_cal_id = cal_id
    _desktop_camera_open = cal_id is not None


def get_active_camera_cal() -> str | None:
    return _active_camera_cal_id


def is_desktop_camera_open() -> bool:
    return _desktop_camera_open


# ---------- Frame capturado (congelado por POST /api/capture) ----------
_captured_frame_bgr = None
_captured_lock = threading.Lock()


def _store_captured(frame_bgr):
    global _captured_frame_bgr
    with _captured_lock:
        _captured_frame_bgr = frame_bgr.copy() if frame_bgr is not None else None


def _get_captured():
    with _captured_lock:
        return _captured_frame_bgr.copy() if _captured_frame_bgr is not None else None


# ---------- Camera streamer ----------
class _CameraStreamer:
    """Captura continua desde la webcam. Un solo VideoCapture compartido."""

    def __init__(self):
        self._frame: bytes | None = None          # último JPEG
        self._frame_bgr = None                    # último frame BGR (para análisis)
        self._lock = threading.Lock()
        self._clients = 0
        self._running = False
        self._thread: threading.Thread | None = None
        self._cap = None
        self._error: str | None = None

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
            if ret and test is not None:
                break
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

        self._cap = cap
        interval = 1.0 / STREAM_FPS
        while self._running:
            t0 = time.monotonic()
            ret, frame = cap.read()
            if ret and frame is not None:
                ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
                if ok:
                    with self._lock:
                        self._frame = bytes(buf)
                        self._frame_bgr = frame
            elapsed = time.monotonic() - t0
            rest = interval - elapsed
            if rest > 0:
                time.sleep(rest)

        try:
            cap.release()
        except Exception:
            pass
        self._cap = None

    def get_jpeg(self) -> bytes | None:
        with self._lock:
            return self._frame

    def get_bgr(self):
        with self._lock:
            return self._frame_bgr.copy() if self._frame_bgr is not None else None

    @property
    def error(self) -> str | None:
        return self._error


_streamer = _CameraStreamer()


# ---------- Helpers HTTP ----------
def _local_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def _json_response(handler, data: dict, status: int = 200):
    body = json.dumps(data, ensure_ascii=False).encode()
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.end_headers()
    handler.wfile.write(body)


def _jpeg_response(handler, data: bytes):
    handler.send_response(200)
    handler.send_header("Content-Type", "image/jpeg")
    handler.send_header("Content-Length", str(len(data)))
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.end_headers()
    handler.wfile.write(data)


def _static_response(handler, path: Path):
    ext = path.suffix.lower()
    mime = {
        ".html": "text/html; charset=utf-8",
        ".js": "application/javascript; charset=utf-8",
        ".css": "text/css; charset=utf-8",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".ico": "image/x-icon",
        ".svg": "image/svg+xml",
    }.get(ext, "application/octet-stream")
    try:
        data = path.read_bytes()
    except OSError:
        handler.send_error(404)
        return
    handler.send_response(200)
    handler.send_header("Content-Type", mime)
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)


def _error_jpeg(message: str) -> bytes:
    """Genera un frame JPEG negro con texto de error."""
    import cv2
    import numpy as np
    img = np.zeros((360, 640, 3), dtype=np.uint8)
    lines = [message[i:i+50] for i in range(0, len(message), 50)]
    y = 160
    for line in lines:
        cv2.putText(img, line, (20, y), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 80, 200), 2)
        y += 36
    _, buf = cv2.imencode(".jpg", img)
    return bytes(buf)


# ---------- Handler ----------
class _QualityHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass  # silenciar logs en consola

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        path = self.path.split("?")[0].rstrip("/") or "/"

        if path == "/" or path == "/index.html":
            _static_response(self, QUALITY_WEB_DIR / "index.html")
        elif path in ("/app.js", "/app.css"):
            _static_response(self, QUALITY_WEB_DIR / path.lstrip("/"))
        elif path == "/api/health":
            _json_response(self, {"ok": True})
        elif path == "/api/calibraciones":
            self._handle_calibraciones()
        elif path == "/api/mjpeg":
            self._handle_mjpeg()
        elif path == "/api/captured":
            self._handle_captured_get()
        else:
            self.send_error(404)

    def do_POST(self):
        path = self.path.split("?")[0].rstrip("/")
        if path == "/api/capture":
            self._handle_capture()
        elif path == "/api/analyze":
            self._handle_analyze()
        else:
            self.send_error(404)

    # ---- Calibraciones ----
    def _handle_calibraciones(self):
        cals = qa.load_calibrations()
        active = get_active_camera_cal()
        if active:
            effective_id = active
        else:
            effective_id = next((c["id"] for c in cals if c.get("is_default")), None)
            if not effective_id and cals:
                effective_id = cals[0]["id"]
        _json_response(self, {"calibraciones": cals, "effective_id": effective_id})

    # ---- MJPEG stream ----
    def _handle_mjpeg(self):
        if is_desktop_camera_open():
            err_frame = _error_jpeg("Cámara en uso por la app desktop")
            self._send_single_mjpeg(err_frame)
            return

        _streamer.acquire()
        try:
            self.send_response(200)
            self.send_header("Content-Type",
                             f"multipart/x-mixed-replace; boundary={MJPEG_BOUNDARY.decode()}")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            interval = 1.0 / STREAM_FPS
            while True:
                t0 = time.monotonic()
                frame = _streamer.get_jpeg()
                if frame is None:
                    if _streamer.error:
                        frame = _error_jpeg(_streamer.error or "Sin señal")
                    else:
                        time.sleep(0.1)
                        continue
                self._write_mjpeg_part(frame)
                elapsed = time.monotonic() - t0
                rest = interval - elapsed
                if rest > 0:
                    time.sleep(rest)
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            _streamer.release_client()

    def _send_single_mjpeg(self, frame: bytes):
        self.send_response(200)
        self.send_header("Content-Type",
                         f"multipart/x-mixed-replace; boundary={MJPEG_BOUNDARY.decode()}")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        try:
            self._write_mjpeg_part(frame)
        except (BrokenPipeError, OSError):
            pass

    def _write_mjpeg_part(self, frame: bytes):
        header = (
            f"--{MJPEG_BOUNDARY.decode()}\r\n"
            f"Content-Type: image/jpeg\r\n"
            f"Content-Length: {len(frame)}\r\n\r\n"
        ).encode()
        self.wfile.write(header + frame + b"\r\n")
        self.wfile.flush()

    # ---- Capturar frame ----
    def _handle_capture(self):
        if is_desktop_camera_open():
            _json_response(self, {"error": "desktop_camera_open"}, 409)
            return
        frame_bgr = _streamer.get_bgr()
        if frame_bgr is None:
            _json_response(self, {"error": "no_frame"}, 503)
            return
        _store_captured(frame_bgr)
        import cv2
        ok, buf = cv2.imencode(".jpg", frame_bgr, [cv2.IMWRITE_JPEG_QUALITY, 95])
        if not ok:
            _json_response(self, {"error": "encode_failed"}, 500)
            return
        _jpeg_response(self, bytes(buf))

    # ---- Obtener último capturado ----
    def _handle_captured_get(self):
        frame_bgr = _get_captured()
        if frame_bgr is None:
            self.send_error(404)
            return
        import cv2
        ok, buf = cv2.imencode(".jpg", frame_bgr, [cv2.IMWRITE_JPEG_QUALITY, 95])
        if not ok:
            self.send_error(500)
            return
        _jpeg_response(self, bytes(buf))

    # ---- Análisis OpenCV ----
    def _handle_analyze(self):
        length = int(self.headers.get("Content-Length", 0))
        if length > MAX_BODY_BYTES:
            _json_response(self, {"error": "body_too_large"}, 413)
            return
        try:
            body = json.loads(self.rfile.read(length).decode())
        except Exception:
            _json_response(self, {"error": "invalid_json"}, 400)
            return

        frame_bgr = _get_captured()
        if frame_bgr is None:
            _json_response(self, {"error": "no_captured_frame"}, 409)
            return

        import cv2

        mode = str(body.get("mode", "nodular"))
        threshold = int(body.get("threshold", 0) or 0)
        min_area = body.get("min_area")
        min_area = int(min_area) if min_area is not None else None
        use_open = bool(body.get("use_open", True))
        cal_id = body.get("cal_id") or None

        px_per_mm = qa.get_px_per_mm(cal_id)

        try:
            if mode == "laminar":
                stats = qa.count_laminar(frame_bgr, px_per_mm=px_per_mm,
                                         threshold=threshold, min_area=min_area,
                                         use_open=use_open)
                flakes = stats.pop("flakes", []) if stats else []
                overlay_bgr = qa.draw_laminar_overlay(frame_bgr, flakes)
            else:
                contours_data = qa.get_nodule_contours(frame_bgr, threshold=threshold,
                                                        min_area=min_area, use_open=use_open)
                stats = qa.count_nodules(frame_bgr, px_per_mm=px_per_mm,
                                          threshold=threshold, min_area=min_area,
                                          use_open=use_open)
                overlay_bgr = qa.draw_nodule_overlay(frame_bgr, contours_data)

            binary_bgr = qa.get_binary_image(frame_bgr, threshold=threshold, use_open=use_open)

            def _to_b64(img):
                ok2, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 90])
                return base64.b64encode(bytes(buf)).decode() if ok2 else ""

            _json_response(self, {
                "stats": stats,
                "overlay_jpeg": _to_b64(overlay_bgr),
                "binary_jpeg": _to_b64(binary_bgr),
                "error": None,
            })
        except Exception as ex:
            _json_response(self, {"stats": None, "error": str(ex)}, 500)


# ---------- Server wrapper ----------
class _QuietHTTPServer(ThreadingHTTPServer):
    def handle_error(self, request, client_address):
        pass


class QualityAPIServer:
    def __init__(self, host: str = QUALITY_API_HOST, port: int = QUALITY_API_PORT):
        self.host = host
        self.port = int(port)
        self.httpd = None
        self.thread = None

    def start(self) -> "QualityAPIServer":
        if self.httpd is not None:
            return self
        self.httpd = _QuietHTTPServer((self.host, self.port), _QualityHandler)
        self.port = int(self.httpd.server_address[1])
        self.thread = threading.Thread(
            target=self.httpd.serve_forever,
            name="ajuste-comp-quality-api",
            daemon=True,
        )
        self.thread.start()
        return self

    def stop(self):
        if self.httpd is None:
            return
        try:
            _streamer.release_client()
        except Exception:
            pass
        try:
            self.httpd.shutdown()
            self.httpd.server_close()
        finally:
            self.httpd = None
            self.thread = None

    def url(self) -> str:
        return f"http://{_local_ip()}:{self.port}"
