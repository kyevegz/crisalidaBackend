"""Catálogo público de productos y servicios (solo publicaciones 'activo')."""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status

from db import obtener_conexion
from dependencias import usuaria_modo_normal

router = APIRouter(tags=["Marketplace"])

# Los mismos campos se usan en el catálogo y en el detalle
_SELECT = """
SELECT p.id, p.tipo, p.titulo, p.descripcion, p.precio, p.nota_precio,
       p.opcion_entrega, p.modalidad_servicio, p.esquema_cobro,
       p.tiempo_elaboracion_horas, p.zona_publica, p.creada_en,
       c.id AS categoria_id, c.nombre AS categoria,
       u.seudonimo AS vendedora, u.avatar AS vendedora_avatar,
       (p.usuaria_id = %s) AS es_mia,
       COALESCE(v.vendidos, 0) AS vendidos, v.calificacion,
       (SELECT json_agg(i.id ORDER BY i.orden) FROM publicacion_imagenes i WHERE i.publicacion_id = p.id) AS imagenes
  FROM publicaciones p
  JOIN categorias c ON c.id = p.categoria_id
  JOIN usuarias   u ON u.id = p.usuaria_id
  LEFT JOIN LATERAL (
        SELECT count(*) AS vendidos, round(avg(pe.calificacion)::numeric, 1) AS calificacion
          FROM pedidos pe WHERE pe.publicacion_id = p.id AND pe.estado = 'completado'
  ) v ON TRUE
"""


def formatear(r: dict) -> dict:
    d = dict(r)
    d["precio"] = float(d["precio"])
    d["calificacion"] = float(d["calificacion"]) if d["calificacion"] is not None else None
    d["vendidos"] = int(d["vendidos"])
    d["por_encargo"] = d["opcion_entrega"] == 3
    d["imagenes"] = [f"/imagenes/{i}" for i in (d["imagenes"] or [])]
    return d


@router.get("/categorias")
def categorias(ambito: Literal["producto", "servicio", "reto"] | None = Query(None),
               usuaria: dict = Depends(usuaria_modo_normal)):
    """Filtros de Marketplace (producto/servicio) y de Retos (reto)."""
    with obtener_conexion() as conn:
        with conn.cursor() as cur:
            if ambito:
                cur.execute("SELECT id, ambito, nombre FROM categorias WHERE ambito = %s ORDER BY id", (ambito,))
            else:
                cur.execute("SELECT id, ambito, nombre FROM categorias ORDER BY id")
            return {"categorias": [dict(r) for r in cur.fetchall()]}


@router.get("/marketplace")
def catalogo(tipo: Literal["producto", "servicio"] | None = Query(None),
             categoria_id: int | None = Query(None),
             q: str | None = Query(None, max_length=60),
             limite: int = Query(30, ge=1, le=50),
             desde: int = Query(0, ge=0),
             usuaria: dict = Depends(usuaria_modo_normal)):
    filtros, params = ["p.estado = 'activo'"], [usuaria["id"]]
    if tipo:
        filtros.append("p.tipo = %s")
        params.append(tipo)
    if categoria_id:
        filtros.append("p.categoria_id = %s")
        params.append(categoria_id)
    if q and q.strip():
        buscar = "%" + q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        filtros.append("(p.titulo ILIKE %s OR p.descripcion ILIKE %s)")
        params += [buscar, buscar]
    sql = _SELECT + " WHERE " + " AND ".join(filtros) + " ORDER BY p.creada_en DESC, p.id LIMIT %s OFFSET %s"
    params += [limite, desde]
    with obtener_conexion() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, tuple(params))
            return {"publicaciones": [formatear(r) for r in cur.fetchall()]}


@router.get("/marketplace/{publicacion_id}")
def detalle(publicacion_id: str, usuaria: dict = Depends(usuaria_modo_normal)):
    with obtener_conexion() as conn:
        with conn.cursor() as cur:
            cur.execute(_SELECT + " WHERE p.id::text = %s AND p.estado = 'activo'", (usuaria["id"], publicacion_id))
            r = cur.fetchone()
    if r is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Publicación no encontrada")
    return formatear(r)
