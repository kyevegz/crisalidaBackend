"""Recuperar el PIN (issue 4.6).

Dos caminos, ambos terminan fijando un PIN NUEVO:
  1. POST /auth/recuperar/codigo           seudónimo + código de recuperación (el que se mostró al registrarse)
  2. POST /auth/recuperar/correo/solicitar seudónimo + correo  -> manda un código de 6 letras y números al correo
     POST /auth/recuperar/correo/confirmar seudónimo + correo + código + PIN nuevo
     (solo si la cuenta tiene el correo VERIFICADO)

Reglas de seguridad:
- Límite de intentos como el login: 5 fallos seguidos = 15 minutos de bloqueo (contador propio de la
  recuperación, para que equivocarse aquí no bloquee el login ni al revés).
- Se pide seudónimo + correo porque el correo puede repetirse entre cuentas.
- «Recibir correo» responde SIEMPRE lo mismo, exista o no la cuenta (el correo se manda en segundo plano
  para que tampoco cambie el tiempo de respuesta).
- El PIN nuevo no puede ser igual al PIN de camuflaje. Esa comprobación se hace DESPUÉS de verificar el
  código, para no revelarle el PIN de camuflaje a quien no tiene el código.
- Un PIN nuevo sube `version_sesion`: todas las sesiones anteriores dejan de valer.
"""
import logging
import os

from fastapi import APIRouter, BackgroundTasks, HTTPException, status
from pydantic import BaseModel, field_validator

from correo import CORREO_RE, enviar_correo
from db import obtener_conexion
from seguridad import (
    HASH_FALSO,
    MAX_INTENTOS,
    MINUTOS_BLOQUEO,
    generar_codigo_recuperacion,
    hashear_codigo,
    hashear_pin,
    normalizar_codigo,
    validar_pin,
    verificar_codigo,
    verificar_pin,
)

log = logging.getLogger("crisalida.recuperacion")
router = APIRouter(prefix="/auth/recuperar", tags=["Recuperar PIN"])

CODIGO_MINUTOS = int(os.getenv("CORREO_CODIGO_MINUTOS", "15"))   # cuánto dura el código del correo
ESPERA_REENVIO_SEGUNDOS = 60    # mínimo entre un código y el siguiente
MAX_ENVIOS_DIA = 5              # códigos que se pueden pedir en 24 horas por cuenta
MAX_INTENTOS_CODIGO = 5         # equivocaciones con un mismo código de correo

# UN solo mensaje (y un solo código HTTP) para todos los fallos: datos incorrectos, cuenta inexistente, código
# vencido y cuenta bloqueada por intentos. Así nadie puede saber si un seudónimo existe, ni siquiera provocando
# el bloqueo. Incluye la pista de esperar para quien sí se bloqueó.
MENSAJE_FALLO = ("Los datos no son correctos, el código venció o hay demasiados intentos. "
                 "Espera unos minutos e inténtalo de nuevo")
MENSAJE_SOLICITUD = ("Si los datos coinciden con una cuenta con correo verificado, te enviamos un código. "
                     "Revisa tu bandeja de entrada y el correo no deseado.")
MENSAJE_LISTO = "Listo, tu PIN se actualizó. Inicia sesión con tu PIN nuevo."


# ============================================================ MODELOS

class _ConSeudonimo(BaseModel):
    seudonimo: str

    @field_validator("seudonimo")
    @classmethod
    def _seudonimo(cls, v: str) -> str:
        v = v.strip()
        if not (1 <= len(v) <= 30):
            raise ValueError("Escribe tu seudónimo")
        return v


class PorCodigoIn(_ConSeudonimo):
    codigo: str
    pin_nuevo: str

    @field_validator("codigo")
    @classmethod
    def _codigo(cls, v: str) -> str:
        v = normalizar_codigo(v.strip())
        if len(v) != 6:
            raise ValueError("El código de recuperación tiene 6 caracteres")
        return v


    @field_validator("pin_nuevo")
    @classmethod
    def _pin(cls, v: str) -> str:
        return validar_pin(v)   # 6 dígitos y no demasiado fácil de adivinar (mismas reglas que el registro)


class _ConCorreo(_ConSeudonimo):
    correo: str

    @field_validator("correo")
    @classmethod
    def _correo(cls, v: str) -> str:
        v = v.strip().lower()
        if len(v) > 254 or not CORREO_RE.match(v):
            raise ValueError("Escribe un correo válido")
        return v


class SolicitarCorreoIn(_ConCorreo):
    pass


class PorCorreoIn(_ConCorreo):
    codigo: str
    pin_nuevo: str

    @field_validator("codigo")
    @classmethod
    def _codigo(cls, v: str) -> str:
        v = normalizar_codigo(v.strip())   # tolera minúsculas, espacios y guiones
        if not (len(v) == 6 and v.isascii() and v.isalnum()):
            raise ValueError("El código tiene 6 caracteres (letras y números)")
        return v


    @field_validator("pin_nuevo")
    @classmethod
    def _pin(cls, v: str) -> str:
        return validar_pin(v)   # 6 dígitos y no demasiado fácil de adivinar (mismas reglas que el registro)


# ============================================================ AYUDAS

_CAMPOS = """id, pin_camuflaje_hash, codigo_recuperacion_hash,
             (recuperacion_bloqueada_hasta IS NOT NULL AND recuperacion_bloqueada_hasta > now()) AS bloqueada"""


def _registrar_fallo(cur, uid) -> None:
    """Suma un intento fallido de recuperación y, al llegar al máximo, bloquea (igual que el login)."""
    cur.execute(
        f"""UPDATE usuarias
            SET recuperacion_intentos = CASE WHEN recuperacion_intentos + 1 >= %s THEN 0
                                             ELSE recuperacion_intentos + 1 END,
                recuperacion_bloqueada_hasta = CASE WHEN recuperacion_intentos + 1 >= %s
                                                    THEN now() + interval '{MINUTOS_BLOQUEO} minutes'
                                                    ELSE recuperacion_bloqueada_hasta END
            WHERE id = %s""",
        (MAX_INTENTOS, MAX_INTENTOS, uid),
    )


def _fijar_pin(cur, u: dict, pin_nuevo: str, pin_hash: str) -> None:
    """Cambia el PIN (ya con el código verificado). El PIN nuevo no puede ser el de camuflaje."""
    if verificar_pin(pin_nuevo, u["pin_camuflaje_hash"]):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "El PIN nuevo debe ser distinto al PIN de camuflaje")
    cur.execute(
        """UPDATE usuarias
           SET pin_hash = %s,
               version_sesion = version_sesion + 1,   -- las sesiones anteriores dejan de valer
               intentos_fallidos = 0, bloqueada_hasta = NULL,
               recuperacion_intentos = 0, recuperacion_bloqueada_hasta = NULL
           WHERE id = %s""",
        (pin_hash, u["id"]),
    )
    cur.execute("DELETE FROM recuperaciones_pin WHERE usuaria_id = %s", (u["id"],))


def _enviar_codigo(destino: str, codigo: str, solicitud_id: int) -> None:
    """Se ejecuta en segundo plano, después de responder."""
    texto = (f"Tu código para recuperar tu PIN de Crisálida es {codigo}.\n\n"
             f"Vence en {CODIGO_MINUTOS} minutos. Si no lo pediste, ignora este mensaje: tu PIN no cambia.")
    if not enviar_correo(destino, "Código para recuperar tu PIN", texto):
        # No salió: se quita la solicitud para que no cuente en los límites
        try:
            with obtener_conexion() as conn:
                with conn.cursor() as cur:
                    cur.execute("DELETE FROM recuperaciones_pin WHERE id = %s", (solicitud_id,))
                conn.commit()
        except Exception:
            log.exception("No se pudo limpiar la solicitud de recuperación")


# ============================================================ CON EL CÓDIGO DE RECUPERACIÓN

@router.post("/codigo")
def recuperar_con_codigo(datos: PorCodigoIn):
    """Fija un PIN nuevo con el seudónimo y el código de recuperación del registro."""
    pin_hash = hashear_pin(datos.pin_nuevo)   # lo pesado, antes de pedir la conexión
    with obtener_conexion() as conn:
        try:
            with conn.cursor() as cur:
                cur.execute(f"SELECT {_CAMPOS} FROM usuarias WHERE lower(seudonimo) = lower(%s) FOR UPDATE",
                            (datos.seudonimo,))
                u = cur.fetchone()
                if u is None or u["codigo_recuperacion_hash"] is None:
                    verificar_codigo(datos.codigo, HASH_FALSO)   # mismo tiempo que un fallo real
                    raise HTTPException(status.HTTP_400_BAD_REQUEST, MENSAJE_FALLO)
                if u["bloqueada"]:
                    verificar_codigo(datos.codigo, HASH_FALSO)   # mismo tiempo y mismo mensaje que un fallo cualquiera
                    raise HTTPException(status.HTTP_400_BAD_REQUEST, MENSAJE_FALLO)

                if not verificar_codigo(datos.codigo, u["codigo_recuperacion_hash"]):
                    _registrar_fallo(cur, u["id"])
                    conn.commit()   # el fallo se cuenta aunque la petición termine en error
                    raise HTTPException(status.HTTP_400_BAD_REQUEST, MENSAJE_FALLO)

                _fijar_pin(cur, u, datos.pin_nuevo, pin_hash)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    return {"mensaje": MENSAJE_LISTO}


# ============================================================ CON CÓDIGO ENVIADO AL CORREO

@router.post("/correo/solicitar")
def solicitar_codigo_por_correo(datos: SolicitarCorreoIn, segundo_plano: BackgroundTasks):
    """Manda un código al correo SI el seudónimo y el correo coinciden con una cuenta con correo verificado.
    La respuesta es siempre la misma: no dice si la cuenta existe."""
    codigo = generar_codigo_recuperacion()   # 6 letras y números (sin 0/O/1/I, que se confunden)
    codigo_hash = hashear_codigo(codigo)     # se hace siempre, exista o no la cuenta (mismo tiempo)
    envio = None
    with obtener_conexion() as conn:
        try:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM recuperaciones_pin WHERE creado_en < now() - interval '1 day'")
                cur.execute(
                    """SELECT id, correo FROM usuarias
                        WHERE lower(seudonimo) = lower(%s) AND correo_verificado AND lower(correo) = %s
                        FOR UPDATE""",
                    (datos.seudonimo, datos.correo),
                )
                u = cur.fetchone()
                if u is not None:
                    cur.execute(
                        """SELECT count(*) AS total,
                                  coalesce(max(creado_en) > now() - make_interval(secs => %s), FALSE) AS reciente
                             FROM recuperaciones_pin WHERE usuaria_id = %s""",
                        (ESPERA_REENVIO_SEGUNDOS, u["id"]),
                    )
                    limites = cur.fetchone()
                    # Si pasa algún límite no se manda nada, pero se responde igual (no se revela nada)
                    if limites["total"] < MAX_ENVIOS_DIA and not limites["reciente"]:
                        cur.execute(
                            """INSERT INTO recuperaciones_pin (usuaria_id, codigo_hash, expira_en)
                               VALUES (%s, %s, now() + make_interval(mins => %s)) RETURNING id""",
                            (u["id"], codigo_hash, CODIGO_MINUTOS),
                        )
                        envio = (u["correo"], cur.fetchone()["id"])
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    if envio is not None:
        segundo_plano.add_task(_enviar_codigo, envio[0], codigo, envio[1])
    return {"mensaje": MENSAJE_SOLICITUD, "expira_en_minutos": CODIGO_MINUTOS}


@router.post("/correo/confirmar")
def recuperar_con_correo(datos: PorCorreoIn):
    """Fija un PIN nuevo con seudónimo + correo + el código de 6 dígitos que llegó al correo."""
    pin_hash = hashear_pin(datos.pin_nuevo)
    with obtener_conexion() as conn:
        try:
            with conn.cursor() as cur:
                cur.execute(
                    f"""SELECT {_CAMPOS} FROM usuarias
                         WHERE lower(seudonimo) = lower(%s) AND correo_verificado AND lower(correo) = %s
                         FOR UPDATE""",
                    (datos.seudonimo, datos.correo),
                )
                u = cur.fetchone()
                if u is None or u["bloqueada"]:
                    verificar_codigo(datos.codigo, HASH_FALSO)   # cuenta inexistente o bloqueada: mismo tiempo y mismo mensaje
                    raise HTTPException(status.HTTP_400_BAD_REQUEST, MENSAJE_FALLO)

                # Solo vale el código más reciente, sin usar y vigente
                cur.execute(
                    """SELECT id, codigo_hash, intentos FROM recuperaciones_pin
                        WHERE usuaria_id = %s AND NOT usado AND expira_en > now()
                        ORDER BY creado_en DESC LIMIT 1 FOR UPDATE""",
                    (u["id"],),
                )
                pedido = cur.fetchone()
                if pedido is None or pedido["intentos"] >= MAX_INTENTOS_CODIGO:
                    verificar_codigo(datos.codigo, HASH_FALSO)
                    _registrar_fallo(cur, u["id"])
                    conn.commit()
                    raise HTTPException(status.HTTP_400_BAD_REQUEST, MENSAJE_FALLO)

                if not verificar_codigo(datos.codigo, pedido["codigo_hash"]):
                    cur.execute("UPDATE recuperaciones_pin SET intentos = intentos + 1 WHERE id = %s", (pedido["id"],))
                    _registrar_fallo(cur, u["id"])
                    conn.commit()
                    raise HTTPException(status.HTTP_400_BAD_REQUEST, MENSAJE_FALLO)

                # _fijar_pin borra todos los códigos pendientes (este incluido) al terminar
                _fijar_pin(cur, u, datos.pin_nuevo, pin_hash)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    return {"mensaje": MENSAJE_LISTO}