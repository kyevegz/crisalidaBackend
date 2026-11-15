"""Dependencias de sesión compartidas por todos los routers (auth, radar, marketplace...)."""
import jwt  # PyJWT
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from db import obtener_conexion
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


def _sesion_vigente(datos: dict) -> None:
    """El token lleva la versión de sesión con la que se emitió ('sv'; los anteriores a esto valen 0).
    Si la usuaria recuperó su PIN, su versión subió y las sesiones anteriores ya no sirven."""
    with obtener_conexion() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT version_sesion FROM usuarias WHERE id = %s", (datos["sub"],))
            fila = cur.fetchone()
    if fila is None or fila["version_sesion"] != datos.get("sv", 0):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sesión inválida o expirada")


def usuaria_actual(cred: HTTPAuthorizationCredentials = Depends(esquema_bearer)) -> dict:
    """Sesión de una usuaria YA registrada (normal o camuflaje).
    El pase temporal del registro ('registro') NO sirve aquí: su 'sub' es un seudónimo, no un id."""
    datos = _datos_token(cred)
    if datos.get("modo") not in ("normal", "camuflaje"):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sesión inválida o expirada")
    _sesion_vigente(datos)
    # Los tokens emitidos antes del rol no lo traen: todas esas cuentas eran vendedoras
    return {"id": datos["sub"], "modo": datos["modo"], "rol": datos.get("rol", "vendedora")}


def usuaria_modo_normal(usuaria: dict = Depends(usuaria_actual)) -> dict:
    """Úsala en los endpoints con datos reales: bloquea las sesiones en modo camuflaje."""
    if usuaria["modo"] != "normal":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "No disponible")
    return usuaria


def exigir_rol(*roles: str):
    """Fabrica una dependencia que solo deja pasar a las cuentas (modo normal) con alguno de estos roles.
    Si el rol no coincide responde 403. Se usa así:  usuaria: dict = Depends(usuaria_vendedora)"""
    def dependencia(usuaria: dict = Depends(usuaria_modo_normal)) -> dict:
        if usuaria["rol"] not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "No disponible")
        return usuaria
    return dependencia


# Funciones de la vendedora: bienestar, mascota (Lilu), portafolio, radar y retos propios
usuaria_vendedora = exigir_rol("vendedora")
# Funciones exclusivas de la compradora (se usarán en las etapas siguientes)
usuaria_compradora = exigir_rol("compradora")


def sesion_radar(cred: HTTPAuthorizationCredentials = Depends(esquema_bearer)) -> dict:
    """El radar lo usa una usuaria ya registrada (modo normal) O una persona que está
    en pleno registro (pase temporal 'registro', todavía sin cuenta)."""
    datos = _datos_token(cred)
    if datos.get("modo") not in ("normal", "registro"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "No disponible")
    # El radar es de la vendedora: una compradora ya registrada no lo usa
    # (el pase 'registro' todavía no tiene rol: la persona aún no tiene cuenta)
    if datos["modo"] == "normal" and datos.get("rol", "vendedora") != "vendedora":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "No disponible")
    if datos["modo"] == "normal":
        _sesion_vigente(datos)
    return {"id": datos["sub"], "modo": datos["modo"]}


def sesion_registro(cred: HTTPAuthorizationCredentials = Depends(esquema_bearer)) -> dict:
    """Solo el pase temporal del registro (lo entrega /auth/validar-registro). 'id' = seudónimo."""
    datos = _datos_token(cred)
    if datos.get("modo") != "registro":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "No disponible")
    return {"id": datos["sub"], "modo": "registro"}