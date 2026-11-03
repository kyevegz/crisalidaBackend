"""
PIN, sesiones (JWT) y cifrado AES-256-GCM.

- El PIN nunca se guarda: se guarda bcrypt( HMAC(PIN_PEPPER, pin) ).
  Un PIN de 6 dígitos tiene solo 1,000,000 de combinaciones; con el "pepper"
  (que vive en el .env y NO en la base) una filtración de la base por sí sola
  no permite adivinar los PIN.
- AES-256-GCM es para datos sensibles (notas privadas, ubicaciones).
"""
import base64
import hashlib
import hmac
import os
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt  # PyJWT
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from dotenv import load_dotenv

load_dotenv()


def _requerida(nombre: str) -> str:
    valor = os.getenv(nombre)
    if not valor:
        raise RuntimeError(f"Falta la variable {nombre} en el archivo .env")
    return valor


PIN_PEPPER = _requerida("PIN_PEPPER").encode()
JWT_SECRET = _requerida("JWT_SECRET")
JWT_HORAS = int(os.getenv("JWT_HORAS", "24"))

_CLAVE_AES = base64.b64decode(_requerida("CLAVE_AES"))
if len(_CLAVE_AES) != 32:
    raise RuntimeError("CLAVE_AES debe ser de 32 bytes (AES-256) en base64")


# ---------------------------------------------------------------- PIN

def _preparar_pin(pin: str) -> bytes:
    digest = hmac.new(PIN_PEPPER, pin.encode(), hashlib.sha256).digest()
    return base64.b64encode(digest)  # 44 bytes, cabe en el límite de 72 de bcrypt


def hashear_pin(pin: str) -> str:
    return bcrypt.hashpw(_preparar_pin(pin), bcrypt.gensalt(rounds=12)).decode()


def verificar_pin(pin: str, hash_guardado: str) -> bool:
    try:
        return bcrypt.checkpw(_preparar_pin(pin), hash_guardado.encode())
    except ValueError:
        return False


# Hash de relleno: se verifica cuando el seudónimo no existe, para que el login
# tarde lo mismo y no revele qué seudónimos están registrados.
HASH_FALSO = hashear_pin("000000")


# ---------------------------------------------------------------- JWT

def crear_token(usuaria_id: str, modo: str) -> str:
    ahora = datetime.now(timezone.utc)
    payload = {
        "sub": usuaria_id,
        "modo": modo,  # "normal" o "camuflaje"
        "iat": ahora,
        "exp": ahora + timedelta(hours=JWT_HORAS),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


def decodificar_token(token: str) -> dict:
    return jwt.decode(token, JWT_SECRET, algorithms=["HS256"])


# ---------------------------------------------------------------- AES-256-GCM

def cifrar_texto(texto: str) -> str:
    """Devuelve base64( nonce(12) + texto_cifrado + etiqueta ). Cada llamada usa un nonce nuevo."""
    nonce = os.urandom(12)
    cifrado = AESGCM(_CLAVE_AES).encrypt(nonce, texto.encode("utf-8"), None)
    return base64.b64encode(nonce + cifrado).decode()


def descifrar_texto(valor: str) -> str:
    datos = base64.b64decode(valor)
    nonce, cifrado = datos[:12], datos[12:]
    return AESGCM(_CLAVE_AES).decrypt(nonce, cifrado, None).decode("utf-8")

# ---------------------------------------------------------------- PASE TEMPORAL DE REGISTRO
# La cuenta se crea hasta terminar el radar, así que durante el radar todavía no hay "usuaria".
# /auth/validar-registro entrega este pase (modo "registro", sub = seudónimo): sirve SOLO para
# usar el radar y para el registro final; no abre ningún otro endpoint.

REGISTRO_MINUTOS = int(os.getenv("REGISTRO_MINUTOS", "120"))


def crear_token_registro(seudonimo: str) -> str:
    ahora = datetime.now(timezone.utc)
    payload = {
        "sub": seudonimo,
        "modo": "registro",
        "iat": ahora,
        "exp": ahora + timedelta(minutes=REGISTRO_MINUTOS),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")
