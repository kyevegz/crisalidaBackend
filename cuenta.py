"""Estado de la cuenta: suspender, reactivar (issue 6.1) y borrar (issue 6.2).

- Cuenta SUSPENDIDA («en reposo»): sus productos, servicios y retos dejan de verse en el marketplace y en el
  tablero de retos (ver marketplace.py y retos.py). No se borra nada.
- Sigue pudiendo entrar y usar la mascota, el bienestar y todo lo demás de su cuenta: suspender oculta lo que
  ella publica, no la encierra.
- Reactivar devuelve todo a como estaba.
- Los dos endpoints son idempotentes: suspender una cuenta ya suspendida (o reactivar una activa) no falla.
- Solo funcionan en modo normal (no en el camuflaje).

Borrar la cuenta (6.2): POST /cuenta/borrar con el PIN.
- Pide el PIN para confirmar (un PIN incorrecto cuenta para el bloqueo, igual que en el login).
- Si hay pedidos en curso en sus publicaciones, o retos en curso (que ella hace o que ella publicó y alguien
  hace), responde 409 y ofrece suspender la cuenta en su lugar.
- Si no los hay, borra la cuenta y con ella (en cascada) sus datos personales, bitácora y emociones,
  publicaciones con sus fotos, mascota, progreso, bloqueos y aceptaciones de retos. Sus retos publicados que
  seguían abiertos se cancelan. Los reportes que hizo o que le hicieron se conservan sin su identidad (para el equipo).
- Después el token deja de servir: la sesión se valida contra la base y la usuaria ya no existe (401).
"""
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, field_validator

from db import obtener_conexion
from dependencias import usuaria_modo_normal
from seguridad import MAX_INTENTOS, MINUTOS_BLOQUEO, PIN_RE, verificar_pin

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


# ============================================================ BORRAR LA CUENTA

class BorrarIn(BaseModel):
    pin: str

    @field_validator("pin")
    @classmethod
    def _pin(cls, v: str) -> str:
        if not PIN_RE.match(v):
            raise ValueError("El PIN tiene 6 dígitos")
        return v


MENSAJE_EN_CURSO = ("Tienes pedidos o retos en curso, así que todavía no podemos borrar tu cuenta. "
                    "Termínalos o, si prefieres descansar sin perder nada, suspende tu cuenta.")


def _en_curso(cur, uid) -> bool:
    """¿Hay pedidos o retos sin terminar ligados a ella?"""
    cur.execute(
        """SELECT
             EXISTS (SELECT 1 FROM pedidos pe JOIN publicaciones p ON p.id = pe.publicacion_id
                      WHERE p.usuaria_id = %(u)s AND pe.estado IN ('pendiente', 'en_custodia', 'entregado'))
          OR EXISTS (SELECT 1 FROM reto_aceptaciones a
                      WHERE a.usuaria_id = %(u)s AND a.estado IN ('aceptado', 'entregado'))
          OR EXISTS (SELECT 1 FROM reto_aceptaciones a JOIN retos r ON r.id = a.reto_id
                      WHERE r.publicado_por = %(u)s AND a.estado IN ('aceptado', 'entregado')) AS en_curso""",
        {"u": uid},
    )
    return cur.fetchone()["en_curso"]


@router.post("/borrar")
def borrar_cuenta(datos: BorrarIn, usuaria: dict = Depends(usuaria_modo_normal)):
    """Borra la cuenta y sus datos. Pide el PIN. Con pedidos o retos en curso responde 409 (ofrece suspender)."""
    uid = usuaria["id"]
    with obtener_conexion() as conn:
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT pin_hash, (bloqueada_hasta IS NOT NULL AND bloqueada_hasta > now()) AS bloqueada
                         FROM usuarias WHERE id = %s FOR UPDATE""", (uid,))
                u = cur.fetchone()
                if u is None:
                    raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sesión inválida o expirada")
                if u["bloqueada"]:
                    raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS,
                                        "Demasiados intentos. Intenta de nuevo en unos minutos")

                if not verificar_pin(datos.pin, u["pin_hash"]):
                    # Igual que el login: se suma el intento y, al llegar al máximo, se bloquea
                    cur.execute(
                        f"""UPDATE usuarias
                            SET intentos_fallidos = CASE WHEN intentos_fallidos + 1 >= %s THEN 0
                                                         ELSE intentos_fallidos + 1 END,
                                bloqueada_hasta   = CASE WHEN intentos_fallidos + 1 >= %s
                                                         THEN now() + interval '{MINUTOS_BLOQUEO} minutes'
                                                         ELSE bloqueada_hasta END
                            WHERE id = %s""", (MAX_INTENTOS, MAX_INTENTOS, uid))
                    conn.commit()
                    raise HTTPException(status.HTTP_401_UNAUTHORIZED, "PIN incorrecto")

                if _en_curso(cur, uid):
                    raise HTTPException(status.HTTP_409_CONFLICT, MENSAJE_EN_CURSO)

                # Sus retos publicados que seguían abiertos se cancelan (los demás quedan sin dueña)
                cur.execute("""UPDATE retos SET estado = 'cancelado'
                                WHERE publicado_por = %s AND estado IN ('en_revision', 'abierto')""", (uid,))
                # Los pedidos ya terminados de sus publicaciones se borran con ellas (la tabla no los borra sola)
                cur.execute("""DELETE FROM pedidos WHERE publicacion_id IN
                                 (SELECT id FROM publicaciones WHERE usuaria_id = %s)""", (uid,))
                # Todo lo demás (datos personales, bitácora, publicaciones y fotos, mascota, progreso, bloqueos,
                # aceptaciones de retos...) se borra en cascada al borrar la cuenta
                cur.execute("DELETE FROM usuarias WHERE id = %s", (uid,))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    return {"borrada": True, "mensaje": "Tu cuenta y tus datos se borraron. Gracias por haber estado en Crisálida."}