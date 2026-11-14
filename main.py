import re

from fastapi import Depends, FastAPI, HTTPException, Query, status
from psycopg2 import errors as pg_errors
from pydantic import BaseModel, field_validator, model_validator

from db import obtener_conexion
from dependencias import sesion_registro, usuaria_actual
from radar import (
    RadarCompletoIn,
    guardar_perfil,
    limpiar_respuestas,
    perfil_desde_cliente,
    router as radar_router,
)
from bienestar import router as bienestar_router
from demo import MODO_DEMO, router as demo_router
from marketplace import router as marketplace_router
from progreso import router as progreso_router
from publicaciones import router as publicaciones_router
from retos import router as retos_router
from seguridad import HASH_FALSO, crear_token, crear_token_registro, hashear_pin, verificar_pin

app = FastAPI(title="API Crisálida", version="0.1.0")
app.include_router(radar_router)   # /radar/...
app.include_router(progreso_router)        # /progreso/..., /perfil/avatar
app.include_router(marketplace_router)     # /categorias, /marketplace
app.include_router(retos_router)           # /retos/...
app.include_router(publicaciones_router)   # /publicaciones/..., /imagenes/...
app.include_router(bienestar_router)       # /bienestar/...
if MODO_DEMO:                              # atajos para la presentación (apagados por defecto)
    app.include_router(demo_router)        # /demo/...

SEUDONIMO_RE = re.compile(r"^\w{3,30}$")   # letras, números y guion bajo
PIN_RE = re.compile(r"^\d{6}$")
PINS_DEBILES = {"123456", "654321", "123123", "121212", "112233", "012345"}
MAX_INTENTOS = 5          # fallos seguidos antes de bloquear
MINUTOS_BLOQUEO = 15
MENSAJE_CREDENCIALES = "Seudónimo o PIN incorrectos"


# ============================================================ MODELOS

def _validar_pin(pin: str) -> str:
    if not PIN_RE.match(pin):
        raise ValueError("El PIN debe tener exactamente 6 dígitos")
    if len(set(pin)) == 1 or pin in PINS_DEBILES:
        raise ValueError("Ese PIN es muy fácil de adivinar, elige otro")
    return pin


class RegistroIn(BaseModel):
    seudonimo: str
    pin: str
    pin_camuflaje: str

    @field_validator("seudonimo")
    @classmethod
    def _seudonimo(cls, v: str) -> str:
        v = v.strip()
        if not SEUDONIMO_RE.match(v):
            raise ValueError("El seudónimo debe tener de 3 a 30 letras, números o guion bajo")
        return v

    @field_validator("pin", "pin_camuflaje")
    @classmethod
    def _pins(cls, v: str) -> str:
        return _validar_pin(v)

    @model_validator(mode="after")
    def _pins_distintos(self):
        if self.pin == self.pin_camuflaje:
            raise ValueError("El PIN de camuflaje debe ser distinto al PIN principal")
        return self


class LoginIn(BaseModel):
    seudonimo: str
    pin: str


class SesionOut(BaseModel):
    usuaria_id: str
    seudonimo: str
    avatar: str
    modo: str      # "normal" o "camuflaje" (en camuflaje la app muestra la galería de mariposas)
    token: str


class RegistroCompletoIn(RegistroIn):
    """Credenciales + radar completo, todo junto: la cuenta se crea hasta terminar el radar."""
    radar: RadarCompletoIn


class TokenRegistroOut(BaseModel):
    token_registro: str   # pase temporal: solo sirve para el radar y para /auth/registro-completo


# ============================================================ ENDPOINTS

@app.get("/")
def estado():
    return {"ok": True, "servicio": "API Crisálida"}


@app.get("/auth/seudonimo-disponible")
def seudonimo_disponible(seudonimo: str = Query(..., min_length=1, max_length=60)):
    """Para validar el seudónimo mientras la usuaria lo escribe en el registro."""
    seudonimo = seudonimo.strip()
    if not SEUDONIMO_RE.match(seudonimo):
        return {"disponible": False, "motivo": "Usa de 3 a 30 letras, números o guion bajo"}
    with obtener_conexion() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM usuarias WHERE lower(seudonimo) = lower(%s)", (seudonimo,))
            existe = cur.fetchone() is not None
    return {"disponible": not existe, "motivo": "Ese seudónimo ya está en uso" if existe else None}


@app.post("/auth/validar-registro", response_model=TokenRegistroOut)
def validar_registro(datos: RegistroIn):
    """Paso 1 del registro (botón "Siguiente"): valida seudónimo y PINs SIN crear la cuenta.
    Devuelve un pase temporal para poder usar el radar mientras todavía no existe la usuaria."""
    with obtener_conexion() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM usuarias WHERE lower(seudonimo) = lower(%s)", (datos.seudonimo,))
            if cur.fetchone() is not None:
                raise HTTPException(status.HTTP_409_CONFLICT, "Ese seudónimo ya está en uso")
    return TokenRegistroOut(token_registro=crear_token_registro(datos.seudonimo))


@app.post("/auth/registro-completo", response_model=SesionOut, status_code=status.HTTP_201_CREATED)
def registrar_completo(datos: RegistroCompletoIn, sesion: dict = Depends(sesion_registro)):
    """Paso final (segundo "Terminar" del radar): crea usuaria + mascota + perfil en UNA transacción.
    Si algo falla no queda nada a medias."""
    # El pase se emitió para un seudónimo concreto: no se puede usar para registrar otro
    if sesion["id"].lower() != datos.seudonimo.lower():
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Sesión de registro inválida")

    # Todo lo pesado (hash de PIN) y la validación van ANTES de pedir la conexión
    pin_hash = hashear_pin(datos.pin)
    camuflaje_hash = hashear_pin(datos.pin_camuflaje)
    radar = datos.radar
    respuestas = limpiar_respuestas(radar.respuestas)
    perfil = perfil_desde_cliente(radar.perfil, radar.actividades)

    with obtener_conexion() as conn:
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO usuarias (seudonimo, pin_hash, pin_camuflaje_hash)
                    VALUES (%s, %s, %s)
                    RETURNING id, seudonimo, avatar
                    """,
                    (datos.seudonimo, pin_hash, camuflaje_hash),
                )
                usuaria = cur.fetchone()
                # C1-01: cada usuaria nace con su mascota (relación 1:1)...
                cur.execute("INSERT INTO mascotas (usuaria_id) VALUES (%s)", (usuaria["id"],))
                # ...y con su perfil inicial (RF-03), todo en la misma transacción
                guardar_perfil(cur, usuaria["id"], radar.actividades, radar.tiempo, respuestas, perfil)
            conn.commit()
        except pg_errors.UniqueViolation:
            conn.rollback()
            raise HTTPException(status.HTTP_409_CONFLICT, "Ese seudónimo ya está en uso")
        except Exception:
            conn.rollback()
            raise

    uid = str(usuaria["id"])
    return SesionOut(
        usuaria_id=uid,
        seudonimo=usuaria["seudonimo"],
        avatar=usuaria["avatar"],
        modo="normal",
        token=crear_token(uid, "normal"),
    )


@app.post("/auth/login", response_model=SesionOut)
def iniciar_sesion(datos: LoginIn):
    with obtener_conexion() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, seudonimo, avatar, pin_hash, pin_camuflaje_hash,
                       bloqueada_hasta, (bloqueada_hasta IS NOT NULL AND bloqueada_hasta > now()) AS bloqueada
                FROM usuarias
                WHERE lower(seudonimo) = lower(%s)
                """,
                (datos.seudonimo.strip(),),
            )
            u = cur.fetchone()

            if u is None:
                verificar_pin(datos.pin, HASH_FALSO)  # mismo tiempo de respuesta que un fallo real
                raise HTTPException(status.HTTP_401_UNAUTHORIZED, MENSAJE_CREDENCIALES)

            if u["bloqueada"]:
                raise HTTPException(
                    status.HTTP_429_TOO_MANY_REQUESTS,
                    "Demasiados intentos. Intenta de nuevo en unos minutos",
                )

            if verificar_pin(datos.pin, u["pin_hash"]):
                modo = "normal"
            elif verificar_pin(datos.pin, u["pin_camuflaje_hash"]):
                modo = "camuflaje"
            else:
                # Fallo: se suma el intento y, al llegar al máximo, se bloquea (todo en un solo UPDATE)
                cur.execute(
                    f"""
                    UPDATE usuarias
                    SET intentos_fallidos = CASE WHEN intentos_fallidos + 1 >= %s THEN 0
                                                 ELSE intentos_fallidos + 1 END,
                        bloqueada_hasta   = CASE WHEN intentos_fallidos + 1 >= %s
                                                 THEN now() + interval '{MINUTOS_BLOQUEO} minutes'
                                                 ELSE bloqueada_hasta END
                    WHERE id = %s
                    """,
                    (MAX_INTENTOS, MAX_INTENTOS, u["id"]),
                )
                conn.commit()
                raise HTTPException(status.HTTP_401_UNAUTHORIZED, MENSAJE_CREDENCIALES)

            cur.execute(
                "UPDATE usuarias SET intentos_fallidos = 0, bloqueada_hasta = NULL WHERE id = %s",
                (u["id"],),
            )
        conn.commit()

    uid = str(u["id"])
    return SesionOut(
        usuaria_id=uid,
        seudonimo=u["seudonimo"],
        avatar=u["avatar"],
        modo=modo,
        token=crear_token(uid, modo),
    )


@app.get("/auth/yo")
def mi_sesion(usuaria: dict = Depends(usuaria_actual)):
    """Valida que el token siga vigente (la app lo puede llamar al abrirse)."""
    with obtener_conexion() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT seudonimo, avatar FROM usuarias WHERE id = %s", (usuaria["id"],))
            u = cur.fetchone()
    if u is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sesión inválida o expirada")
    return {"usuaria_id": usuaria["id"], "seudonimo": u["seudonimo"], "avatar": u["avatar"], "modo": usuaria["modo"]}