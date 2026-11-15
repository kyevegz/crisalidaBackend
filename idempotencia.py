"""Idempotencia (issue 5.1).

La app manda un identificador único por cada cosa que crea, en el encabezado `Idempotency-Key`
(un UUID que genera el teléfono). Si el mismo identificador llega otra vez, no se crea nada
nuevo, no se dan flores otra vez y se devuelve la misma respuesta de la primera vez.

- El encabezado es OPCIONAL: sin él, el endpoint funciona como antes (así no se rompe la app actual).
- La clave se guarda en la MISMA transacción que el dato: o quedan los dos o no queda ninguno.
- Si dos reenvíos llegan al mismo tiempo, el segundo espera al primero (llave primaria) y luego
  recibe su respuesta; nunca se guarda doble.
- La clave es por usuaria: la de otra persona no choca ni se puede leer.
"""
import uuid

from fastapi import Header, HTTPException, status
from psycopg2.extras import Json


def clave_idempotencia(idempotency_key: str | None = Header(default=None)) -> str | None:
    """Dependencia de FastAPI: lee y valida el encabezado Idempotency-Key (UUID). Devuelve None si no viene."""
    if idempotency_key is None or not idempotency_key.strip():
        return None
    try:
        return str(uuid.UUID(idempotency_key.strip()))
    except ValueError:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Idempotency-Key debe ser un UUID")


def reservar(cur, usuaria_id, clave: str, operacion: str):
    """Intenta reservar la clave dentro de la transacción actual.
    - Si es nueva: la reserva y devuelve None (el endpoint debe seguir y crear el dato).
    - Si ya existe: devuelve la respuesta guardada (el endpoint la regresa tal cual, sin crear nada).
    Si la clave se usó antes para OTRA operación responde 409."""
    cur.execute(
        """INSERT INTO operaciones_idempotentes (usuaria_id, clave, operacion)
           VALUES (%s, %s, %s) ON CONFLICT DO NOTHING RETURNING clave""",
        (usuaria_id, clave, operacion),
    )
    if cur.fetchone() is not None:
        return None
    cur.execute(
        "SELECT operacion, respuesta FROM operaciones_idempotentes WHERE usuaria_id = %s AND clave = %s",
        (usuaria_id, clave),
    )
    previa = cur.fetchone()
    if previa["operacion"] != operacion or previa["respuesta"] is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Ese identificador ya se usó en otra operación")
    return previa["respuesta"]


def guardar_respuesta(cur, usuaria_id, clave: str, respuesta: dict) -> None:
    """Guarda la respuesta que se dio, para repetirla si el cliente reenvía."""
    cur.execute(
        "UPDATE operaciones_idempotentes SET respuesta = %s WHERE usuaria_id = %s AND clave = %s",
        (Json(respuesta), usuaria_id, clave),
    )