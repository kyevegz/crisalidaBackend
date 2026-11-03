"""Microrretos: tablero, aceptar, entregar y abandonar.
Validar un reto lo hace el contratista (todavía sin login): en la demo se simula con SQL o con /demo."""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from psycopg2 import errors as pg_errors

from db import obtener_conexion
from dependencias import usuaria_modo_normal

router = APIRouter(prefix="/retos", tags=["Microrretos"])

MAX_RETOS_ACTIVOS = 3   # para que nadie "acapare" el tablero

_CAMPOS_RETO = """
       r.id AS reto_id, r.titulo, r.descripcion, r.compensacion, r.duracion_min, r.dificultad,
       r.habilidad_requerida, r.etiqueta, r.fecha_limite, r.estado AS reto_estado,
       c.id AS categoria_id, c.nombre AS categoria, e.nombre_publico AS contratista,
       EXISTS (SELECT 1 FROM reto_imagenes ri WHERE ri.reto_id = r.id) AS tiene_imagen
"""


def _reto(r: dict) -> dict:
    d = dict(r)
    d["compensacion"] = float(d["compensacion"])
    d["imagen_ruta"] = f"/retos/{d['reto_id']}/imagen" if d.pop("tiene_imagen", False) else None
    return d


@router.get("")
def tablero(categoria_id: int | None = Query(None),
            dificultad: Literal["facil", "media", "dificil"] | None = Query(None),
            q: str | None = Query(None, max_length=60),
            limite: int = Query(30, ge=1, le=50),
            desde: int = Query(0, ge=0),
            usuaria: dict = Depends(usuaria_modo_normal)):
    filtros, params = ["r.estado = 'abierto'", "r.fecha_limite > now()"], []
    if categoria_id:
        filtros.append("r.categoria_id = %s")
        params.append(categoria_id)
    if dificultad:
        filtros.append("r.dificultad = %s")
        params.append(dificultad)
    if q and q.strip():
        buscar = "%" + q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        filtros.append("(r.titulo ILIKE %s OR r.descripcion ILIKE %s)")
        params += [buscar, buscar]
    sql = (f"SELECT {_CAMPOS_RETO} FROM retos r JOIN categorias c ON c.id = r.categoria_id "
           "JOIN externos e ON e.id = r.contratista_id WHERE " + " AND ".join(filtros) +
           " ORDER BY r.fecha_limite, r.id LIMIT %s OFFSET %s")
    params += [limite, desde]
    with obtener_conexion() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, tuple(params))
            return {"retos": [_reto(r) for r in cur.fetchall()]}


@router.get("/mis")
def mis_retos(usuaria: dict = Depends(usuaria_modo_normal)):
    with obtener_conexion() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""SELECT a.id AS aceptacion_id, a.estado, a.aceptado_en, a.entregado_en, a.validado_en, {_CAMPOS_RETO}
                      FROM reto_aceptaciones a
                      JOIN retos r ON r.id = a.reto_id
                      JOIN categorias c ON c.id = r.categoria_id
                      JOIN externos e ON e.id = r.contratista_id
                     WHERE a.usuaria_id = %s
                     ORDER BY a.aceptado_en DESC""",
                (usuaria["id"],),
            )
            return {"retos": [_reto(r) for r in cur.fetchall()]}


@router.get("/{reto_id}/imagen")
def imagen_reto(reto_id: str):
    """Pública (como las fotos de productos): el id es un UUID y la app la carga con un cargador normal."""
    with obtener_conexion() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT mime, datos FROM reto_imagenes WHERE reto_id::text = %s", (reto_id,))
            r = cur.fetchone()
    if r is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Este reto no tiene imagen")
    return Response(content=bytes(r["datos"]), media_type=r["mime"],
                    headers={"Cache-Control": "public, max-age=86400"})


@router.get("/{reto_id}")
def detalle(reto_id: str, usuaria: dict = Depends(usuaria_modo_normal)):
    """Detalle de un reto, con el estado de la usuaria en él (si ya lo tomó)."""
    with obtener_conexion() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""SELECT {_CAMPOS_RETO},
                           (SELECT a.id FROM reto_aceptaciones a WHERE a.reto_id = r.id AND a.usuaria_id = %s
                             ORDER BY a.aceptado_en DESC LIMIT 1) AS aceptacion_id,
                           (SELECT a.estado FROM reto_aceptaciones a WHERE a.reto_id = r.id AND a.usuaria_id = %s
                             ORDER BY a.aceptado_en DESC LIMIT 1) AS mi_estado
                      FROM retos r JOIN categorias c ON c.id = r.categoria_id
                      JOIN externos e ON e.id = r.contratista_id
                     WHERE r.id::text = %s""",
                (usuaria["id"], usuaria["id"], reto_id),
            )
            fila = cur.fetchone()
    if fila is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No encontramos ese reto")
    d = _reto(fila)
    d["aceptacion_id"] = str(d["aceptacion_id"]) if d["aceptacion_id"] else None
    return d


@router.post("/{reto_id}/aceptar", status_code=status.HTTP_201_CREATED)
def aceptar(reto_id: str, usuaria: dict = Depends(usuaria_modo_normal)):
    uid = usuaria["id"]
    with obtener_conexion() as conn:
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT count(*) AS n FROM reto_aceptaciones WHERE usuaria_id = %s AND estado IN ('aceptado', 'entregado')",
                    (uid,),
                )
                if cur.fetchone()["n"] >= MAX_RETOS_ACTIVOS:
                    raise HTTPException(status.HTTP_409_CONFLICT,
                                        f"Ya tienes {MAX_RETOS_ACTIVOS} retos en curso. Termina uno antes de tomar otro")
                cur.execute(
                    "SELECT id FROM retos WHERE id::text = %s AND estado = 'abierto' AND fecha_limite > now() FOR UPDATE",
                    (reto_id,),
                )
                if cur.fetchone() is None:
                    raise HTTPException(status.HTTP_409_CONFLICT, "Este reto ya no está disponible")
                cur.execute(
                    "INSERT INTO reto_aceptaciones (reto_id, usuaria_id) VALUES (%s, %s) RETURNING id, aceptado_en",
                    (reto_id, uid),
                )
                acept = cur.fetchone()
                cur.execute("UPDATE retos SET estado = 'asignado' WHERE id::text = %s", (reto_id,))
            conn.commit()
        except pg_errors.UniqueViolation:
            conn.rollback()
            raise HTTPException(status.HTTP_409_CONFLICT, "Este reto ya fue tomado por otra persona")
        except Exception:
            conn.rollback()
            raise
    return {"aceptacion_id": str(acept["id"]), "estado": "aceptado"}


@router.post("/aceptaciones/{aceptacion_id}/entregar")
def entregar(aceptacion_id: str, usuaria: dict = Depends(usuaria_modo_normal)):
    with obtener_conexion() as conn:
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """UPDATE reto_aceptaciones SET estado = 'entregado', entregado_en = now()
                        WHERE id::text = %s AND usuaria_id = %s AND estado = 'aceptado' RETURNING id""",
                    (aceptacion_id, usuaria["id"]),
                )
                ok = cur.fetchone()
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    if ok is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No encontramos ese reto en curso")
    return {"estado": "entregado"}


@router.post("/aceptaciones/{aceptacion_id}/abandonar")
def abandonar(aceptacion_id: str, usuaria: dict = Depends(usuaria_modo_normal)):
    """Soltar un reto sin entregarlo: vuelve al tablero para otra persona."""
    with obtener_conexion() as conn:
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """UPDATE reto_aceptaciones SET estado = 'abandonado'
                        WHERE id::text = %s AND usuaria_id = %s AND estado = 'aceptado' RETURNING reto_id""",
                    (aceptacion_id, usuaria["id"]),
                )
                fila = cur.fetchone()
                if fila is not None:
                    cur.execute("UPDATE retos SET estado = 'abierto' WHERE id = %s AND estado = 'asignado'", (fila["reto_id"],))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    if fila is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No encontramos ese reto en curso")
    return {"estado": "abandonado"}
