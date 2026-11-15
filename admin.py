"""Moderación de retos (issue 7.2). Rutas protegidas para el equipo; después las usará la web de administración.

Protección
- Todas piden el encabezado  X-Admin-Key  con la llave de la variable de entorno ADMIN_API_KEY (mínimo 32
  caracteres; se compara en tiempo constante). Si la variable no existe o es corta, estas rutas quedan
  APAGADAS (503): así nunca quedan abiertas por olvido. Las usuarias de la app no tienen forma de usarlas.
- La llave es del equipo: no va en la app ni en el repositorio, solo en Render y en el gestor de contraseñas.
  Para cambiarla basta con cambiar la variable.

Qué se puede hacer
- GET  /admin/retos/pendientes        retos en revisión (nuevos o ocultos por reportes), con sus reportes.
- POST /admin/retos/{id}/aprobar      pasa a 'abierto' y aparece en el tablero.
- POST /admin/retos/{id}/rechazar     pasa a 'rechazado' con un motivo (se le muestra a la publicadora).
Solo se puede revisar un reto que esté 'en_revision' (si no, 409). Los reportes del reto se marcan como
descartados (si se aprobó) o resueltos (si se rechazó). La publicadora recibe el resultado por correo y lo ve en
el detalle de su reto (GET /retos/{id}: reto_estado y motivo_rechazo).
"""
import hmac
import logging
import os

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel, field_validator

from avisos import avisar_publicadora
from db import obtener_conexion

log = logging.getLogger("crisalida.admin")
router = APIRouter(prefix="/admin", tags=["Administración (equipo)"])

LARGO_MIN_LLAVE = 32


def equipo(x_admin_key: str | None = Header(default=None)) -> None:
    """Deja pasar solo con la llave del equipo."""
    llave = os.getenv("ADMIN_API_KEY", "")
    if len(llave) < LARGO_MIN_LLAVE:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "La administración no está habilitada")
    if not x_admin_key or not hmac.compare_digest(x_admin_key.encode(), llave.encode()):
        log.warning("Intento de acceso a administración con llave incorrecta")
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "No autorizado")


class RechazoIn(BaseModel):
    motivo: str

    @field_validator("motivo")
    @classmethod
    def _motivo(cls, v: str) -> str:
        v = " ".join(v.split())
        if not 5 <= len(v) <= 300:
            raise ValueError("El motivo debe tener entre 5 y 300 caracteres")
        return v


@router.get("/retos/pendientes", dependencies=[Depends(equipo)])
def pendientes(limite: int = Query(50, ge=1, le=200), desde: int = Query(0, ge=0)):
    """Retos esperando revisión, los que traen reportes primero y luego los más viejos."""
    with obtener_conexion() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT r.id, r.titulo, r.descripcion, r.compensacion, r.fecha_limite, r.creado_en, r.revisado_en,
                          c.nombre AS categoria, u.seudonimo AS publicado_por,
                          count(x.id) AS reportes,
                          COALESCE(array_agg(DISTINCT x.motivo) FILTER (WHERE x.id IS NOT NULL), '{}') AS motivos
                     FROM retos r
                     JOIN categorias c ON c.id = r.categoria_id
                     LEFT JOIN usuarias u ON u.id = r.publicado_por
                     LEFT JOIN reportes x ON x.reto_id = r.id AND x.tipo = 'reto'
                                         AND x.creado_en > COALESCE(r.revisado_en, '-infinity')
                    WHERE r.estado = 'en_revision'
                    GROUP BY r.id, c.nombre, u.seudonimo
                    ORDER BY (count(x.id) > 0) DESC, r.creado_en
                    LIMIT %s OFFSET %s""", (limite, desde))
            filas = cur.fetchall()
    retos = []
    for f in filas:
        d = dict(f)
        d["id"] = str(d["id"])
        d["compensacion"] = float(d["compensacion"])
        d["por_reportes"] = d["reportes"] > 0   # True = llegó aquí (o se mantiene) por reportes
        retos.append(d)
    return {"retos": retos}


def _revisar(reto_id: str, aprobar: bool, motivo: str | None, segundo_plano: BackgroundTasks) -> dict:
    nuevo = "abierto" if aprobar else "rechazado"
    with obtener_conexion() as conn:
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT id, titulo, estado, publicado_por FROM retos WHERE id::text = %s FOR UPDATE", (reto_id,))
                r = cur.fetchone()
                if r is None:
                    raise HTTPException(status.HTTP_404_NOT_FOUND, "No encontramos ese reto")
                if r["estado"] != "en_revision":
                    raise HTTPException(status.HTTP_409_CONFLICT, f"Ese reto no está en revisión (estado: {r['estado']})")
                cur.execute("""UPDATE retos SET estado = %s, revisado_en = now(), motivo_rechazo = %s WHERE id = %s""",
                            (nuevo, None if aprobar else motivo, r["id"]))
                cur.execute("""UPDATE reportes SET estado = %s
                                WHERE reto_id = %s AND tipo = 'reto' AND estado IN ('nuevo', 'en_revision')""",
                            ("descartado" if aprobar else "resuelto", r["id"]))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    if aprobar:
        asunto = "Crisálida: tu reto fue aprobado"
        texto = (f"¡Buenas noticias! Tu reto «{r['titulo']}» fue aprobado y ya aparece en el tablero de retos "
                 "para que otras usuarias lo tomen.")
    else:
        asunto = "Crisálida: tu reto no fue aprobado"
        texto = (f"Revisamos tu reto «{r['titulo']}» y por ahora no pudimos aprobarlo.\n\nMotivo: {motivo}\n\n"
                 "Puedes publicar uno nuevo corrigiendo lo anterior.")
    segundo_plano.add_task(avisar_publicadora, r["publicado_por"], asunto, texto)
    return {"reto_id": str(r["id"]), "estado": nuevo}


@router.post("/retos/{reto_id}/aprobar", dependencies=[Depends(equipo)])
def aprobar(reto_id: str, segundo_plano: BackgroundTasks):
    return _revisar(reto_id, True, None, segundo_plano)


@router.post("/retos/{reto_id}/rechazar", dependencies=[Depends(equipo)])
def rechazar(reto_id: str, datos: RechazoIn, segundo_plano: BackgroundTasks):
    return _revisar(reto_id, False, datos.motivo, segundo_plano)