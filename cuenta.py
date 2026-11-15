"""Estado de la cuenta: suspender y reactivar (issue 6.1).

- Cuenta SUSPENDIDA («en reposo»): sus productos, servicios y retos dejan de verse en el marketplace y en el
  tablero de retos (ver marketplace.py y retos.py). No se borra nada.
- Sigue pudiendo entrar y usar la mascota, el bienestar y todo lo demás de su cuenta: suspender oculta lo que
  ella publica, no la encierra.
- Reactivar devuelve todo a como estaba.
- Los dos endpoints son idempotentes: suspender una cuenta ya suspendida (o reactivar una activa) no falla.
- Solo funcionan en modo normal (no en el camuflaje).
"""
from fastapi import APIRouter, Depends, HTTPException, status

from db import obtener_conexion
from dependencias import usuaria_modo_normal

router = APIRouter(prefix="/cuenta", tags=["Cuenta"])


def _estado(cur, uid) -> dict:
    cur.execute("SELECT estado, suspendida_en FROM usuarias WHERE id = %s", (uid,))
    u = cur.fetchone()
    if u is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Usuaria no encontrada")
    return {"estado": u["estado"], "suspendida_en": u["suspendida_en"]}


@router.get("/estado")
def mi_estado(usuaria: dict = Depends(usuaria_modo_normal)):
    with obtener_conexion() as conn:
        with conn.cursor() as cur:
            return _estado(cur, usuaria["id"])


@router.post("/suspender")
def suspender(usuaria: dict = Depends(usuaria_modo_normal)):
    """Pone la cuenta en reposo: sus publicaciones dejan de verse hasta que la reactive."""
    with obtener_conexion() as conn:
        try:
            with conn.cursor() as cur:
                cur.execute("""UPDATE usuarias SET estado = 'suspendida', suspendida_en = now()
                                WHERE id = %s AND estado = 'activa'""", (usuaria["id"],))
                resultado = _estado(cur, usuaria["id"])
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    return {**resultado, "mensaje": "Tu cuenta está en reposo. Tus publicaciones no se muestran, "
                                    "pero puedes seguir usando tu mascota y tu bienestar."}


@router.post("/reactivar")
def reactivar(usuaria: dict = Depends(usuaria_modo_normal)):
    """Reactiva la cuenta: sus publicaciones vuelven a verse."""
    with obtener_conexion() as conn:
        try:
            with conn.cursor() as cur:
                cur.execute("""UPDATE usuarias SET estado = 'activa', suspendida_en = NULL
                                WHERE id = %s AND estado = 'suspendida'""", (usuaria["id"],))
                resultado = _estado(cur, usuaria["id"])
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    return {**resultado, "mensaje": "¡Bienvenida de vuelta! Tu cuenta está activa y tus publicaciones vuelven a verse."}