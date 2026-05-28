#!/usr/bin/env python3
"""
Lanza la app AjustesRomero apuntando al mock Carbomax local.

Uso:
  1. En una terminal:  python3 mock_carbomax.py
  2. En otra terminal: python3 run_with_mock.py
"""
import os
import sys

os.chdir("/var/home/matias/AjustesRomero")
sys.path.insert(0, "/var/home/matias/AjustesRomero")

import device_sync
import tab_analisis_termico

MOCK_IP = "127.0.0.1:8888"

tab_analisis_termico.DEFAULT_THERMAL_DEVICE_IP = MOCK_IP

_orig_ws = device_sync.WatchService.__init__
def _patched_ws(self, ip, on_carbon=None, on_status=None, interval=None):
    _orig_ws(self, MOCK_IP, on_carbon=on_carbon, on_status=on_status, interval=interval)
device_sync.WatchService.__init__ = _patched_ws

_orig_ds = device_sync.DeviceSyncService.__init__
def _patched_ds(self, ip, on_done=None, on_log=None):
    _orig_ds(self, MOCK_IP, on_done=on_done, on_log=on_log)
device_sync.DeviceSyncService.__init__ = _patched_ds

print(f"[MOCK] App apuntando a {MOCK_IP}")
print(f"[MOCK] Abrí http://localhost:8888 para agregar lecturas de carbono.")
print()

import app
app.main()
