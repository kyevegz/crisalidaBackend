"""Progreso: nivel (por actividades), etapa de Lilu (por flores), estadísticas y avatar.

- El NIVEL (Semilla … Mujer Extraordinaria) depende de las actividades completadas (ventas + retos).
- La ETAPA de Lilu (Huevo / Larva / Mariposa) depende de las flores acumuladas.
Quien cuenta todo es el trigger de la base; aquí solo se LEE (y se cambia el avatar).
"""
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, field_validator

from db import obtener_conexion
from dependencias import usuaria_modo_normal

router = APIRouter(tags=["Progreso"])


def _porcentaje(actual: int, desde: int, hasta: int | None) -> int:
    if hasta is None or hasta <= desde:
        return 100
    return max(0, min(100, round((actual - desde) * 100 / (hasta - desde))))


def calcular_progreso(cur, uid) -> dict:
    cur.execute(
        """
        SELECT u.seudonimo, u.avatar, m.nombre AS mascota, m.flores, m.nivel,
               m.actividades_completadas AS actividades,
               n.nombre AS nivel_nombre, n.descripcion AS nivel_descripcion,
               n.actividades_requeridas AS actividades_desde
          FROM usuarias u
          JOIN mascotas m ON m.usuaria_id = u.id
          JOIN niveles  n ON n.nivel = m.nivel
         WHERE u.id = %s
        """,
        (uid,),
    )
    base = cur.fetchone()
    if base is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Usuaria no encontrada")

    cur.execute("SELECT nombre, actividades_requeridas FROM niveles WHERE nivel = %s", (base["nivel"] + 1,))
    sig = cur.fetchone()

    cur.execute("SELECT etapa, nombre, flores_requeridas FROM etapas_lilu ORDER BY etapa")
    etapas = cur.fetchall()
    actual = etapas[0]
    for e in etapas:
        if base["flores"] >= e["flores_requeridas"]:
            actual = e
    siguiente = next((e for e in etapas if e["etapa"] == actual["etapa"] + 1), None)

    cur.execute(
        """
        SELECT
          (SELECT count(*) FROM reto_aceptaciones WHERE usuaria_id = %s AND estado = 'validado') AS retos,
          (SELECT count(*) FROM pedidos pe JOIN publicaciones p ON p.id = pe.publicacion_id
            WHERE p.usuaria_id = %s AND pe.estado = 'completado') AS ventas,
          (SELECT round(avg(pe.calificacion)::numeric, 1) FROM pedidos pe JOIN publicaciones p ON p.id = pe.publicacion_id
            WHERE p.usuaria_id = %s AND pe.estado = 'completado' AND pe.calificacion IS NOT NULL) AS calificacion
        """,
        (uid, uid, uid),
    )
    est = cur.fetchone()

    return {
        "seudonimo": base["seudonimo"],
        "avatar": base["avatar"],
        "nivel": {
            "nivel": base["nivel"],
            "nombre": base["nivel_nombre"],
            "descripcion": base["nivel_descripcion"],
            "actividades": base["actividades"],
            "actividades_siguiente": sig["actividades_requeridas"] if sig else None,
            "siguiente_nombre": sig["nombre"] if sig else None,
            "porcentaje": _porcentaje(base["actividades"], base["actividades_desde"],
                                      sig["actividades_requeridas"] if sig else None),
        },
        "lilu": {
            "nombre": base["mascota"],
            "flores": base["flores"],
            "etapa": actual["etapa"],
            "etapa_nombre": actual["nombre"],
            "flores_siguiente": siguiente["flores_requeridas"] if siguiente else None,
            "siguiente_nombre": siguiente["nombre"] if siguiente else None,
            "porcentaje": _porcentaje(base["flores"], actual["flores_requeridas"],
                                      siguiente["flores_requeridas"] if siguiente else None),
        },
        "estadisticas": {
            "retos_completados": est["retos"],
            "ventas_completadas": est["ventas"],
            "calificacion_promedio": float(est["calificacion"]) if est["calificacion"] is not None else None,
        },
    }


@router.get("/progreso/yo")
def mi_progreso(usuaria: dict = Depends(usuaria_modo_normal)):
    """Todo lo que necesitan Inicio, Perfil y Mascota en una sola llamada."""
    with obtener_conexion() as conn:
        with conn.cursor() as cur:
            return calcular_progreso(cur, usuaria["id"])


@router.get("/progreso/niveles")
def lista_niveles(usuaria: dict = Depends(usuaria_modo_normal)):
    """Los 10 niveles y las 3 etapas de Lilu (para mostrar el mapa completo)."""
    with obtener_conexion() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT nivel, nombre, descripcion, actividades_requeridas FROM niveles ORDER BY nivel")
            niveles = [dict(r) for r in cur.fetchall()]
            cur.execute("SELECT etapa, nombre, flores_requeridas FROM etapas_lilu ORDER BY etapa")
            etapas = [dict(r) for r in cur.fetchall()]
    return {"niveles": niveles, "etapas_lilu": etapas}


@router.get("/progreso/reglas")
def reglas_de_flores(usuaria: dict = Depends(usuaria_modo_normal)):
    """Cuántas flores da cada acción (así los textos de la app nunca se desfasan de la base)."""
    with obtener_conexion() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT clave, flores FROM reglas_recompensa")
            return {"reglas": {r["clave"]: r["flores"] for r in cur.fetchall()}}


class AvatarIn(BaseModel):
    avatar: str

    @field_validator("avatar")
    @classmethod
    def _avatar(cls, v: str) -> str:
        v = v.strip()
        if not 1 <= len(v) <= 8 or any(c.isalnum() or c.isspace() for c in v):
            raise ValueError("Elige un emoji como avatar")
        return v


@router.put("/perfil/avatar")
def cambiar_avatar(datos: AvatarIn, usuaria: dict = Depends(usuaria_modo_normal)):
    with obtener_conexion() as conn:
        try:
            with conn.cursor() as cur:
                cur.execute("UPDATE usuarias SET avatar = %s WHERE id = %s", (datos.avatar, usuaria["id"]))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    return {"avatar": datos.avatar}
