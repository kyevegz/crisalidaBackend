"""Dependencias de sesión compartidas por todos los routers (auth, radar, marketplace...)."""
import jwt  # PyJWT
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from seguridad import decodificar_token

esquema_bearer = HTTPBearer(auto_error=False)


def _datos_token(cred: HTTPAuthorizationCredentials | None) -> dict:
    """Valida el token del encabezado 'Authorization: Bearer ...' y devuelve su contenido."""
    if cred is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sesión no iniciada")
    try:
        return decodificar_token(cred.credentials)
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sesión inválida o expirada")


def usuaria_actual(cred: HTTPAuthorizationCredentials = Depends(esquema_bearer)) -> dict:
    """Sesión de una usuaria YA registrada (normal o camuflaje).
    El pase temporal del registro ('registro') NO sirve aquí: su 'sub' es un seudónimo, no un id."""
    datos = _datos_token(cred)
    if datos.get("modo") not in ("normal", "camuflaje"):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sesión inválida o expirada")
    return {"id": datos["sub"], "modo": datos["modo"]}


def usuaria_modo_normal(usuaria: dict = Depends(usuaria_actual)) -> dict:
    """Úsala en los endpoints con datos reales: bloquea las sesiones en modo camuflaje."""
    if usuaria["modo"] != "normal":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "No disponible")
    return usuaria


def sesion_radar(cred: HTTPAuthorizationCredentials = Depends(esquema_bearer)) -> dict:
    """El radar lo usa una usuaria ya registrada (modo normal) O una persona que está
    en pleno registro (pase temporal 'registro', todavía sin cuenta)."""
    datos = _datos_token(cred)
    if datos.get("modo") not in ("normal", "registro"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "No disponible")
    return {"id": datos["sub"], "modo": datos["modo"]}


def sesion_registro(cred: HTTPAuthorizationCredentials = Depends(esquema_bearer)) -> dict:
    """Solo el pase temporal del registro (lo entrega /auth/validar-registro). 'id' = seudónimo."""
    datos = _datos_token(cred)
    if datos.get("modo") != "registro":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "No disponible")
    return {"id": datos["sub"], "modo": "registro"}
