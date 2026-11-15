"""Avisos por correo a la publicadora de un reto (resultado de la revisión, reto en revisión por reportes).
Se usan siempre en segundo plano (BackgroundTasks): nunca rompen la petición. Solo se manda si la usuaria tiene
correo VERIFICADO (para publicar un reto ya lo necesita)."""
import logging

from correo import enviar_correo
from db import obtener_conexion

log = logging.getLogger("crisalida.avisos")


def avisar_publicadora(usuaria_id, asunto: str, texto: str) -> None:
    if usuaria_id is None:
        return
    try:
        with obtener_conexion() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT correo FROM usuarias WHERE id = %s AND correo_verificado AND correo IS NOT NULL",
                            (usuaria_id,))
                fila = cur.fetchone()
        if fila:
            enviar_correo(fila["correo"], asunto, texto)
    except Exception:
        log.exception("No se pudo avisar a la publicadora del reto")