"""Datos de contacto de la usuaria: correo (opcional, se verifica con un código), municipio y localidad.

- El correo es PRIVADO: solo la propia usuaria lo ve. Ningún endpoint de marketplace o retos lo devuelve.
- La ubicación es gruesa (municipio y localidad escritos por ella), nunca GPS.
- El código de verificación (6 dígitos) se guarda solo como hash, vence y tiene límites de intentos
  y de solicitudes para que nadie pueda usar la app para llenar de correos a otra persona.
- Si el correo no se puede enviar no se rompe nada: se avisa a la usuaria y el error queda registrado.
"""
import os
import secrets

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, field_validator

from correo import CORREO_RE, enviar_correo
from db import obtener_conexion
from dependencias import usuaria_modo_normal
from seguridad import hashear_pin, verificar_pin

router = APIRouter(prefix="/perfil", tags=["Datos personales"])

CODIGO_MINUTOS = int(os.getenv("CORREO_CODIGO_MINUTOS", "15"))   # cuánto dura un código
ESPERA_REENVIO_SEGUNDOS = 60    # mínimo entre un código y el siguiente
MAX_ENVIOS_DIA = 5              # códigos que se pueden pedir en 24 horas
MAX_INTENTOS_CODIGO = 5         # equivocaciones antes de tener que pedir otro código


# ============================================================ MODELOS

def _lugar(v: str | None) -> str | None:
    """Limpia municipio/localidad: espacios de más fuera; vacío = borrar el dato."""
    if v is None:
        return None
    v = " ".join(v.split())
    if len(v) > 80:
        raise ValueError("Escribe máximo 80 caracteres")
    return v or None


class UbicacionIn(BaseModel):
    """Solo se actualizan los campos que vengan en la petición; mandar vacío borra ese dato."""
    municipio: str | None = None
    localidad: str | None = None

    @field_validator("municipio", "localidad")
    @classmethod
    def _limpiar(cls, v: str | None) -> str | None:
        return _lugar(v)


class CorreoIn(BaseModel):
    correo: str

    @field_validator("correo")
    @classmethod
    def _correo(cls, v: str) -> str:
        v = v.strip().lower()
        if len(v) > 254 or not CORREO_RE.match(v):
            raise ValueError("Escribe un correo válido")
        return v


class CodigoIn(BaseModel):
    codigo: str

    @field_validator("codigo")
    @classmethod
    def _codigo(cls, v: str) -> str:
        v = v.strip()
        if not (v.isascii() and v.isdigit() and len(v) == 6):
            raise ValueError("El código tiene 6 dígitos")
        return v


# ============================================================ AYUDAS

def _datos(cur, uid) -> dict:
    cur.execute("SELECT correo, correo_verificado, municipio, localidad FROM usuarias WHERE id = %s", (uid,))
    u = cur.fetchone()
    if u is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Usuaria no encontrada")
    return {"correo": u["correo"], "correo_verificado": u["correo_verificado"],
            "municipio": u["municipio"], "localidad": u["localidad"]}


# ============================================================ ENDPOINTS

@router.get("/datos")
def mis_datos(usuaria: dict = Depends(usuaria_modo_normal)):
    """Correo (con si está verificado), municipio y localidad de la propia usuaria."""
    with obtener_conexion() as conn:
        with conn.cursor() as cur:
            return _datos(cur, usuaria["id"])


@router.put("/datos")
def guardar_ubicacion(datos: UbicacionIn, usuaria: dict = Depends(usuaria_modo_normal)):
    """Guarda municipio y/o localidad. Solo cambia lo que venga en la petición."""
    cambios = {campo: getattr(datos, campo) for campo in datos.model_fields_set}
    if not cambios:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "No hay datos para guardar")
    # Los nombres de columna salen de los campos del modelo (municipio, localidad), nunca de la petición
    asignaciones = ", ".join(f"{campo} = %s" for campo in cambios)
    with obtener_conexion() as conn:
        try:
            with conn.cursor() as cur:
                cur.execute(f"UPDATE usuarias SET {asignaciones} WHERE id = %s", (*cambios.values(), usuaria["id"]))
                resultado = _datos(cur, usuaria["id"])
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    return resultado


@router.post("/correo")
def guardar_correo(datos: CorreoIn, usuaria: dict = Depends(usuaria_modo_normal)):
    """Guarda el correo (queda SIN verificar) y manda un código de verificación.
    También sirve para pedir un código nuevo del mismo correo."""
    uid = usuaria["id"]
    # El hash tarda un poco: se hace antes de pedir la conexión
    codigo = f"{secrets.randbelow(10**6):06d}"
    codigo_hash = hashear_pin(codigo)

    with obtener_conexion() as conn:
        try:
            with conn.cursor() as cur:
                actual = _datos(cur, uid)
                if actual["correo"] == datos.correo and actual["correo_verificado"]:
                    return {"correo_verificado": True, "mensaje": "Ese correo ya está verificado"}

                # Solo se guardan 24 horas: alcanza para los límites de abajo
                cur.execute("DELETE FROM verificaciones_correo WHERE creado_en < now() - interval '1 day'")
                cur.execute(
                    """SELECT count(*) AS total,
                              coalesce(max(creado_en) > now() - make_interval(secs => %s), FALSE) AS reciente
                         FROM verificaciones_correo WHERE usuaria_id = %s""",
                    (ESPERA_REENVIO_SEGUNDOS, uid),
                )
                limites = cur.fetchone()
                if limites["total"] >= MAX_ENVIOS_DIA:
                    raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS,
                                        "Pediste demasiados códigos hoy. Inténtalo mañana")
                if limites["reciente"]:
                    raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS,
                                        "Espera un minuto antes de pedir otro código")

                cur.execute("UPDATE usuarias SET correo = %s, correo_verificado = FALSE WHERE id = %s",
                            (datos.correo, uid))
                cur.execute(
                    """INSERT INTO verificaciones_correo (usuaria_id, correo, codigo_hash, expira_en)
                       VALUES (%s, %s, %s, now() + make_interval(mins => %s)) RETURNING id""",
                    (uid, datos.correo, codigo_hash, CODIGO_MINUTOS),
                )
                solicitud_id = cur.fetchone()["id"]
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    # El correo se manda FUERA de la transacción (puede tardar unos segundos)
    texto = (f"Tu código de verificación es {codigo}.\n\n"
             f"Vence en {CODIGO_MINUTOS} minutos. Si no lo pediste, ignora este mensaje.")
    if not enviar_correo(datos.correo, "Tu código de verificación", texto):
        # No salió: se quita la solicitud para que no cuente en los límites y pueda reintentar
        with obtener_conexion() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM verificaciones_correo WHERE id = %s", (solicitud_id,))
            conn.commit()
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            "No pudimos enviar el correo. Inténtalo de nuevo en unos minutos")
    return {"correo_verificado": False, "expira_en_minutos": CODIGO_MINUTOS,
            "mensaje": "Te enviamos un código para confirmar que el correo es tuyo"}


@router.post("/correo/verificar")
def verificar_correo(datos: CodigoIn, usuaria: dict = Depends(usuaria_modo_normal)):
    """Confirma el correo con el código que llegó. Vence y tiene límite de intentos."""
    uid = usuaria["id"]
    with obtener_conexion() as conn:
        try:
            with conn.cursor() as cur:
                actual = _datos(cur, uid)
                if actual["correo"] is None:
                    raise HTTPException(status.HTTP_409_CONFLICT, "Primero agrega tu correo")
                if actual["correo_verificado"]:
                    return {"correo_verificado": True}

                # Solo vale el código más reciente, sin usar, vigente y del correo que tiene ahora
                cur.execute(
                    """SELECT id, codigo_hash, intentos FROM verificaciones_correo
                        WHERE usuaria_id = %s AND correo = %s AND NOT usado AND expira_en > now()
                        ORDER BY creado_en DESC LIMIT 1 FOR UPDATE""",
                    (uid, actual["correo"]),
                )
                pedido = cur.fetchone()
                if pedido is None:
                    raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                        "El código venció o no existe. Pide uno nuevo")
                if pedido["intentos"] >= MAX_INTENTOS_CODIGO:
                    raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS,
                                        "Demasiados intentos. Pide un código nuevo")

                if not verificar_pin(datos.codigo, pedido["codigo_hash"]):
                    cur.execute("UPDATE verificaciones_correo SET intentos = intentos + 1 WHERE id = %s",
                                (pedido["id"],))
                    conn.commit()   # el intento fallido se cuenta aunque la petición termine en error
                    raise HTTPException(status.HTTP_400_BAD_REQUEST, "Código incorrecto")

                cur.execute("UPDATE verificaciones_correo SET usado = TRUE WHERE id = %s", (pedido["id"],))
                cur.execute("UPDATE usuarias SET correo_verificado = TRUE WHERE id = %s", (uid,))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    return {"correo_verificado": True}


@router.delete("/correo")
def quitar_correo(usuaria: dict = Depends(usuaria_modo_normal)):
    """Quita el correo (es opcional) y los códigos pendientes."""
    with obtener_conexion() as conn:
        try:
            with conn.cursor() as cur:
                cur.execute("UPDATE usuarias SET correo = NULL, correo_verificado = FALSE WHERE id = %s",
                            (usuaria["id"],))
                cur.execute("DELETE FROM verificaciones_correo WHERE usuaria_id = %s", (usuaria["id"],))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    return {"correo": None, "correo_verificado": False}