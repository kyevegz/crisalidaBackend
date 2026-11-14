"""Frases de apoyo de la pantalla "Respira con Lilu".

Las frases viven en la tabla `frases_apoyo` (migración 006). Este endpoint devuelve unas
pocas al azar, solo activas, según el estado de Lilu: 'normal' o 'reposo'.
"""
from fastapi import APIRouter, Depends

from db import obtener_conexion
from dependencias import usuaria_vendedora
from progreso import REPOSO_DIAS

router = APIRouter(tags=["Frases"])

CANTIDAD = 5  # cuántas frases devuelve cada vez (variadas, no toda la tabla)


@router.get("/frases-apoyo")
def frases_de_apoyo(usuaria: dict = Depends(usuaria_vendedora)):
    """Estado de Lilu: 'reposo' si en REPOSO_DIAS días no hubo ninguna actividad
    (bienestar, reto, publicación o venta); si no, 'normal'. Iniciar sesión no cuenta."""
    with obtener_conexion() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT ultima_actividad < now() - make_interval(days => %s) AS reposo
                  FROM mascotas
                 WHERE usuaria_id = %s
                """,
                (REPOSO_DIAS, usuaria["id"]),
            )
            fila = cur.fetchone()
            estado = "reposo" if fila and fila["reposo"] else "normal"

            cur.execute(
                """
                SELECT id, texto
                  FROM frases_apoyo
                 WHERE estado = %s AND activa
                 ORDER BY random()
                 LIMIT %s
                """,
                (estado, CANTIDAD),
            )
            frases = [dict(r) for r in cur.fetchall()]
    return {"estado": estado, "frases": frases}