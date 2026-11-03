"""Bienestar emocional.

- Se puede registrar a CUALQUIER hora y todas las veces que se quiera: cada registro es una fila nueva.
- Las FLORES se dan una sola vez al día por bloque (emoción, monitoreo, reflexión, bitácora).
- Privacidad: las reflexiones y la bitácora se guardan CIFRADAS (AES-256-GCM) en el servidor.
  La clave vive en el servidor (no en el teléfono), así que NO es cifrado de extremo a extremo.
"""
import json
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator

from db import obtener_conexion
from dependencias import usuaria_modo_normal
from seguridad import cifrar_texto, descifrar_texto

router = APIRouter(prefix="/bienestar", tags=["Bienestar"])

SUBTIPOS = ("emocion", "monitoreo", "reflexion", "bitacora")


class EmocionIn(BaseModel):
    emocion: str = Field(min_length=2, max_length=30)


class MonitoreoIn(BaseModel):
    tension: int = Field(ge=1, le=5)
    claridad: int = Field(ge=1, le=5)
    energia: int = Field(ge=1, le=5)


class ReflexionIn(BaseModel):
    respuestas: list[str] = Field(max_length=4)   # una por pregunta, en orden; vacías permitidas

    @field_validator("respuestas")
    @classmethod
    def _resp(cls, v: list[str]) -> list[str]:
        v = [r.strip()[:600] for r in v]
        if not any(v):
            raise ValueError("Responde al menos una pregunta")
        return v


class BitacoraIn(BaseModel):
    texto: str = Field(min_length=1, max_length=4000)

    @field_validator("texto")
    @classmethod
    def _texto(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Escribe algo en tu bitácora")
        return v


def _guardar(uid, subtipo: str, columnas: dict) -> dict:
    """Inserta un registro NUEVO y, si es el primero del día en ese bloque, da las flores."""
    nombres = list(columnas)
    with obtener_conexion() as conn:
        try:
            with conn.cursor() as cur:
                cur.execute(
                    f"""INSERT INTO bienestar_entradas (usuaria_id, subtipo, {", ".join(nombres)})
                        VALUES (%s, %s, {", ".join(["%s"] * len(nombres))}) RETURNING id""",
                    (uid, subtipo, *columnas.values()),
                )
                nueva = cur.fetchone()
                # referencia_id NULL a propósito: el tope de "una vez al día por bloque" lo da el índice único
                cur.execute(
                    """INSERT INTO eventos_progreso (usuaria_id, tipo, subtipo, flores, cuenta_para_nivel)
                       SELECT %s, 'bienestar', %s, r.flores, FALSE FROM reglas_recompensa r WHERE r.clave = %s
                       ON CONFLICT DO NOTHING RETURNING flores""",
                    (uid, subtipo, f"bienestar_{subtipo}"),
                )
                ev = cur.fetchone()
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    return {"id": str(nueva["id"]), "flores_ganadas": ev["flores"] if ev else 0, "ya_registrado_hoy": ev is None}


@router.post("/emocion")
def guardar_emocion(datos: EmocionIn, usuaria: dict = Depends(usuaria_modo_normal)):
    return _guardar(usuaria["id"], "emocion", {"emocion": datos.emocion.strip()})


@router.post("/monitoreo")
def guardar_monitoreo(datos: MonitoreoIn, usuaria: dict = Depends(usuaria_modo_normal)):
    return _guardar(usuaria["id"], "monitoreo",
                    {"tension": datos.tension, "claridad": datos.claridad, "energia": datos.energia})


@router.post("/reflexion")
def guardar_reflexion(datos: ReflexionIn, usuaria: dict = Depends(usuaria_modo_normal)):
    return _guardar(usuaria["id"], "reflexion",
                    {"texto_cifrado": cifrar_texto(json.dumps(datos.respuestas, ensure_ascii=False))})


@router.post("/bitacora")
def guardar_bitacora(datos: BitacoraIn, usuaria: dict = Depends(usuaria_modo_normal)):
    return _guardar(usuaria["id"], "bitacora", {"texto_cifrado": cifrar_texto(datos.texto)})


@router.get("/hoy")
def hoy(usuaria: dict = Depends(usuaria_modo_normal)):
    """Qué bloques ya dieron flores hoy (para mostrar «🌸 flores ganadas hoy») y cuántos registros lleva."""
    with obtener_conexion() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT subtipo, count(*) AS n FROM bienestar_entradas
                    WHERE usuaria_id = %s AND dia = (now() AT TIME ZONE 'America/Mexico_City')::date
                    GROUP BY subtipo""",
                (usuaria["id"],),
            )
            registros = {r["subtipo"]: int(r["n"]) for r in cur.fetchall()}
            cur.execute(
                """SELECT subtipo FROM eventos_progreso
                    WHERE usuaria_id = %s AND tipo = 'bienestar'
                      AND dia = (now() AT TIME ZONE 'America/Mexico_City')::date""",
                (usuaria["id"],),
            )
            con_flores = {x["subtipo"] for x in cur.fetchall()}
    return {
        "flores_cobradas": {s: (s in con_flores) for s in SUBTIPOS},
        "registros_hoy": {s: registros.get(s, 0) for s in SUBTIPOS},
    }


def _abrir(valor: str | None):
    if not valor:
        return None
    try:
        return descifrar_texto(valor)
    except Exception:
        return None


@router.get("/entradas")
def listar_entradas(subtipo: Literal["emocion", "monitoreo", "reflexion", "bitacora"] = Query("emocion"),
                    limite: int = Query(50, ge=1, le=100),
                    desde: int = Query(0, ge=0),
                    usuaria: dict = Depends(usuaria_modo_normal)):
    """Historial de UN bloque, lo más reciente primero (solo la propia usuaria lo ve)."""
    with obtener_conexion() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT id, subtipo, emocion, tension, claridad, energia, texto_cifrado, dia,
                          to_char(creado_en AT TIME ZONE 'America/Mexico_City', 'HH24:MI') AS hora
                     FROM bienestar_entradas
                    WHERE usuaria_id = %s AND subtipo = %s
                    ORDER BY creado_en DESC, id LIMIT %s OFFSET %s""",
                (usuaria["id"], subtipo, limite, desde),
            )
            filas = cur.fetchall()
    salida = []
    for f in filas:
        texto = _abrir(f["texto_cifrado"])
        e = {"id": str(f["id"]), "subtipo": f["subtipo"], "dia": str(f["dia"]), "hora": f["hora"],
             "emocion": f["emocion"], "tension": f["tension"], "claridad": f["claridad"], "energia": f["energia"],
             "texto": None, "respuestas": None}
        if f["subtipo"] == "reflexion" and texto:
            try:
                e["respuestas"] = json.loads(texto)
            except ValueError:
                e["respuestas"] = []
        elif f["subtipo"] == "bitacora":
            e["texto"] = texto or ""
        salida.append(e)
    return {"entradas": salida}


@router.delete("/entradas/{entrada_id}")
def borrar_entrada(entrada_id: str, usuaria: dict = Depends(usuaria_modo_normal)):
    """Borra un registro. Las flores que ya se ganaron se conservan."""
    with obtener_conexion() as conn:
        try:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM bienestar_entradas WHERE id::text = %s AND usuaria_id = %s RETURNING id",
                            (entrada_id, usuaria["id"]))
                ok = cur.fetchone()
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    if ok is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No encontramos ese registro")
    return {"borrada": True}
