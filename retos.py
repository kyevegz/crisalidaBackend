"""Microrretos: tablero, aceptar, entregar y abandonar.
Validar un reto lo hace el contratista (todavía sin login): en la demo se simula con SQL o con /demo."""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from psycopg2 import errors as pg_errors

from db import obtener_conexion
from dependencias import usuaria_modo_normal, usuaria_vendedora
from idempotencia import clave_idempotencia, guardar_respuesta, reservar

router = APIRouter(prefix="/retos", tags=["Microrretos"])

MAX_RETOS_ACTIVOS = 3   # para que nadie "acapare" el tablero

_CAMPOS_RETO = """
       r.id AS reto_id, r.titulo, r.descripcion, r.compensacion, r.duracion_min, r.dificultad,
       r.habilidad_requerida, r.etiqueta, r.fecha_limite, r.estado AS reto_estado,
       c.id AS categoria_id, c.nombre AS categoria, COALESCE(e.nombre_publico, pu.seudonimo) AS contratista,
       EXISTS (SELECT 1 FROM reto_imagenes ri WHERE ri.reto_id = r.id) AS tiene_imagen,
       r.publicado_por AS autora_id
"""


# Lo bloqueado deja de aparecer, en los dos sentidos (igual que en el marketplace). Los retos sin cuenta detrás
# (publicado_por vacío, p. ej. los de demo) nunca se ocultan.
_SIN_BLOQUEOS = """NOT EXISTS (SELECT 1 FROM bloqueos b
                  WHERE (b.usuaria_id = %s AND b.bloqueada_id = r.publicado_por)
                     OR (b.usuaria_id = r.publicado_por AND b.bloqueada_id = %s))"""


# Los retos de una cuenta suspendida (en reposo) tampoco se muestran
_PUBLICADORA_ACTIVA = """NOT EXISTS (SELECT 1 FROM usuarias s WHERE s.id = r.publicado_por AND s.estado = 'suspendida')"""


def _reto(r: dict, uid=None) -> dict:
    d = dict(r)
    # para la app: «Reportar» y «Bloquear» no aparecen en tu propio reto, y los retos de demo (sin cuenta) no se bloquean
    autora = d.pop("autora_id", None)
    d["es_mio"] = autora is not None and uid is not None and str(autora) == str(uid)
    d["bloqueable"] = autora is not None and not d["es_mio"]
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
    filtros = ["r.estado = 'abierto'", "r.fecha_limite > now()", _SIN_BLOQUEOS, _PUBLICADORA_ACTIVA]
    params = [usuaria["id"], usuaria["id"]]
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
           "LEFT JOIN externos e ON e.id = r.contratista_id "
           "LEFT JOIN usuarias pu ON pu.id = r.publicado_por WHERE " + " AND ".join(filtros) +
           " ORDER BY r.fecha_limite, r.id LIMIT %s OFFSET %s")
    params += [limite, desde]
    with obtener_conexion() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, tuple(params))
            return {"retos": [_reto(r, usuaria["id"]) for r in cur.fetchall()]}


@router.get("/mis")
def mis_retos(usuaria: dict = Depends(usuaria_vendedora)):
    with obtener_conexion() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""SELECT a.id AS aceptacion_id, a.estado, a.aceptado_en, a.entregado_en, a.validado_en,
                           a.motivo_rechazo, a.rechazado_en, a.rechazos, {_CAMPOS_RETO}
                      FROM reto_aceptaciones a
                      JOIN retos r ON r.id = a.reto_id
                      JOIN categorias c ON c.id = r.categoria_id
                      LEFT JOIN externos e ON e.id = r.contratista_id
           LEFT JOIN usuarias pu ON pu.id = r.publicado_por
                     WHERE a.usuaria_id = %s
                     ORDER BY a.aceptado_en DESC""",
                (usuaria["id"],),
            )
            return {"retos": [_reto(r, usuaria["id"]) for r in cur.fetchall()]}


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
                           CASE WHEN r.publicado_por = %s THEN r.motivo_rechazo END AS motivo_rechazo,
                           (SELECT a.id FROM reto_aceptaciones a WHERE a.reto_id = r.id AND a.usuaria_id = %s
                             ORDER BY a.aceptado_en DESC LIMIT 1) AS aceptacion_id,
                           (SELECT a.estado FROM reto_aceptaciones a WHERE a.reto_id = r.id AND a.usuaria_id = %s
                             ORDER BY a.aceptado_en DESC LIMIT 1) AS mi_estado
                      FROM retos r JOIN categorias c ON c.id = r.categoria_id
                      LEFT JOIN externos e ON e.id = r.contratista_id
           LEFT JOIN usuarias pu ON pu.id = r.publicado_por
                     WHERE r.id::text = %s
                       AND (r.estado NOT IN ('en_revision', 'rechazado') OR r.publicado_por = %s)
                       AND (EXISTS (SELECT 1 FROM reto_aceptaciones a2 WHERE a2.reto_id = r.id AND a2.usuaria_id = %s)
                            OR (""" + _SIN_BLOQUEOS + " AND " + _PUBLICADORA_ACTIVA + """))""",
                (usuaria["id"], usuaria["id"], usuaria["id"], reto_id, usuaria["id"], usuaria["id"], usuaria["id"], usuaria["id"]),
            )
            fila = cur.fetchone()
    if fila is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No encontramos ese reto")
    d = _reto(fila, usuaria["id"])
    d["aceptacion_id"] = str(d["aceptacion_id"]) if d["aceptacion_id"] else None
    return d


@router.post("/{reto_id}/aceptar", status_code=status.HTTP_201_CREATED)
def aceptar(reto_id: str, usuaria: dict = Depends(usuaria_vendedora)):
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
                    "SELECT id, publicado_por FROM retos WHERE id::text = %s AND estado = 'abierto' AND fecha_limite > now() FOR UPDATE",
                    (reto_id,),
                )
                reto = cur.fetchone()
                if reto is None:
                    raise HTTPException(status.HTTP_409_CONFLICT, "Este reto ya no está disponible")
                if reto["publicado_por"] is not None and str(reto["publicado_por"]) == str(uid):
                    raise HTTPException(status.HTTP_403_FORBIDDEN, "No puedes aceptar un reto que publicaste tú")
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
def entregar(aceptacion_id: str, response: Response, usuaria: dict = Depends(usuaria_vendedora),
             clave: str | None = Depends(clave_idempotencia)):
    """Entrega un reto. Con Idempotency-Key, un reenvío devuelve lo mismo en lugar de un 404."""
    with obtener_conexion() as conn:
        try:
            with conn.cursor() as cur:
                if clave:
                    previo = reservar(cur, usuaria["id"], clave, f"entregar:{aceptacion_id}")
                    if previo is not None:
                        conn.commit()
                        response.headers["Idempotent-Replay"] = "true"
                        return previo
                cur.execute(
                    """UPDATE reto_aceptaciones SET estado = 'entregado', entregado_en = now(), motivo_rechazo = NULL
                        WHERE id::text = %s AND usuaria_id = %s AND estado = 'aceptado' RETURNING id""",
                    (aceptacion_id, usuaria["id"]),
                )
                ok = cur.fetchone()
                if ok is not None and clave:
                    guardar_respuesta(cur, usuaria["id"], clave, {"estado": "entregado"})
            # si no se encontró, rollback: la clave NO se queda reservada y el reintento puede volver a intentar
            if ok is None:
                conn.rollback()
            else:
                conn.commit()
        except Exception:
            conn.rollback()
            raise
    if ok is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No encontramos ese reto en curso")
    return {"estado": "entregado"}


@router.post("/aceptaciones/{aceptacion_id}/abandonar")
def abandonar(aceptacion_id: str, usuaria: dict = Depends(usuaria_vendedora)):
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