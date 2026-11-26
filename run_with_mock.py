#!/usr/bin/env python3
"""
Lanza la app AjustesRomero apuntando al emulador Carbomax local.

Uso:
  1. En una terminal:  python carbomax_emulator.py
  2. En otra terminal: python run_with_mock.py
"""
import os
import sys
from pathlib import Path

# Ruta del propio repo (antes esto era una ruta de otra maquina
# hardcodeada a mano; calcularla a partir de __file__ hace que el script
# funcione en cualquier maquina sin editarlo).
REPO_DIR = Path(__file__).resolve().parent
os.chdir(REPO_DIR)
sys.path.insert(0, str(REPO_DIR))

import tab_analisis_termico

MOCK_IP = "127.0.0.1:8766"  # puerto por defecto de carbomax_emulator.py

tab_analisis_termico.DEFAULT_THERMAL_DEVICE_IP = MOCK_IP

print(f"[MOCK] App apuntando a {MOCK_IP}")
print(f"[MOCK] Abrí http://localhost:8766 para agregar lecturas de carbono.")
print()

import app
app.main()
