"""Publicar retos (issue 7.1): POST /retos.

Quién puede publicar
- Solo cuentas COMPRADORAS en modo normal, con el CORREO VERIFICADO y la cuenta activa (no suspendida).
- Si falta verificar el correo responde 403 con el mensaje «Verifica tu correo para publicar un reto» (la app
  manda a la pantalla de correo; ver PuertaCorreo).

Qué se rechaza (422, no se guarda nada; ver filtros_retos.py)
- Datos de contacto, direcciones exactas y lenguaje que pida dinero por adelantado, en el título, la descripción
  y la habilidad pedida.

Límites contra spam
- MAX_RETOS_DIA retos publicados en las últimas 24 horas por usuaria (cuentan también los que el equipo rechace).
- MAX_RETOS_PENDIENTES retos suyos esperando revisión o abiertos a la vez.
- No se puede publicar dos veces el mismo título mientras el primero siga en revisión o abierto.

Después de publicar
- El reto queda en estado 'en_revision': no aparece en el tablero hasta que el equipo lo apruebe.
- Se avisa por correo al equipo (REVISION_CORREO o, si no existe, REPORTES_CORREO). Si el correo falla, el reto
  queda guardado igual.
- Acepta el encabezado opcional Idempotency-Key: reenviar la misma publicación no crea otro reto.
"""
import logging
import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel, field_validator

from correo import enviar_correo
from db import obtener_conexion
from dependencias import usuaria_compradora
from filtros_retos import explicar, motivos
from idempotencia import clave_idempotencia, guardar_respuesta, reservar

log = logging.getLogger("crisalida.retos")
router = APIRouter(prefix="/retos", tags=["Microrretos"])

MAX_RETOS_DIA = 3
MAX_RETOS_PENDIENTES = 10
RECOMPENSA_MIN = Decimal("10")
RECOMPENSA_MAX = Decimal("5000")
PLAZO_MIN = timedelta(hours=1)
PLAZO_MAX = timedelta(days=60)


class RetoIn(BaseModel):
    titulo: str
    categoria_id: int
    descripcion: str
    compensacion: Decimal                       # «Recompensa» en pesos (MXN)
    fecha_limite: datetime                      # día + hora límite, con zona horaria (ej. 2026-12-01T18:00:00-06:00)
    duracion_min: int = 60                      # tiempo aproximado; el diseño aún no lo pide
    dificultad: Literal["facil", "media", "dificil"] = "media"
    habilidad_requerida: str | None = None

    @field_validator("titulo")
    @classmethod
    def _titulo(cls, v: str) -> str:
        v = " ".join(v.split())
        if not 5 <= len(v) <= 120:
            raise ValueError("El título debe tener entre 5 y 120 caracteres")
        return v

    @field_validator("descripcion")
    @classmethod
    def _descripcion(cls, v: str) -> str:
        v = v.strip()
        if not 20 <= len(v) <= 1500:
            raise ValueError("La descripción debe tener entre 20 y 1500 caracteres")
        return v

    @field_validator("compensacion")
    @classmethod
    def _compensacion(cls, v: Decimal) -> Decimal:
        if not v.is_finite() or not RECOMPENSA_MIN <= v <= RECOMPENSA_MAX:
            raise ValueError(f"La recompensa debe estar entre ${RECOMPENSA_MIN} y ${RECOMPENSA_MAX} MXN")
        return v.quantize(Decimal("0.01"))

    @field_validator("duracion_min")
    @classmethod
    def _duracion(cls, v: int) -> int:
        if not 5 <= v <= 1440:
            raise ValueError("La duración aproximada debe ser de 5 minutos a 24 horas")
        return v

    @field_validator("habilidad_requerida")
    @classmethod
    def _habilidad(cls, v: str | None) -> str | None:
        v = " ".join(v.split()) if v else None
        if v and len(v) > 80:
            raise ValueError("La habilidad pedida puede tener hasta 80 caracteres")
        return v or None

    @field_validator("fecha_limite")
    @classmethod
    def _fecha(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("La fecha límite debe incluir la zona horaria (por ejemplo -06:00)")
        ahora = datetime.now(timezone.utc)
        if v < ahora + PLAZO_MIN:
            raise ValueError("La fecha límite debe ser al menos una hora después de ahora")
        if v > ahora + PLAZO_MAX:
            raise ValueError("La fecha límite no puede ser a más de 60 días")
        return v


def _avisar_al_equipo(reto_id: str, titulo: str, descripcion: str, seudonimo: str, compensacion: Decimal) -> None:
    """Segundo plano: avisa que hay un reto por revisar. Nunca rompe nada."""
    destino = (os.getenv("REVISION_CORREO") or os.getenv("REPORTES_CORREO") or "").strip()
    if not destino:
        log.warning("Reto %s en revisión: falta REVISION_CORREO / REPORTES_CORREO para avisar al equipo", reto_id)
        return
    enviar_correo(
        destino,
        "Crisálida: reto nuevo por revisar",
        f"{seudonimo} publicó un reto y espera revisión.\n\nId: {reto_id}\nTítulo: {titulo}\n"
        f"Recompensa: ${compensacion} MXN\n\nDescripción:\n{descripcion}\n",
    )


@router.post("", status_code=status.HTTP_201_CREATED)
def publicar_reto(datos: RetoIn, segundo_plano: BackgroundTasks,
                  usuaria: dict = Depends(usuaria_compradora),
                  clave: str | None = Depends(clave_idempotencia)):
    """Publica un reto. Queda 'en_revision' hasta que el equipo lo apruebe."""
    uid = usuaria["id"]

    # Filtros de seguridad (no tocan la BD): se revisan antes de bloquear nada
    problemas = {"título": motivos(datos.titulo), "descripción": motivos(datos.descripcion),
                 "campo de habilidad": motivos(datos.habilidad_requerida)}
    if any(problemas.values()):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, explicar(problemas))

    with obtener_conexion() as conn:
        try:
            with conn.cursor() as cur:
                # Bloquea a la usuaria: dos publicaciones a la vez no se saltan el límite
                cur.execute("SELECT seudonimo, correo_verificado, estado FROM usuarias WHERE id = %s FOR UPDATE", (uid,))
                u = cur.fetchone()
                if u is None:
                    raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sesión inválida o expirada")
                if clave:
                    previa = reservar(cur, uid, clave, "publicar_reto")
                    if previa is not None:
                        conn.rollback()
                        return previa
                if not u["correo_verificado"]:
                    raise HTTPException(status.HTTP_403_FORBIDDEN, "Verifica tu correo para publicar un reto")
                if u["estado"] != "activa":
                    raise HTTPException(status.HTTP_403_FORBIDDEN, "Tu cuenta está en reposo. Reactívala para publicar")

                cur.execute("SELECT 1 FROM categorias WHERE id = %s AND ambito = 'reto'", (datos.categoria_id,))
                if cur.fetchone() is None:
                    raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Elige una categoría de reto válida")

                cur.execute("""SELECT count(*) FILTER (WHERE creado_en > now() - interval '24 hours') AS hoy,
                                      count(*) FILTER (WHERE estado IN ('en_revision', 'abierto')) AS pendientes,
                                      bool_or(lower(titulo) = lower(%s) AND estado IN ('en_revision', 'abierto')) AS repetido
                                 FROM retos WHERE publicado_por = %s""", (datos.titulo, uid))
                n = cur.fetchone()
                if n["hoy"] >= MAX_RETOS_DIA:
                    raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS,
                                        f"Ya publicaste {MAX_RETOS_DIA} retos hoy. Intenta de nuevo mañana")
                if n["pendientes"] >= MAX_RETOS_PENDIENTES:
                    raise HTTPException(status.HTTP_409_CONFLICT,
                                        "Ya tienes muchos retos abiertos o en revisión. Espera a que se resuelvan")
                if n["repetido"]:
                    raise HTTPException(status.HTTP_409_CONFLICT, "Ya publicaste un reto con ese mismo título")

                cur.execute(
                    """INSERT INTO retos (publicado_por, categoria_id, titulo, descripcion, compensacion,
                                          duracion_min, dificultad, habilidad_requerida, fecha_limite, estado)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'en_revision') RETURNING id""",
                    (uid, datos.categoria_id, datos.titulo, datos.descripcion, datos.compensacion,
                     datos.duracion_min, datos.dificultad, datos.habilidad_requerida, datos.fecha_limite),
                )
                reto_id = str(cur.fetchone()["id"])
                respuesta = {"reto_id": reto_id, "estado": "en_revision",
                             "mensaje": "Recibimos tu reto. Nuestro equipo lo revisará y te avisará cuando esté aprobado."}
                if clave:
                    guardar_respuesta(cur, uid, clave, respuesta)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    segundo_plano.add_task(_avisar_al_equipo, reto_id, datos.titulo, datos.descripcion,
                           u["seudonimo"], datos.compensacion)
    return respuesta