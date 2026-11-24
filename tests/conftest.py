"""Configuración común de las pruebas.

Las pruebas NO usan la base de datos ni los secretos reales: aquí se fijan valores falsos ANTES de importar
`seguridad.py`, que exige estas variables al cargarse.
"""
import base64
import os
import sys
from pathlib import Path

os.environ.setdefault("PIN_PEPPER", "pepper-solo-para-pruebas")
os.environ.setdefault("JWT_SECRET", "secreto-jwt-solo-para-pruebas-0123456789")
os.environ.setdefault("CLAVE_AES", base64.b64encode(bytes(range(32))).decode())

# Para poder hacer `import seguridad` desde la carpeta tests/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
