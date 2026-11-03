"""Atajos SOLO PARA DEMO. Quedan apagados salvo que pongas MODO_DEMO=true en el .env.

Los compradores y contratistas aún no tienen login, así que estos endpoints hacen lo que ellos harían,
pero solo sobre lo que es de la usuaria que los llama. Apágalos (quita MODO_DEMO) para producción.
"""
import os

from fastapi import APIRouter, Depends, HTTPException, status

from db import obtener_conexion
from dependencias import usuaria_modo_normal

MODO_DEMO = os.getenv("MODO_DEMO", "false").lower() == "true"
router = APIRouter(prefix="/demo", tags=["Solo demo"])


def _ejecutar(sql: str, params: tuple, vacio: str):
    with obtener_conexion() as conn:
        try:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                fila = cur.fetchone()
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    if fila is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, vacio)
    return {"ok": True}


@router.post("/aprobar-publicacion/{publicacion_id}")
def aprobar_publicacion(publicacion_id: str, usuaria: dict = Depends(usuaria_modo_normal)):
    return _ejecutar("UPDATE publicaciones SET estado = 'activo' WHERE id::text = %s AND usuaria_id = %s "
                     "AND estado = 'en_revision' RETURNING id",
                     (publicacion_id, usuaria["id"]), "Publicación no encontrada o ya aprobada")


@router.post("/completar-venta/{publicacion_id}")
def completar_venta(publicacion_id: str, usuaria: dict = Depends(usuaria_modo_normal)):
    """Simula que una compradora compró y recibió tu publicación (+flores y +1 actividad)."""
    with obtener_conexion() as conn:
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT p.id, p.precio FROM publicaciones p WHERE p.id::text = %s AND p.usuaria_id = %s "
                            "AND p.estado = 'activo'", (publicacion_id, usuaria["id"]))
                p = cur.fetchone()
                if p is None:
                    raise HTTPException(status.HTTP_404_NOT_FOUND, "Publicación activa no encontrada")
                cur.execute("SELECT id FROM externos WHERE tipo IN ('comprador', 'ambos') ORDER BY creado_en LIMIT 1")
                comprador = cur.fetchone()
                if comprador is None:
                    raise HTTPException(status.HTTP_409_CONFLICT, "No hay compradores de prueba (corre 03_datos_demo.sql)")
                cur.execute("INSERT INTO pedidos (publicacion_id, comprador_id, monto, calificacion, comentario) "
                            "VALUES (%s, %s, %s, 5, 'Compra de prueba') RETURNING id",
                            (p["id"], comprador["id"], p["precio"]))
                pedido = cur.fetchone()
                cur.execute("UPDATE pedidos SET estado = 'completado' WHERE id = %s", (pedido["id"],))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    return {"ok": True}


@router.post("/validar-reto/{aceptacion_id}")
def validar_reto(aceptacion_id: str, usuaria: dict = Depends(usuaria_modo_normal)):
    """Simula que el contratista validó tu reto ya entregado (+flores y +1 actividad)."""
    return _ejecutar("UPDATE reto_aceptaciones SET estado = 'validado' WHERE id::text = %s AND usuaria_id = %s "
                     "AND estado = 'entregado' RETURNING id",
                     (aceptacion_id, usuaria["id"]), "Primero entrega el reto")
