"""Cambiar de rol: vendedora <-> compradora (issue 6.4).

Pasar a COMPRADORA oculta lo de vendedora, NO lo borra:
- Bienestar, mascota/progreso y portafolio dejan de estar disponibles: esos endpoints ya exigen rol de vendedora
  (dependencias.usuaria_vendedora) y el rol se lee SIEMPRE de la base de datos, no del token. Así el cambio vale
  al instante en todos sus dispositivos, aunque tengan un token anterior.
- Sus publicaciones desaparecen del marketplace y sus fotos dejan de servirse (marketplace.py y publicaciones.py
  piden rol de vendedora). Nada se borra: ni bitácora, ni emociones, ni publicaciones, ni progreso, ni la mascota.
- Los datos ocultos no los ve nadie ni cuentan en estadísticas. Regla para cualquier estadística o consulta nueva:
  solo se toman en cuenta cuentas con  rol = 'vendedora' AND estado = 'activa'.

Volver a VENDEDORA: todo reaparece tal como estaba (nunca se tocó).

Pedidos y retos en curso NO se pierden: no se puede cambiar de rol (en ningún sentido) mientras haya pedidos o
retos sin terminar. Igual que al borrar la cuenta, responde 409 y pide terminarlos primero; así nada queda a medias
ni se vuelve inalcanzable. Cuenta como «en curso»: pedidos pendientes, en custodia o entregados en sus publicaciones,
retos que ella hace (aceptados o entregados) y retos que ella publicó y alguien está haciendo.

El cambio devuelve una sesión nueva (con el mismo formato del login) para que la app actualice la barra de
navegación y el Perfil sin pedir el PIN otra vez. No cierra las demás sesiones.
"""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from db import obtener_conexion
from dependencias import usuaria_modo_normal
from seguridad import crear_token

router = APIRouter(prefix="/cuenta", tags=["Cuenta"])

MENSAJES = {
    "compradora": ("Listo, ahora eres compradora. Tu mascota, tu bienestar y tu portafolio quedaron guardados "
                   "y ocultos: nadie los ve y no se borraron. Cuando quieras volver a vender, todo reaparece."),
    "vendedora": "¡Bienvenida de vuelta! Tu mascota, tu bienestar y tu portafolio reaparecieron tal como estaban.",
}
MENSAJE_EN_CURSO = ("Tienes pedidos o retos en curso. Termínalos antes de cambiar de rol, "
                    "así no se queda nada a medias.")


class CambioRolIn(BaseModel):
    rol: Literal["vendedora", "compradora"]


def _en_curso(cur, uid) -> dict:
    """Cuántos pedidos y retos sin terminar tiene (se conservan al cambiar de rol)."""
    cur.execute(
        """SELECT
             (SELECT count(*) FROM pedidos pe JOIN publicaciones p ON p.id = pe.publicacion_id
               WHERE p.usuaria_id = %(u)s AND pe.estado IN ('pendiente', 'en_custodia', 'entregado')) AS pedidos,
             (SELECT count(*) FROM reto_aceptaciones a
               WHERE a.usuaria_id = %(u)s AND a.estado IN ('aceptado', 'entregado')) AS retos_que_hace,
             (SELECT count(*) FROM reto_aceptaciones a JOIN retos r ON r.id = a.reto_id
               WHERE r.publicado_por = %(u)s AND a.estado IN ('aceptado', 'entregado')) AS retos_que_publico""",
        {"u": uid},
    )
    f = cur.fetchone()
    return {"pedidos": f["pedidos"], "retos": f["retos_que_hace"] + f["retos_que_publico"]}


@router.get("/rol")
def mi_rol(usuaria: dict = Depends(usuaria_modo_normal)):
    """Rol actual y lo que tiene en curso. `puede_cambiar` es false mientras haya algo en curso
    (la app lo usa para explicar el cambio antes de hacerlo o desactivar el botón)."""
    with obtener_conexion() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT rol FROM usuarias WHERE id = %s", (usuaria["id"],))
            u = cur.fetchone()
            if u is None:
                raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sesión inválida o expirada")
            en_curso = _en_curso(cur, usuaria["id"])
            return {"rol": u["rol"], "en_curso": en_curso,
                    "puede_cambiar": en_curso["pedidos"] == 0 and en_curso["retos"] == 0}


@router.post("/rol")
def cambiar_rol(datos: CambioRolIn, usuaria: dict = Depends(usuaria_modo_normal)):
    """Cambia el rol. No borra nada. Con pedidos o retos en curso responde 409 (hay que terminarlos primero).
    Si ya tiene ese rol responde lo mismo, sin fallar."""
    uid = usuaria["id"]
    with obtener_conexion() as conn:
        try:
            with conn.cursor() as cur:
                cur.execute("""SELECT seudonimo, avatar, rol, estado, version_sesion
                                 FROM usuarias WHERE id = %s FOR UPDATE""", (uid,))
                u = cur.fetchone()
                if u is None:
                    raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sesión inválida o expirada")
                cambio = u["rol"] != datos.rol
                en_curso = _en_curso(cur, uid)
                if cambio:
                    if en_curso["pedidos"] or en_curso["retos"]:
                        raise HTTPException(status.HTTP_409_CONFLICT, MENSAJE_EN_CURSO)
                    cur.execute("UPDATE usuarias SET rol = %s WHERE id = %s", (datos.rol, uid))
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    mensaje = MENSAJES[datos.rol] if cambio else "Tu cuenta ya tenía ese rol."
    return {
        # mismo formato que el login: la app actualiza su sesión sin pedir el PIN otra vez
        "usuaria_id": str(uid),
        "seudonimo": u["seudonimo"],
        "avatar": u["avatar"],
        "modo": "normal",
        "token": crear_token(str(uid), "normal", datos.rol, u["version_sesion"]),
        "rol": datos.rol,
        "estado": u["estado"],
        "cambio": cambio,
        "en_curso": en_curso,
        "mensaje": mensaje,
    }