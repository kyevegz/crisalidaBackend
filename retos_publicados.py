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

Mis retos publicados (issue 7.3)
- GET /retos/publicados y GET /retos/publicados/{id}: los retos de la usuaria en cualquier estado (en revisión,
  abierto, asignado, completado, rechazado, cancelado) con sus aceptaciones: quién lo tomó (seudónimo y avatar) y si
  ya lo entregó. SOLO la dueña los ve: la consulta siempre filtra por publicado_por = ella, y para otra persona un
  reto ajeno responde 404 (no confirma que existe). Ninguna otra ruta devuelve las aceptaciones de un reto.

Validar o rechazar entregas (issue 7.4)
- POST /retos/aceptaciones/{id}/validar y /rechazar: SOLO quien publicó el reto (para cualquier otra persona la
  entrega "no existe": 404). Solo se puede revisar una entrega en estado 'entregado'.
- Validar: la aceptación pasa a 'validado' y la BD (triggers) da las flores a quien hizo el reto UNA sola vez
  (índice único por aceptación) y marca el reto como 'completado'. Repetir la petición (con o sin Idempotency-Key)
  no da flores otra vez ni falla. No se mueve dinero: la recompensa en pesos se arregla fuera de la app.
- Rechazar: pide un motivo breve (5 a 300 caracteres, sin datos de contacto). La aceptación vuelve a 'aceptado'
  con el motivo guardado: la usuaria puede volver a entregar o abandonar. El reto sigue tomado por ella.
- A la usuaria se le avisa por correo (si lo tiene verificado) y lo ve en GET /retos/mis.

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

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, field_validator

from avisos import avisar_publicadora
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

# ============================================================ MIS RETOS PUBLICADOS (7.3)

_SQL_MIS_RETOS = """
SELECT r.id AS reto_id, r.titulo, r.descripcion, r.compensacion, r.fecha_limite, r.estado,
       r.motivo_rechazo, r.revisado_en, r.creado_en, c.id AS categoria_id, c.nombre AS categoria,
       COALESCE((SELECT json_agg(json_build_object(
                    'aceptacion_id', a.id, 'estado', a.estado, 'seudonimo', u.seudonimo, 'avatar', u.avatar,
                    'aceptado_en', a.aceptado_en, 'entregado_en', a.entregado_en, 'validado_en', a.validado_en,
                    'motivo_rechazo', a.motivo_rechazo, 'rechazos', a.rechazos)
                    ORDER BY a.aceptado_en DESC)
                   FROM reto_aceptaciones a JOIN usuarias u ON u.id = a.usuaria_id
                  WHERE a.reto_id = r.id), '[]'::json) AS aceptaciones
  FROM retos r JOIN categorias c ON c.id = r.categoria_id
 WHERE r.publicado_por = %s"""


def _mi_reto(f: dict) -> dict:
    d = dict(f)
    d["reto_id"] = str(d["reto_id"])
    d["compensacion"] = float(d["compensacion"])
    # La aceptación vigente (si la hay): la que está tomada, entregada o validada
    d["aceptacion_actual"] = next((a for a in d["aceptaciones"] if a["estado"] in ("aceptado", "entregado", "validado")), None)
    return d


@router.get("/publicados")
def mis_retos_publicados(estado: Literal["en_revision", "abierto", "asignado", "completado", "rechazado", "cancelado"] | None = None,
                         limite: int = Query(50, ge=1, le=100), desde: int = Query(0, ge=0),
                         usuaria: dict = Depends(usuaria_compradora)):
    """Los retos que publiqué, los más nuevos primero, con quién los tomó y si ya los entregó."""
    sql, params = _SQL_MIS_RETOS, [usuaria["id"]]
    if estado:
        sql += " AND r.estado = %s"
        params.append(estado)
    sql += " ORDER BY r.creado_en DESC, r.id LIMIT %s OFFSET %s"
    params += [limite, desde]
    with obtener_conexion() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, tuple(params))
            return {"retos": [_mi_reto(f) for f in cur.fetchall()]}


@router.get("/publicados/{reto_id}")
def mi_reto_publicado(reto_id: str, usuaria: dict = Depends(usuaria_compradora)):
    """Un reto mío con sus aceptaciones. Si el reto es de otra persona responde 404 (no confirma que existe)."""
    with obtener_conexion() as conn:
        with conn.cursor() as cur:
            cur.execute(_SQL_MIS_RETOS + " AND r.id::text = %s", (usuaria["id"], reto_id))
            f = cur.fetchone()
    if f is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No encontramos ese reto")
    return _mi_reto(f)

# ============================================================ VALIDAR / RECHAZAR ENTREGAS (7.4)

class RechazoEntregaIn(BaseModel):
    motivo: str

    @field_validator("motivo")
    @classmethod
    def _motivo(cls, v: str) -> str:
        v = " ".join(v.split())
        if not 5 <= len(v) <= 300:
            raise ValueError("Cuéntale brevemente por qué (de 5 a 300 caracteres)")
        malos = [m for m in motivos(v) if m in ("contacto", "direccion")]
        if malos:
            raise ValueError("Por seguridad, no incluyas datos de contacto ni direcciones. "
                             "La comunicación se hace dentro de Crisálida")
        return v


_SQL_ENTREGA_DE_MI_RETO = """
SELECT a.id, a.estado, a.usuaria_id, r.titulo
  FROM reto_aceptaciones a JOIN retos r ON r.id = a.reto_id
 WHERE a.id::text = %s AND r.publicado_por = %s
   FOR UPDATE OF a"""


def _flores_de(cur, aceptacion_id) -> int:
    cur.execute("SELECT COALESCE(sum(flores), 0) AS n FROM eventos_progreso WHERE tipo = 'reto' AND referencia_id = %s",
                (aceptacion_id,))
    return int(cur.fetchone()["n"])


@router.post("/aceptaciones/{aceptacion_id}/validar")
def validar_entrega(aceptacion_id: str, response: Response, segundo_plano: BackgroundTasks,
                    usuaria: dict = Depends(usuaria_compradora),
                    clave: str | None = Depends(clave_idempotencia)):
    """Da por buena la entrega: la usuaria que hizo el reto recibe sus flores (una sola vez)."""
    uid = usuaria["id"]
    with obtener_conexion() as conn:
        try:
            with conn.cursor() as cur:
                if clave:
                    previo = reservar(cur, uid, clave, f"validar:{aceptacion_id}")
                    if previo is not None:
                        conn.commit()
                        response.headers["Idempotent-Replay"] = "true"
                        return previo
                cur.execute(_SQL_ENTREGA_DE_MI_RETO, (aceptacion_id, uid))
                a = cur.fetchone()
                if a is None:
                    raise HTTPException(status.HTTP_404_NOT_FOUND, "No encontramos esa entrega")
                nuevo = a["estado"] == "entregado"
                if a["estado"] not in ("entregado", "validado"):
                    raise HTTPException(status.HTTP_409_CONFLICT, "Esta entrega todavía no se puede validar")
                if nuevo:
                    # Los triggers de la BD dan las flores (una vez, por índice único) y completan el reto
                    cur.execute("UPDATE reto_aceptaciones SET estado = 'validado' WHERE id = %s", (a["id"],))
                respuesta = {"aceptacion_id": str(a["id"]), "estado": "validado", "flores_otorgadas": _flores_de(cur, a["id"])}
                if clave:
                    guardar_respuesta(cur, uid, clave, respuesta)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    if nuevo:
        segundo_plano.add_task(
            avisar_publicadora, a["usuaria_id"], "Crisálida: validaron tu entrega",
            f"¡Felicidades! Validaron tu entrega del reto «{a['titulo']}» y ganaste "
            f"{respuesta['flores_otorgadas']} flores para Lilu. 🌸")
    return respuesta


@router.post("/aceptaciones/{aceptacion_id}/rechazar")
def rechazar_entrega(aceptacion_id: str, datos: RechazoEntregaIn, response: Response, segundo_plano: BackgroundTasks,
                     usuaria: dict = Depends(usuaria_compradora),
                     clave: str | None = Depends(clave_idempotencia)):
    """Rechaza la entrega con un motivo. La usuaria puede corregirla y volver a entregar, o abandonar el reto."""
    uid = usuaria["id"]
    with obtener_conexion() as conn:
        try:
            with conn.cursor() as cur:
                if clave:
                    previo = reservar(cur, uid, clave, f"rechazar:{aceptacion_id}")
                    if previo is not None:
                        conn.commit()
                        response.headers["Idempotent-Replay"] = "true"
                        return previo
                cur.execute(_SQL_ENTREGA_DE_MI_RETO, (aceptacion_id, uid))
                a = cur.fetchone()
                if a is None:
                    raise HTTPException(status.HTTP_404_NOT_FOUND, "No encontramos esa entrega")
                if a["estado"] != "entregado":
                    raise HTTPException(status.HTTP_409_CONFLICT, "Solo se puede rechazar una entrega que ya fue enviada")
                # Vuelve a 'aceptado' (no a 'rechazado': ese estado soltaría el reto para otra persona)
                cur.execute("""UPDATE reto_aceptaciones
                                  SET estado = 'aceptado', entregado_en = NULL, motivo_rechazo = %s,
                                      rechazado_en = now(), rechazos = rechazos + 1
                                WHERE id = %s""", (datos.motivo, a["id"]))
                respuesta = {"aceptacion_id": str(a["id"]), "estado": "aceptado", "motivo_rechazo": datos.motivo}
                if clave:
                    guardar_respuesta(cur, uid, clave, respuesta)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    segundo_plano.add_task(
        avisar_publicadora, a["usuaria_id"], "Crisálida: tu entrega necesita cambios",
        f"Revisaron tu entrega del reto «{a['titulo']}» y piden algunos cambios.\n\nMotivo: {datos.motivo}\n\n"
        "Puedes corregirla y volver a entregar, o dejar el reto si ya no puedes continuar.")
    return respuesta