"""Reportar y bloquear (issue 4.8).

Reportar
- Se puede reportar una PUBLICACIÓN (producto o servicio), un RETO o a una USUARIA, siempre con un motivo.
- Cada reporte se guarda y se manda por correo al equipo (REPORTES_CORREO). Si el correo no sale o no está
  configurado, el reporte queda guardado igual (correo_enviado_en queda en NULL).
- Un mismo reporte no se puede repetir: una persona solo puede reportar una vez la misma publicación,
  el mismo reto o a la misma usuaria (409 si lo intenta de nuevo).
- La persona reportada nunca se entera de quién la reportó.
- Los motivos de riesgo (acoso, contacto externo) o pedir «revisión prioritaria» marcan el reporte con prioridad alta.
- Tope diario de reportes por usuaria, para que nadie llene el correo del equipo.

Bloquear
- Una usuaria bloquea a otra: sus publicaciones dejan de aparecerle en el marketplace, y las de ella a la otra.
- Los retos los publican compradoras (retos.publicado_por): desde un reto también se puede reportar y bloquear a
  quien lo publicó, y sus retos dejan de aparecer. Los retos de demo no tienen cuenta detrás: se reportan, pero no
  se pueden bloquear.
- Las usuarias nunca ven los ids de otras usuarias: se identifican por una de sus publicaciones o retos, y un
  bloqueo se deshace con el id del bloqueo.
"""
import logging
import os
import uuid
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Response, status
from psycopg2 import errors as pg_errors
from pydantic import BaseModel, field_validator, model_validator

from avisos import avisar_publicadora
from correo import enviar_correo
from db import obtener_conexion
from dependencias import usuaria_modo_normal

log = logging.getLogger("crisalida.reportes")
router = APIRouter(tags=["Reportes y bloqueos"])

MAX_REPORTES_DIA = 20
REPORTES_PARA_OCULTAR = 3   # reportes distintos a un reto abierto para que pase a revisión (se oculta solo)

# Los textos son los del diseño del reporte; la app los puede pedir en GET /reportes/motivos
MOTIVOS = {
    "acoso": {
        "titulo": "Mensaje intimidante, hostigamiento o acoso",
        "descripcion": "Tono demandante, presión psicológica, amenazas encubiertas o comentarios que vulneran tu paz.",
        "riesgo": True,
    },
    "entrega_insegura": {
        "titulo": "Insiste en entrega en domicilio o punto no seguro",
        "descripcion": "Rechaza acudir a Puntos Violeta, estaciones protegidas o casilleros aliados comunitarios.",
        "riesgo": False,
    },
    "cobro_indebido": {
        "titulo": "Intento de cobro indebido o regateo abusivo",
        "descripcion": "No respeta el precio pactado, exige pagos no registrados o intenta eludir la custodia segura.",
        "riesgo": False,
    },
    "otro": {
        "titulo": "Otro motivo que me genera desconfianza",
        "descripcion": "Cualquier intuición o comportamiento extraño que merezca la revisión de una orientadora.",
        "riesgo": False,
    },
    "contacto_externo": {
        "titulo": "Pide teléfono personal o contacto externo",
        "descripcion": "Solicita WhatsApp, llamada privada o redes sociales fuera de los canales de protección autorizados.",
        "riesgo": True,
    },
}


# ============================================================ MODELOS

class ReporteIn(BaseModel):
    tipo: Literal["publicacion", "reto", "usuaria"]
    # publicacion: id de la publicación · reto: id del reto · usuaria: id de CUALQUIER publicación de esa persona
    objetivo_id: str
    motivo: Literal["acoso", "entrega_insegura", "cobro_indebido", "otro", "contacto_externo"]
    detalle: str | None = None
    bloquear: bool = False                # además de reportar, bloquear a la persona que lo publicó
    revision_prioritaria: bool = False    # pedir que una orientadora lo revise primero

    @field_validator("objetivo_id")
    @classmethod
    def _id(cls, v: str) -> str:
        try:
            return str(uuid.UUID(v.strip()))
        except ValueError:
            raise ValueError("Identificador no válido")

    @field_validator("detalle")
    @classmethod
    def _detalle(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = " ".join(v.split())
        if len(v) > 500:
            raise ValueError("Escribe máximo 500 caracteres")
        return v or None


class BloqueoIn(BaseModel):
    """Se bloquea a quien publicó la publicación o el reto indicado (manda exactamente uno de los dos)."""
    publicacion_id: str | None = None
    reto_id: str | None = None

    @field_validator("publicacion_id", "reto_id")
    @classmethod
    def _id(cls, v: str | None) -> str | None:
        if v is None:
            return None
        try:
            return str(uuid.UUID(v.strip()))
        except ValueError:
            raise ValueError("Identificador no válido")

    @model_validator(mode="after")
    def _uno_solo(self):
        if (self.publicacion_id is None) == (self.reto_id is None):
            raise ValueError("Indica una publicación o un reto")
        return self


# ============================================================ CORREO AL EQUIPO

def _enviar_al_equipo(reporte_id: int, asunto: str, texto: str) -> None:
    """Segundo plano: manda el reporte al equipo y anota que salió. Nunca rompe nada."""
    destino = os.getenv("REPORTES_CORREO", "").strip()
    if not destino:
        log.warning("Reporte %s guardado pero NO enviado: falta REPORTES_CORREO", reporte_id)
        return
    if not enviar_correo(destino, asunto, texto):
        return   # el reporte sigue guardado; correo_enviado_en queda en NULL para reenviarlo a mano
    try:
        with obtener_conexion() as conn:
            with conn.cursor() as cur:
                cur.execute("UPDATE reportes SET correo_enviado_en = now() WHERE id = %s", (reporte_id,))
            conn.commit()
    except Exception:
        log.exception("No se pudo marcar el reporte %s como enviado", reporte_id)


# ============================================================ ENDPOINTS: REPORTES

@router.get("/reportes/motivos")
def motivos(usuaria: dict = Depends(usuaria_modo_normal)):
    """Los motivos que se muestran en la ventana de reporte (la app puede usar estos textos)."""
    return {"motivos": [{"clave": k, **v} for k, v in MOTIVOS.items()]}


@router.post("/reportes", status_code=status.HTTP_201_CREATED)
def reportar(datos: ReporteIn, segundo_plano: BackgroundTasks, usuaria: dict = Depends(usuaria_modo_normal)):
    uid = usuaria["id"]
    prioridad = "alta" if MOTIVOS[datos.motivo]["riesgo"] or datos.revision_prioritaria else "normal"
    publicacion_id = reto_id = reportada_id = None
    titulo = reportada_seudonimo = ""
    bloqueada = False
    reto_oculto = False

    with obtener_conexion() as conn:
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT count(*) AS n FROM reportes WHERE reportante_id = %s AND creado_en > now() - interval '1 day'",
                            (uid,))
                if cur.fetchone()["n"] >= MAX_REPORTES_DIA:
                    raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS,
                                        "Enviaste muchos reportes hoy. Si es urgente, usa la ayuda de la app")

                if datos.tipo == "reto":
                    cur.execute("""SELECT r.id, r.titulo, r.publicado_por,
                                          COALESCE(u.seudonimo, e.nombre_publico) AS publica
                                     FROM retos r
                                     LEFT JOIN usuarias u ON u.id = r.publicado_por
                                     LEFT JOIN externos e ON e.id = r.contratista_id
                                    WHERE r.id::text = %s""", (datos.objetivo_id,))
                    r = cur.fetchone()
                    if r is None:
                        raise HTTPException(status.HTTP_404_NOT_FOUND, "No encontramos eso para reportarlo")
                    if r["publicado_por"] is not None and str(r["publicado_por"]) == str(uid):
                        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "No puedes reportar tu propio reto")
                    reto_id, reportada_id = r["id"], r["publicado_por"]   # None en los retos de demo
                    titulo, reportada_seudonimo = r["titulo"], r["publica"]
                else:
                    cur.execute("""SELECT p.id, p.titulo, p.usuaria_id, u.seudonimo FROM publicaciones p
                                     JOIN usuarias u ON u.id = p.usuaria_id
                                    WHERE p.id::text = %s AND p.estado = 'activo'""", (datos.objetivo_id,))
                    p = cur.fetchone()
                    if p is None:
                        raise HTTPException(status.HTTP_404_NOT_FOUND, "No encontramos eso para reportarlo")
                    if str(p["usuaria_id"]) == str(uid):
                        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "No puedes reportarte a ti misma")
                    publicacion_id, reportada_id = p["id"], p["usuaria_id"]
                    titulo, reportada_seudonimo = p["titulo"], p["seudonimo"]

                cur.execute(
                    """INSERT INTO reportes (reportante_id, tipo, publicacion_id, reto_id, usuaria_reportada_id,
                                             objetivo_titulo, motivo, detalle, prioridad, bloqueo_solicitado)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
                    (uid, datos.tipo, publicacion_id, reto_id, reportada_id, titulo[:200], datos.motivo,
                     datos.detalle, prioridad, datos.bloquear and reportada_id is not None),
                )
                reporte_id = cur.fetchone()["id"]

                # Bloquear en la misma transacción: o queda todo o no queda nada
                if datos.bloquear and reportada_id is not None:
                    cur.execute("""INSERT INTO bloqueos (usuaria_id, bloqueada_id) VALUES (%s, %s)
                                   ON CONFLICT DO NOTHING""", (uid, reportada_id))
                    bloqueada = True

                # Un reto abierto con varios reportes (de personas distintas, cuenta solo los posteriores a su última
                # revisión) vuelve a 'en_revision': deja de verse hasta que el equipo lo revise.
                if datos.tipo == "reto":
                    cur.execute("""UPDATE retos SET estado = 'en_revision'
                                    WHERE id = %s AND estado = 'abierto'
                                      AND (SELECT count(*) FROM reportes x WHERE x.reto_id = retos.id AND x.tipo = 'reto'
                                              AND x.creado_en > COALESCE(retos.revisado_en, '-infinity')) >= %s
                                RETURNING id""", (reto_id, REPORTES_PARA_OCULTAR))
                    reto_oculto = cur.fetchone() is not None

                cur.execute("SELECT seudonimo FROM usuarias WHERE id = %s", (uid,))
                reportante = cur.fetchone()["seudonimo"]
            conn.commit()
        except pg_errors.UniqueViolation:
            conn.rollback()
            raise HTTPException(status.HTTP_409_CONFLICT, "Ya enviaste un reporte sobre esto. Lo estamos revisando")
        except Exception:
            conn.rollback()
            raise

    objetivo = {"publicacion": "Publicación", "reto": "Reto", "usuaria": "Usuaria"}[datos.tipo]
    asunto = (f"[Crisálida] Reporte #{reporte_id}" + (" · PRIORIDAD ALTA" if prioridad == "alta" else "")
              + (" · RETO OCULTO" if reto_oculto else ""))
    texto = (
        f"Nuevo reporte #{reporte_id} (prioridad {prioridad})\n\n"
        f"Qué se reporta: {objetivo}\n"
        f"Título/nombre: {titulo}\n"
        f"Publicado por: {reportada_seudonimo}\n"
        f"Motivo: {MOTIVOS[datos.motivo]['titulo']}\n"
        f"Detalle: {datos.detalle or '(sin detalle)'}\n"
        f"Reportó: {reportante}\n"
        f"Pidió bloquear: {'sí' if bloqueada else 'no'}\n"
        f"Pidió revisión prioritaria: {'sí' if datos.revision_prioritaria else 'no'}\n"
        + ("El reto juntó varios reportes y se OCULTÓ solo hasta que lo revisen (GET /admin/retos/pendientes).\n"
           if reto_oculto else "")
        + "\n"
        f"Para revisarlo: SELECT * FROM reportes WHERE id = {reporte_id};"
    )
    segundo_plano.add_task(_enviar_al_equipo, reporte_id, asunto, texto)
    if reto_oculto and reportada_id is not None:
        segundo_plano.add_task(
            avisar_publicadora, reportada_id, "Crisálida: tu reto está en revisión",
            f"Tu reto «{titulo}» está en revisión y dejó de mostrarse temporalmente. Nuestro equipo lo revisará "
            "y te avisaremos el resultado.")

    return {"id": reporte_id, "bloqueada": bloqueada,
            "mensaje": "Gracias. Recibimos tu reporte y lo revisaremos con cuidado."}


# ============================================================ ENDPOINTS: BLOQUEOS

@router.get("/bloqueos")
def mis_bloqueos(usuaria: dict = Depends(usuaria_modo_normal)):
    """Las usuarias que bloqueé (para la lista en Privacidad). 'id' es el del bloqueo, sirve para desbloquear."""
    with obtener_conexion() as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT b.id, u.seudonimo, u.avatar, b.creado_en FROM bloqueos b
                             JOIN usuarias u ON u.id = b.bloqueada_id
                            WHERE b.usuaria_id = %s ORDER BY b.creado_en DESC""", (usuaria["id"],))
            return {"bloqueos": [dict(r) for r in cur.fetchall()]}


@router.post("/bloqueos", status_code=status.HTTP_201_CREATED)
def bloquear(datos: BloqueoIn, usuaria: dict = Depends(usuaria_modo_normal)):
    """Bloquea a quien publicó una publicación o un reto. Si ya estaba bloqueada responde lo mismo (no falla)."""
    uid = usuaria["id"]
    with obtener_conexion() as conn:
        try:
            with conn.cursor() as cur:
                if datos.publicacion_id is not None:
                    cur.execute("SELECT usuaria_id AS autora FROM publicaciones WHERE id::text = %s", (datos.publicacion_id,))
                else:
                    cur.execute("SELECT publicado_por AS autora FROM retos WHERE id::text = %s", (datos.reto_id,))
                p = cur.fetchone()
                if p is None:
                    raise HTTPException(status.HTTP_404_NOT_FOUND, "No encontramos a esa persona")
                if p["autora"] is None:
                    raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Esta publicación no se puede bloquear")
                if str(p["autora"]) == str(uid):
                    raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "No puedes bloquearte a ti misma")
                cur.execute("""INSERT INTO bloqueos (usuaria_id, bloqueada_id) VALUES (%s, %s)
                               ON CONFLICT DO NOTHING""", (uid, p["autora"]))
                cur.execute("""SELECT b.id, u.seudonimo, u.avatar FROM bloqueos b JOIN usuarias u ON u.id = b.bloqueada_id
                                WHERE b.usuaria_id = %s AND b.bloqueada_id = %s""", (uid, p["autora"]))
                fila = cur.fetchone()
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    return {"id": fila["id"], "seudonimo": fila["seudonimo"], "avatar": fila["avatar"], "bloqueada": True}


@router.delete("/bloqueos/{bloqueo_id}")
def desbloquear(bloqueo_id: int, usuaria: dict = Depends(usuaria_modo_normal)):
    with obtener_conexion() as conn:
        try:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM bloqueos WHERE id = %s AND usuaria_id = %s RETURNING id",
                            (bloqueo_id, usuaria["id"]))
                ok = cur.fetchone()
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    if ok is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No encontramos ese bloqueo")
    return {"bloqueada": False}